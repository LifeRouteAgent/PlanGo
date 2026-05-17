from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# 优先加载 backend/.env。真实密码只放在 .env，.env.example 只保留字段说明。
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    mimo_api_key: str = os.getenv("MIMO_API_KEY") or os.getenv("travelAgent", "")
    mimo_base_url: str = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    mimo_model: str = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    amap_api_key: str = os.getenv("AMAP_API_KEY", "")
    use_database: bool = os.getenv("LIFEROUTE_USE_DATABASE", "0") == "1"
    database_host: str = os.getenv("DATABASE_HOST", "127.0.0.1")
    database_port: int = int(os.getenv("DATABASE_PORT", "3306"))
    database_user: str = os.getenv("DATABASE_USER", "root")
    database_password: str = os.getenv("DATABASE_PASSWORD", "")
    database_name: str = os.getenv("DATABASE_NAME", "life_route_agent")


settings = Settings()
