from __future__ import annotations

# todo: 这个东西也不该放在 services 里面吧
from app.config import BACKEND_DIR

RUNTIME_DIR = BACKEND_DIR / "data" / "runtime"
SESSIONS_DIR = RUNTIME_DIR / "sessions"
TRACES_DIR = RUNTIME_DIR / "traces"
MEMORY_DIR = RUNTIME_DIR / "memory"
CALENDAR_DIR = RUNTIME_DIR / "calendar"
TASKS_DIR = RUNTIME_DIR / "tasks"
TOOL_CACHE_DIR = RUNTIME_DIR / "tool_cache"


def ensure_runtime_dirs() -> None:
    """创建本地运行态目录。

    这些目录只保存 demo 运行时状态，不属于源码资产；后续如果切换 MySQL/Redis，
    可以保持上层接口不变，只替换服务实现。
    """

    for path in (SESSIONS_DIR, TRACES_DIR, MEMORY_DIR, CALENDAR_DIR, TASKS_DIR, TOOL_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
