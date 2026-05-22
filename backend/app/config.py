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
    use_database: bool = os.getenv("LIFEROUTE_USE_DATABASE", "1") == "1"
    database_host: str = os.getenv("DATABASE_HOST", "127.0.0.1")
    database_port: int = int(os.getenv("DATABASE_PORT", "3306"))
    database_user: str = os.getenv("DATABASE_USER", "root")
    database_password: str = os.getenv("DATABASE_PASSWORD", "")
    database_name: str = os.getenv("DATABASE_NAME", "life_route_agent")
    milvus_enabled: bool = os.getenv("MILVUS_ENABLED", "1") == "1"
    milvus_host: str = os.getenv("MILVUS_HOST", "127.0.0.1")
    milvus_port: int = int(os.getenv("MILVUS_PORT", "19530"))
    milvus_collection_memory: str = os.getenv("MILVUS_COLLECTION_MEMORY", "liferoute_memory")
    milvus_collection_user_profile: str = os.getenv(
        "MILVUS_COLLECTION_USER_PROFILE", "liferoute_user_profile_vectors"
    )
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "local_bge")
    embedding_model_path: str = os.getenv("EMBEDDING_MODEL_PATH", "BAAI/bge-small-zh-v1.5")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "512"))


settings = Settings()
