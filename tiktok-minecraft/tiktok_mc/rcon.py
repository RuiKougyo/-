"""Minecraft（Java版）のサーバーにコマンドを送る「RCON」という仕組みのクライアント。

サーバーの server.properties で enable-rcon=true にすると、
外部からパスワード付きでコマンドを送れるようになります。
ここではその通信手順を、追加のライブラリなしで実装しています。
"""

from __future__ import annotations

import asyncio
import itertools
import struct

_TYPE_RESPONSE = 0
_TYPE_COMMAND = 2
_TYPE_AUTH = 3

# Minecraftが受け付けるコマンド本文の最大バイト数
MAX_COMMAND_BYTES = 1446


class RconError(Exception):
    """RCONの接続やコマンド送信に失敗したときのエラー。"""


class RconAuthError(RconError):
    """パスワードが違うときのエラー（再接続しても直らない）。"""


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        await self.close()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (OSError, asyncio.TimeoutError) as e:
            raise RconError(
                f"Minecraftサーバー（{self.host}:{self.port}）に接続できません。"
                "サーバーが起動しているか、RCONが有効かを確認してください。"
            ) from e
        request_id = next(self._ids)
        await self._send(request_id, _TYPE_AUTH, self.password)
        # 認証の返事より前に、空の返事が1つ届くサーバーがあるので読み飛ばす
        while True:
            reply_id, reply_type, _ = await self._receive()
            if reply_type == 2 or reply_id == -1:
                break
        if reply_id == -1:
            await self.close()
            raise RconAuthError(
                "RCONのパスワードが違います。config.yaml の minecraft → password と、"
                "server.properties の rcon.password を同じにしてください。"
            )

    async def command(self, text: str) -> str:
        """コマンドを1つ送り、サーバーからの返事を返す。"""
        body = text.encode("utf-8")
        if len(body) > MAX_COMMAND_BYTES:
            raise ValueError(f"コマンドが長すぎます（{len(body)}バイト、上限{MAX_COMMAND_BYTES}）")
        async with self._lock:
            if not self.connected:
                await self.connect()
            request_id = next(self._ids)
            try:
                await self._send(request_id, _TYPE_COMMAND, text)
                while True:
                    reply_id, _, payload = await self._receive()
                    if reply_id == request_id:
                        return payload
            except RconError:
                await self.close()
                raise

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass

    async def _send(self, request_id: int, packet_type: int, text: str) -> None:
        assert self._writer is not None
        body = text.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<ii", request_id, packet_type) + body
        try:
            self._writer.write(struct.pack("<i", len(packet)) + packet)
            await asyncio.wait_for(self._writer.drain(), self.timeout)
        except (OSError, asyncio.TimeoutError) as e:
            raise RconError("Minecraftサーバーとの接続が切れました。") from e

    async def _receive(self) -> tuple[int, int, str]:
        assert self._reader is not None
        try:
            header = await asyncio.wait_for(self._reader.readexactly(4), self.timeout)
            (length,) = struct.unpack("<i", header)
            if not 10 <= length <= 1 << 20:
                raise RconError("Minecraftサーバーから想定外のデータが届きました。")
            data = await asyncio.wait_for(self._reader.readexactly(length), self.timeout)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
            raise RconError("Minecraftサーバーとの接続が切れました。") from e
        request_id, packet_type = struct.unpack("<ii", data[:8])
        return request_id, packet_type, data[8:-2].decode("utf-8", errors="replace")
