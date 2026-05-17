from __future__ import annotations

import pytest

from app.config import settings
from app.services.poi_repository import PoiRepository
from app.tools.poi_schema import POI_RESTAURANT


@pytest.mark.skipif(not settings.use_database, reason="local database is not enabled")
def test_poi_repository_reads_mysql_restaurants() -> None:
    """本地数据库启用时，Collector 仓储应能把 MySQL 餐厅表映射为统一 POI。"""

    result = PoiRepository(limit_per_category=3).fetch_by_categories([POI_RESTAURANT])

    assert result[POI_RESTAURANT]
    first = result[POI_RESTAURANT][0]
    assert first["id"]
    assert first["name"]
    assert first["category"] == POI_RESTAURANT
    assert isinstance(first["lat"], float)
    assert isinstance(first["lon"], float)
