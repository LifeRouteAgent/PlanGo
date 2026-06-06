from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONFIG_LOCAL_PATH = BACKEND_DIR / "config.local.json"
CONFIG_EXAMPLE_PATH = BACKEND_DIR / "config.example.json"


def _load_config() -> dict[str, Any]:
    """从文件读取运行配置。

    读取优先级：
    1. LIFEROUTE_CONFIG_PATH：容器或部署环境显式指定的配置文件。
    2. backend/config.local.json：本机真实配置，包含 key 和数据库密码，不提交 Git。
    3. backend/config.example.json：仓库内示例配置，只放非敏感默认值和空占位。

    业务代码统一从 settings 读取配置，不再直接依赖系统环境变量。
    """

    explicit_path = os.environ.get("LIFEROUTE_CONFIG_PATH")
    candidates = [Path(explicit_path)] if explicit_path else []
    candidates.extend([CONFIG_LOCAL_PATH, CONFIG_EXAMPLE_PATH])
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return _expand_env_placeholders(data)
    return {}


def _expand_env_placeholders(value: Any) -> Any:
    """展开配置文件中的 `${ENV_NAME}` 占位符。

    这样 Docker 配置仍由文件声明字段结构，但敏感值由运行环境注入，不需要提交真实 key。
    """

    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", value)
        if match:
            return os.environ.get(match.group(1), "")
    return value


def _get(config: dict[str, Any], key: str, default: Any) -> Any:
    """读取单个配置项，并把空字符串视为未配置。"""

    value = os.environ.get(key, config.get(key, default))
    return default if value == "" or value is None else value


def _get_alias(config: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
    """按顺序读取多个兼容配置名，便于从 MiMo 平滑迁移到 DeepSeek。"""

    for key in keys:
        value = os.environ.get(key, config.get(key))
        if value != "" and value is not None:
            return value
    return default


def _get_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    """读取 bool 配置，兼容 JSON bool 和字符串形式。"""

    value = os.environ.get(key, config.get(key, default))
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_int(config: dict[str, Any], key: str, default: int) -> int:
    """读取 int 配置，配置异常时回退默认值。"""

    try:
        return int(os.environ.get(key, config.get(key, default)))
    except (TypeError, ValueError):
        return default


_CONFIG = _load_config()


@dataclass(frozen=True)
class Settings:
    app_env: str = _get(_CONFIG, "APP_ENV", "local")
    debug: bool = _get_bool(_CONFIG, "DEBUG", False)
    database_url: str = _get(_CONFIG, "DATABASE_URL", "")
    redis_url: str = _get(_CONFIG, "REDIS_URL", "")
    es_url: str = _get(_CONFIG, "ES_URL", "")
    llm_provider: str = _get(_CONFIG, "LLM_PROVIDER", "deepseek")
    llm_model: str = _get_alias(_CONFIG, ("LLM_MODEL", "DEEPSEEK_MODEL", "MIMO_MODEL"), "deepseek-v4-pro")
    llm_timeout: int = _get_int(_CONFIG, "LLM_TIMEOUT", 60)
    max_recent_turns: int = _get_int(_CONFIG, "MAX_RECENT_TURNS", 8)
    max_memory_items: int = _get_int(_CONFIG, "MAX_MEMORY_ITEMS", 20)
    default_city: str = _get(_CONFIG, "DEFAULT_CITY", "北京")
    default_distance_km: int = _get_int(_CONFIG, "DEFAULT_DISTANCE_KM", 8)
    default_budget_level: str = _get(_CONFIG, "DEFAULT_BUDGET_LEVEL", "medium")
    route_provider: str = _get(_CONFIG, "ROUTE_PROVIDER", "amap")
    enable_memory: bool = _get_bool(_CONFIG, "ENABLE_MEMORY", True)
    enable_verification: bool = _get_bool(_CONFIG, "ENABLE_VERIFICATION", True)
    enable_trace: bool = _get_bool(_CONFIG, "ENABLE_TRACE", True)
    deepseek_api_key: str = _get(_CONFIG, "DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = _get(_CONFIG, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = _get(_CONFIG, "DEEPSEEK_MODEL", "deepseek-v4-pro")
    deepseek_reasoning_effort: str = _get(_CONFIG, "DEEPSEEK_REASONING_EFFORT", "high")
    deepseek_thinking_enabled: bool = _get_bool(_CONFIG, "DEEPSEEK_THINKING_ENABLED", True)
    # 兼容历史字段：旧代码和旧本地配置仍可读取 mimo_*，但默认值已经切换到 DeepSeek。
    mimo_api_key: str = _get_alias(_CONFIG, ("MIMO_API_KEY", "DEEPSEEK_API_KEY"), "")
    mimo_base_url: str = _get_alias(
        _CONFIG, ("MIMO_BASE_URL", "DEEPSEEK_BASE_URL"), "https://api.deepseek.com"
    )
    mimo_model: str = _get_alias(_CONFIG, ("MIMO_MODEL", "DEEPSEEK_MODEL"), "deepseek-v4-pro")
    amap_api_key: str = _get(_CONFIG, "AMAP_API_KEY", "")
    amap_route_enabled: bool = _get_bool(_CONFIG, "AMAP_ROUTE_ENABLED", False)
    use_database: bool = _get_bool(_CONFIG, "LIFEROUTE_USE_DATABASE", True)
    database_host: str = _get(_CONFIG, "DATABASE_HOST", "127.0.0.1")
    database_port: int = _get_int(_CONFIG, "DATABASE_PORT", 3306)
    database_user: str = _get(_CONFIG, "DATABASE_USER", "root")
    database_password: str = _get(_CONFIG, "DATABASE_PASSWORD", "")
    database_name: str = _get(_CONFIG, "DATABASE_NAME", "life_route_agent")
    milvus_enabled: bool = _get_bool(_CONFIG, "MILVUS_ENABLED", True)
    milvus_host: str = _get(_CONFIG, "MILVUS_HOST", "127.0.0.1")
    milvus_port: int = _get_int(_CONFIG, "MILVUS_PORT", 19530)
    milvus_collection_memory: str = _get(_CONFIG, "MILVUS_COLLECTION_MEMORY", "liferoute_memory")
    milvus_collection_user_profile: str = _get(
        _CONFIG, "MILVUS_COLLECTION_USER_PROFILE", "liferoute_user_profile_vectors"
    )
    embedding_provider: str = _get(_CONFIG, "EMBEDDING_PROVIDER", "local_bge")
    embedding_model_path: str = _get(_CONFIG, "EMBEDDING_MODEL_PATH", "BAAI/bge-small-zh-v1.5")
    embedding_dimension: int = _get_int(_CONFIG, "EMBEDDING_DIMENSION", 512)
    runtime_store: str = _get(_CONFIG, "RUNTIME_STORE", "mysql")
    runtime_mysql_enabled: bool = _get_bool(_CONFIG, "RUNTIME_MYSQL_ENABLED", True)
    prompt_version_enforced: bool = _get_bool(_CONFIG, "PROMPT_VERSION_ENFORCED", True)
    kafka_enabled: bool = _get_bool(_CONFIG, "KAFKA_ENABLED", False)
    kafka_bootstrap_servers: str = _get(_CONFIG, "KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    kafka_memory_topic: str = _get(_CONFIG, "KAFKA_MEMORY_TOPIC", "liferoute.memory.events")


settings = Settings()

