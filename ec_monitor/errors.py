"""このツール内で使うエラーの種類。

エラーの種類によって「すぐ再試行する」「長めに待つ」などの対応を変えます。
"""


class MonitorError(Exception):
    """このツールのエラーの共通の親クラス。メッセージは日本語で持つ。"""


class ConfigError(MonitorError):
    """設定ファイルの内容に問題がある。"""


class ApiError(MonitorError):
    """APIの呼び出しで起きたエラーの共通の親クラス。"""


class ApiTemporaryError(ApiError):
    """通信エラーやサーバー側の一時的なエラー。時間をおけば直る可能性が高い。"""


class ApiRateLimitError(ApiTemporaryError):
    """API側のリクエスト回数の上限に達した（HTTP 429）。"""


class ApiAuthError(ApiError):
    """アプリID・アクセスキー・許可サイト・許可IPなど、認証や権限の問題。

    利用者が設定を直さない限り直らないため、短い間隔で再試行しない。
    """


class ApiRequestError(ApiError):
    """検索条件（パラメータ）の誤りなど、リクエスト内容の問題。"""


class NotifyError(MonitorError):
    """Discordへの通知に失敗した。"""
