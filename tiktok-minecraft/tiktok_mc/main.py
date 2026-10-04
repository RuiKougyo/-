"""ツール全体の起動と、動かし方（本番・テスト・接続チェック）の切り替え。

  TikTokMinecraft.exe            … 本番。配信を待って自動でつなぎ、ギフトでギミックを動かす
  TikTokMinecraft.exe --test     … テスト。キーボードで「ギフトが来たふり」をして動作確認する
  TikTokMinecraft.exe --check    … Minecraftサーバーにつながるかだけ確認する
  --dry-run を付けると、Minecraftに送らず画面に表示するだけになります
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from . import __version__
from . import events as ev
from .config import Config, ConfigError, Rule, load_config
from .events import LiveEvent
from .executor import CommandQueue, CommandSender, DryRunSender
from .log_setup import get_logger, setup_logging
from .paths import base_dir, bundled_file
from .rcon import RconClient, RconError
from .rules import RuleEngine

log = get_logger()

TEST_HELP = """\
──────── テストモードの使い方 ────────
  gift バラの名前 [個数] [コイン]   例: gift Rose 5
  follow                            フォローされたふり
  share                             シェアされたふり
  like [数]                         いいね（例: like 100）
  comment 文字                      コメント（例: comment ジャンプ）
  join                              だれかが入室したふり
  sub                               サブスク登録されたふり
  help                              この説明をもう一度表示
  quit                              終了
──────────────────────────────────"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TikTokライブのギフトでMinecraftのギミックを動かすツール")
    parser.add_argument("--config", type=Path, default=base_dir() / "config.yaml", help="設定ファイルの場所")
    parser.add_argument("--test", action="store_true", help="キーボード入力でギフトが来たふりをして試す")
    parser.add_argument("--check", action="store_true", help="Minecraftサーバーへの接続だけ確認する")
    parser.add_argument("--dry-run", action="store_true", help="Minecraftに送らず、画面に表示するだけにする")
    args = parser.parse_args(argv)

    setup_logging(base_dir() / "logs")
    if not args.config.exists():
        return _create_sample_config(args.config)
    try:
        config = load_config(args.config)
    except ConfigError as e:
        log.error("設定ファイルに問題があります: %s", e)
        _pause()
        return 1
    setup_logging(base_dir() / "logs", config.log_level)
    log.info("TikTok × Minecraft ギミック連動ツール v%s を起動しました。", __version__)

    try:
        if args.check:
            ok = asyncio.run(_check_minecraft(config))
            _pause()
            return 0 if ok else 1
        asyncio.run(_run(config, test_mode=args.test, dry_run=args.dry_run))
    except KeyboardInterrupt:
        pass
    log.info("終了しました。")
    return 0


async def _run(config: Config, test_mode: bool, dry_run: bool) -> None:
    sender: CommandSender
    if dry_run:
        sender = DryRunSender()
        log.info("「送信のふり」モードです。Minecraftにはコマンドを送りません。")
    else:
        rcon = RconClient(config.minecraft.host, config.minecraft.port, config.minecraft.password)
        try:
            await rcon.connect()
            log.info("Minecraftサーバー（%s:%d）に接続しました。", config.minecraft.host, config.minecraft.port)
        except RconError as e:
            log.warning("%s つながるまで自動で再試行します。", e)
        sender = rcon

    queue = CommandQueue(
        sender,
        commands_per_second=config.minecraft.commands_per_second,
        max_queue=config.minecraft.max_queue,
    )
    engine = RuleEngine(config)

    def on_event(event: LiveEvent) -> None:
        if event.kind == ev.GIFT:
            log.info("🎁 %s さんから「%s」×%d", event.display_name, event.gift_name, event.count)
        jobs = engine.handle(event)
        if jobs and event.kind in _KIND_JA:
            log.info("%s：%s さん", _KIND_JA.get(event.kind, event.kind), event.display_name)
        for label, commands in jobs:
            if event.kind == ev.LIKE:
                log.info("👍 いいねが合計 %d になりました →「%s」", engine.like_total, label)
            queue.submit(label, commands)

    tasks = [asyncio.create_task(queue.run(), name="queue")]
    try:
        if test_mode:
            tasks.append(asyncio.create_task(_run_timers(config, engine, queue, lambda: True)))
            await _test_console(on_event, engine)
            # 入力を終えたあとも、並んでいるコマンドは送り切る
            while queue.pending:
                await asyncio.sleep(0.2)
        else:
            from .tiktok_source import TikTokSource

            source = TikTokSource(
                config.tiktok,
                on_event,
                gift_mode=config.gift_mode,
                on_live_start=engine.reset_session,
            )
            tasks.append(asyncio.create_task(_run_timers(config, engine, queue, lambda: source.is_connected)))
            log.info("Ctrl + C で終了できます。")
            await source.run_forever()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sender.close()


