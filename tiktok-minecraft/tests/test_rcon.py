import asyncio
import struct

import pytest

from tiktok_mc.rcon import RconAuthError, RconClient, RconError


class FakeMinecraft:
    """RCONの通信手順だけを真似する、テスト用のMinecraftサーバー。"""

    def __init__(self, password="pw", empty_before_auth=False):
        self.password = password
        self.empty_before_auth = empty_before_auth
        self.received: list[str] = []
        self.server = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    @staticmethod
    def _packet(request_id, packet_type, body):
        data = struct.pack("<ii", request_id, packet_type) + body.encode() + b"\x00\x00"
        return struct.pack("<i", len(data)) + data

    async def _handle(self, reader, writer):
        try:
            while True:
                (length,) = struct.unpack("<i", await reader.readexactly(4))
                data = await reader.readexactly(length)
                request_id, packet_type = struct.unpack("<ii", data[:8])
                body = data[8:-2].decode()
                if packet_type == 3:
                    if self.empty_before_auth:
                        writer.write(self._packet(request_id, 0, ""))
                    ok = body == self.password
                    writer.write(self._packet(request_id if ok else -1, 2, ""))
                else:
                    self.received.append(body)
                    writer.write(self._packet(request_id, 0, f"ok:{body}"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()


@pytest.mark.parametrize("empty_before_auth", [False, True])
def test_command_roundtrip(empty_before_auth):
    async def scenario():
        mc = FakeMinecraft(empty_before_auth=empty_before_auth)
        port = await mc.start()
        client = RconClient("127.0.0.1", port, "pw")
        reply = await client.command("say こんにちは")
        await client.close()
        await mc.stop()
        return reply, mc.received

    reply, received = asyncio.run(scenario())
    assert reply == "ok:say こんにちは"
    assert received == ["say こんにちは"]


def test_wrong_password():
    async def scenario():
        mc = FakeMinecraft(password="right")
        port = await mc.start()
        try:
            await RconClient("127.0.0.1", port, "wrong").connect()
        finally:
            await mc.stop()

    with pytest.raises(RconAuthError):
        asyncio.run(scenario())


def test_server_down():
    async def scenario():
        mc = FakeMinecraft()
        port = await mc.start()
        await mc.stop()
        await RconClient("127.0.0.1", port, "pw", timeout=1).connect()

    with pytest.raises(RconError):
        asyncio.run(scenario())


def test_too_long_command():
    with pytest.raises(ValueError):
        asyncio.run(RconClient("127.0.0.1", 1, "pw").command("x" * 2000))
