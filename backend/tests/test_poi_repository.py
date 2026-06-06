from __future__ import annotations

import pytest

from app.config import settings
from app.repositories.poi_repository import PoiRepository
from app.repositories.constants import POI_RESTAURANT


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


@pytest.mark.skipif(not settings.use_database, reason="local database is not enabled")
def test_trip_data_source_api_reports_mysql_counts() -> None:
    """数据源状态接口应返回 MySQL 表行数，便于前端和 review 判断是否走真实库。"""

    from fastapi.testclient import TestClient

    from app.api.main import app

    response = TestClient(app).get("/trip/data-source")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "mysql"
    assert body["enabled"] is True
    assert body["database_name"] == settings.database_name
    assert body["table_counts"][POI_RESTAURANT] > 0
