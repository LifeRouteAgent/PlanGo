from __future__ import annotations

"""统一配置入口。

当前项目已有 `app.config.settings`，为了降低迁移风险，core.config 先作为兼容门面。
新代码应优先从这里导入 settings；旧模块可以逐步迁移，避免一次性改动 API/SSE。
"""

from app.config import settings

__all__ = ["settings"]
