from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/export", tags=["export"])


@router.get("/health")
def export_health() -> dict[str, str]:
    return {"status": "placeholder"}
