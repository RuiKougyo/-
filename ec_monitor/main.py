"""起動処理。

使い方：
  ECMonitor.exe            … 監視を開始（止めるまで動き続ける）
  ECMonitor.exe --test     … 設定の確認（Discordにテスト通知を送り、APIに1回だけ問い合わせる）
  ECMonitor.exe --once     … すべての監視条件を1回だけチェックして終了
  ECMonitor.exe --config 別の設定.yaml … 設定ファイルを指定して起動
"""

import argparse
import shutil
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config_loader import AppConfig, load_config
from .errors import ApiError, ConfigError, NotifyError
from .filters import filter_items
from .log_setup import setup_logging
from .monitor import Monitor, build_clients, describe_watch
from .notifier import DiscordNotifier, yen
from .paths import base_dir, bundled_file
from .storage import Storage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{__version__}")
    parser.add_argument("--config", help="設定ファイルの場所（省略時は exe と同じフォルダの config.yaml）")
    parser.add_argument("--test", action="store_true", help="設定の確認だけを行う")
    parser.add_argument("--once", action="store_true", help="1回だけチェックして終了する")
    args = parser.parse_args(argv)

    root = base_dir()
    log = setup_logging(root / "logs")
    log.info(f"{APP_NAME} v{__version__} を起動しました")

    config_path = Path(args.config) if args.config else root / "config.yaml"
    if not config_path.exists():
        _create_config_from_sample(config_path, log)
        return _finish(1)

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        log.error(str(exc))
        log.error(f"設定ファイル（{config_path}）を修正してから、もう一度起動してください。")
        return _finish(1)

    log = setup_logging(root / "logs", config.settings.log_level)
    clients = build_clients(config)
    notifier = DiscordNotifier(config.discord.webhook_url)

    for watch in config.watches:
        log.info(f"監視条件「{watch.name}」：{describe_watch(watch)}")

    if args.test:
        return _finish(run_test(config, clients, notifier, log))

    storage = Storage(root / "data" / "state.db")
    monitor = Monitor(config, clients, storage, notifier)
    try:
        if args.once:
            monitor.run_once()
            log.info("1回分のチェックが終わりました")
        else:
            monitor.run_forever()
    except KeyboardInterrupt:
        log.info("監視を停止しました")
    finally:
        storage.close()
    return 0


def run_test(config: AppConfig, clients, notifier: DiscordNotifier, log) -> int:
    """設定の確認：Discordにテスト通知を送り、各サイトのAPIに1回だけ問い合わせる。"""
    ok = True
    credits = " / ".join(c.credit_text for c in clients.values())
    try:
        notifier.send_text(
            "✅ テスト通知",
            "EC新着・値下げ監視ツールからのテスト通知です。\nこのメッセージが見えていれば、Discordの設定は完了しています。",
            footer=credits,
        )
        log.info("Discordにテスト通知を送りました。Discordを開いて届いているか確認してください。")
    except NotifyError as exc:
        log.error(f"Discordへのテスト通知に失敗しました：{exc}")
        ok = False

    for site, client in clients.items():
        watch = next(w for w in config.watches if site in w.sites)
        watch_1page = type(watch)(**{**watch.__dict__, "max_pages": 1})
        try:
            items = client.search(watch_1page)
        except ApiError as exc:
            log.error(f"{client.display_name}のAPIの確認に失敗しました：{exc}")
            ok = False
            continue
        matched = filter_items(items, watch)
        log.info(
            f"{client.display_name}のAPIに接続できました。"
            f"「{watch.name}」で {len(items)}件取得、うち条件に合う商品 {len(matched)}件"
        )
        for item in matched[:3]:
            log.info(f"    例：{item.name[:40]}　{yen(item.price)}")

    if ok:
        log.info("設定の確認が完了しました。問題はありません。--test を付けずに起動すると監視を開始します。")
    else:
        log.error("設定の確認で問題が見つかりました。上のメッセージを参考に config.yaml を見直してください。")
    return 0 if ok else 1


def _create_config_from_sample(config_path: Path, log) -> None:
    """設定ファイルがないときは、サンプルをコピーして作る。"""
    sample = bundled_file("config.sample.yaml")
    if sample.exists():
        shutil.copyfile(sample, config_path)
        log.warning(
            f"設定ファイルが見つからなかったため、ひな形を作成しました：{config_path}\n"
            "    メモ帳などで開いて、APIキーやDiscordのURL、監視条件を入力してから、もう一度起動してください。"
        )
    else:
        log.error(f"設定ファイルが見つかりません：{config_path}")


def _finish(code: int) -> int:
    """ダブルクリックで起動した場合に、画面がすぐ閉じてメッセージが読めなくならないようにする。"""
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nEnterキーを押すと画面を閉じます…")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
