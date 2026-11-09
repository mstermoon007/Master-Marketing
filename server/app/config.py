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

PORT = int(_opt("PORT", "8000"))


def require_runtime_secrets() -> None:
    """启动时校验关键密钥，避免带着空 AppSecret / 空签名密钥上线。"""
    _req("WX_APPID")
    _req("WX_SECRET")
    _req("JWT_SECRET")
