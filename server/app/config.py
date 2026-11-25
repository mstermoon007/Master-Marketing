"""集中读取环境变量，避免在业务代码里散落 os.environ。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 允许从 server/ 目录直接启动时加载到 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _req(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必需环境变量 {name}，请参考 .env.example 配置")
    return value


def _opt(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _flag(name: str, default: str = "1") -> bool:
    return _opt(name, default).strip().lower() not in ("0", "false", "no", "off")


DB_HOST = _opt("DB_HOST", "127.0.0.1")
DB_PORT = int(_opt("DB_PORT", "3306"))
DB_USER = _opt("DB_USER", "root")
DB_PASSWORD = _opt("DB_PASSWORD", "")
DB_NAME = _opt("DB_NAME", "jinribao")

WX_APPID = _opt("WX_APPID", "")
WX_SECRET = _opt("WX_SECRET", "")
WX_HTTP_TIMEOUT = int(_opt("WX_HTTP_TIMEOUT", "5"))

JWT_SECRET = _opt("JWT_SECRET", "")
JWT_TTL_DAYS = int(_opt("JWT_TTL_DAYS", "30"))

# Web 管理后台：与 API 同域 + 独立有效期的 aud=web 令牌
WEB_ORIGIN = _opt("WEB_ORIGIN", "https://api.modouyu.top")
WEB_TOKEN_TTL_HOURS = int(_opt("WEB_TOKEN_TTL_HOURS", "12"))

# ---- 消息通知（P6）----
# 四类微信订阅消息模板 ID：留空时只写通知记录（status=skipped），不调用微信。
# 模板字段约定见 .env.example（thing1 / thing2 / date3 / number4）。
WX_TMPL_DAILY_REMIND = _opt("WX_TMPL_DAILY_REMIND", "")
WX_TMPL_DUE_REMIND = _opt("WX_TMPL_DUE_REMIND", "")
WX_TMPL_MISSING_REMIND = _opt("WX_TMPL_MISSING_REMIND", "")
WX_TMPL_ANOMALY_ALERT = _opt("WX_TMPL_ANOMALY_ALERT", "")

# 应用内调度（APScheduler）：多 worker 同时运行时靠通知去重唯一键兜底。
SCHEDULER_ENABLED = _flag("SCHEDULER_ENABLED", "1")
SCHEDULER_TZ = _opt("SCHEDULER_TZ", "Asia/Shanghai")
DAILY_REMIND_TIME = _opt("DAILY_REMIND_TIME", "09:00")
MISSING_REMIND_TIME = _opt("MISSING_REMIND_TIME", "20:00")
REMIND_BEFORE_MINUTES = int(_opt("REMIND_BEFORE_MINUTES", "30"))

PORT = int(_opt("PORT", "8000"))


def require_runtime_secrets() -> None:
    """启动时校验关键密钥，避免带着空 AppSecret / 空签名密钥上线。"""
    _req("WX_APPID")
    _req("WX_SECRET")
    secret = _req("JWT_SECRET")
    if len(secret) < 32:
        raise RuntimeError(
            "JWT_SECRET 至少 32 个字符（HS256 建议 256 位随机值）；"
            "生成命令：python3 -c \"import secrets;print(secrets.token_urlsafe(48))\""
        )
