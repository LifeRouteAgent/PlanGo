from __future__ import annotations

import os
import re
import tomllib
import warnings
from pathlib import Path
from typing import Any

import loguru
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONFIG_LOCAL_PATH = BACKEND_DIR / "config.local.toml"
CONFIG_EXAMPLE_PATH = BACKEND_DIR / "config.example.toml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归地深度合并两个字典：override 覆写 base，嵌套 dict 递归合并。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_env_placeholders(value: Any) -> Any:
    """递归展开 TOML 配置中的 ${ENV_NAME} 占位符。"""
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{([A-Z0-9_]+)}", value)
        if match:
            return os.environ.get(match.group(1), "")
    return value


def _load_merged_config() -> dict[str, Any]:
    """始终以 config.example.toml 为基准，再用用户配置覆写后扁平化。

    config.example.toml 是所有默认值的唯一来源（提交 Git），
    用户只需在 config.local.toml 里写需要覆写的字段。
    """

    merged: dict[str, Any] = {}

    # 1. example 为基础
    if CONFIG_EXAMPLE_PATH.exists():
        with CONFIG_EXAMPLE_PATH.open("rb") as f:
            merged = tomllib.load(f)
    else:
        loguru.logger.warning("config.example.toml not found.")

    # 2. 用户配置覆写（深度合并）
    explicit_path = os.environ.get("LIFEROUTE_CONFIG_PATH")
    override_path = Path(explicit_path) if explicit_path else CONFIG_LOCAL_PATH
    if override_path.exists():
        with override_path.open("rb") as f:
            merged = _deep_merge(merged, tomllib.load(f))

    # 3. 展开 ${ENV} 占位符
    merged = _expand_env_placeholders(merged)

    # 4. 扁平化 [section] → key
    flat: dict[str, Any] = {}
    for key, value in merged.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


class Settings(BaseSettings):
    """应用运行配置。
    todo: 后续改成分层结构, 而不是这种平铺结构
    不再支持通过环境变量读取
    config.local.toml > config.example.toml
    默认值全部由 config.example.toml 提供，Python 不维护默认值。
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # ── App ──
    app_env: str
    debug: bool

    # ── LLM ──
    llm_provider: str
    llm_model: str
    llm_timeout: int
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_reasoning_effort: str
    deepseek_thinking_enabled: bool

    # ── Route ──
    route_provider: str
    default_city: str
    default_distance_km: int
    default_budget_level: str
    amap_api_key: str
    amap_route_enabled: bool

    # ── Database ──
    database_url: str
    use_database: bool
    database_host: str
    database_port: int
    database_user: str
    database_password: str
    database_name: str

    # ── Redis / ES ──
    redis_url: str
    es_url: str

    # ── Milvus ──
    milvus_enabled: bool
    milvus_host: str
    milvus_port: int
    milvus_collection_memory: str
    milvus_collection_user_profile: str
    embedding_provider: str
    embedding_model_path: str
    embedding_dimension: int

    # ── Runtime ──
    runtime_store: str
    runtime_mysql_enabled: bool
    prompt_version_enforced: bool

    # ── Memory ──
    enable_memory: bool
    enable_verification: bool
    enable_trace: bool
    max_recent_turns: int
    max_memory_items: int

    # ── Kafka ──
    kafka_enabled: bool
    kafka_bootstrap_servers: str
    kafka_memory_topic: str


def get_settings() -> Settings:
    """加载并返回 Settings 实例。"""
    toml_data = _load_merged_config()
    kwargs: dict[str, Any] = {}

    for field_name in Settings.model_fields:
        upper_field_nameme = field_name.upper()

        # 从 TOML 查找
        value = toml_data.get(upper_field_nameme)
        if value is not None:
            kwargs[field_name] = value
        else:
            loguru.logger.warning("配置中 {} 未在提供的配置文件中出现!", field_name)

    return Settings(**kwargs)


settings = get_settings()