_KIND_JA = {
    ev.FOLLOW: "➕ フォロー",
    ev.SHARE: "🔁 シェア",
    ev.COMMENT: "💬 コメント",
    ev.JOIN: "👋 入室",
    ev.SUBSCRIBE: "⭐ サブスク",
}


async def _run_timers(config: Config, engine: RuleEngine, queue: CommandQueue, is_live) -> None:
    """timers の設定に従って、一定時間ごとにコマンドを実行する（配信中だけ）。"""
    if not config.timers:
        return

    async def one(rule: Rule) -> None:
        while True:
            await asyncio.sleep(rule.every_minutes * 60)
            if rule.enabled and is_live():
                label, commands = engine.timer_job(rule)
                log.info("⏰ 定期イベント「%s」を実行します。", label)
                queue.submit(label, commands)

    await asyncio.gather(*(one(r) for r in config.timers))


async def _test_console(on_event, engine: RuleEngine) -> None:
    print(TEST_HELP)
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "> ")
        except EOFError:
            return
        event = parse_test_command(line)
        if event == "quit":
            return
        if event == "help" or event is None:
            if event is None and line.strip():
                print("入力の形が分かりませんでした。")
            print(TEST_HELP)
            continue
        on_event(event)


def parse_test_command(line: str) -> LiveEvent | str | None:
    """テストモードで入力された1行を、出来事に変換する。"""
    parts = line.strip().split()
    if not parts:
        return None
    word = parts[0].lower()
    tester = dict(user_id="test-user", username="test_viewer", nickname="テスト視聴者")
    if word in ("quit", "exit", "q"):
        return "quit"
    if word in ("help", "h", "?"):
        return "help"
    if word == "gift" and len(parts) >= 2:
        # ギフト名に空白が入っていても良いように、末尾の数字だけを個数・コインとして扱う
        rest = parts[1:]
        numbers: list[int] = []
        while len(rest) > 1 and rest[-1].isdigit() and len(numbers) < 2:
            numbers.insert(0, int(rest.pop()))
        count = numbers[0] if numbers else 1
        coins = numbers[1] if len(numbers) > 1 else 1
        return LiveEvent(kind=ev.GIFT, gift_name=" ".join(rest), count=count, coins=coins, **tester)
    if word == "like":
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        return LiveEvent(kind=ev.LIKE, count=count, **tester)
    if word == "comment" and len(parts) >= 2:
        return LiveEvent(kind=ev.COMMENT, comment=" ".join(parts[1:]), **tester)
    simple = {"follow": ev.FOLLOW, "share": ev.SHARE, "join": ev.JOIN, "sub": ev.SUBSCRIBE}
    if word in simple:
        return LiveEvent(kind=simple[word], **tester)
    return None


async def _check_minecraft(config: Config) -> bool:
    rcon = RconClient(config.minecraft.host, config.minecraft.port, config.minecraft.password)
    try:
        await rcon.connect()
        reply = await rcon.command("list")
        await rcon.command('tellraw @a {"text":"[TikTok連動] 接続テストOK！","color":"green"}')
    except RconError as e:
        log.error("接続できませんでした: %s", e)
        return False
    finally:
        await rcon.close()
    log.info("Minecraftサーバーに接続できました！ サーバーの返事: %s", reply.strip())
    if config.minecraft.player and config.minecraft.player not in reply:
        log.warning(
            "設定のプレイヤー名「%s」が、今サーバーにいるプレイヤーの中に見つかりません。"
            "名前のつづり（大文字・小文字）を確認してください。",
            config.minecraft.player,
        )
    return True


def _create_sample_config(path: Path) -> int:
    sample = bundled_file("config.sample.yaml")
    try:
        shutil.copyfile(sample, path)
    except OSError as e:
        log.error("設定ファイルのひな形を作れませんでした: %s", e)
        _pause()
        return 1
    log.info(
        "設定ファイル（%s）を作りました。メモ帳で開いて、TikTokのIDとRCONのパスワードを書いてから、もう一度起動してください。",
        path,
    )
    _pause()
    return 1


def _pause() -> None:
    """exeをダブルクリックで起動したとき、メッセージを読む前に画面が閉じないようにする。"""
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("Enterキーを押すと閉じます…")
        except EOFError:
            pass
