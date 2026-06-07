from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.schemas.trip import ExportPlanRequest
from app.memory.memory_event_queue import MemoryEventQueue
from app.export.product_pdf_service import build_product_plan_pdf
from app.tools.tool_harness import ToolHarness
from app.observability.trace_recorder import record_trace_event, set_trace_context

router = APIRouter(prefix="/export", tags=["export"])
_PDF_CACHE: dict[str, dict[str, object]] = {}
_PDF_CACHE_TTL_SECONDS = 30 * 60
_PDF_CACHE_MAX_ITEMS = 64


@router.get("/health")
def export_health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/plan/pdf/prepare")
def prepare_plan_pdf(request: ExportPlanRequest) -> dict[str, str | bool]:
    token = _pdf_cache_token(request)
    cached = _PDF_CACHE.get(token)
    if cached and _cache_fresh(cached):
        return {"ok": True, "token": token, "ready": True, "cached": True}

    _cleanup_pdf_cache()
    pdf_bytes = _build_pdf_bytes(request)
    _PDF_CACHE[token] = {
        "bytes": pdf_bytes,
        "created_at": time.time(),
        "filename": _pdf_filename(request.plan),
    }
    return {"ok": True, "token": token, "ready": True, "cached": False}


@router.get("/plan/pdf/{token}")
def download_prepared_plan_pdf(token: str) -> Response:
    cached = _PDF_CACHE.get(token)
    if not cached or not _cache_fresh(cached):
        return Response(
            content=b"",
            status_code=404,
            media_type="application/json",
        )
    return Response(
        cached["bytes"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(str(cached.get("filename") or "plango-plan.pdf")),
        },
    )


@router.post("/plan/pdf")
def export_plan_pdf(request: ExportPlanRequest) -> Response:
    """导出 PlanGo 产品化中文 PDF。

    PDF 直接基于结构化方案绘制两页式内容，包含方案指标、头图、亮点标签、
    行程时间轴、路线概览、优缺点分析和出行清单，面向分享与答辩展示。
    """

    if request.trace_id or request.session_id:
        set_trace_context(
            trace_id=request.trace_id,
            run_id="export_pdf",
            session_id=request.session_id or "export_session",
        )
    record_trace_event(
        "user_action",
        {
            "action": "plan_exported_pdf",
            "plan_id": request.plan.get("id"),
        },
    )
    if request.session_id:
        MemoryEventQueue().publish_plan_feedback(
            request.plan,
            user_id=request.session_id,
            stage="plan_exported_pdf",
            feedback={"source": "export_pdf_button"},
            trace_id=request.trace_id or "",
            run_id="export_pdf",
            session_id=request.session_id,
        )

    token = _pdf_cache_token(request)
    cached = _PDF_CACHE.get(token)
    if cached and _cache_fresh(cached):
        pdf_bytes = cached["bytes"]
    else:
        pdf_bytes = _build_pdf_bytes(request)
        _PDF_CACHE[token] = {
            "bytes": pdf_bytes,
            "created_at": time.time(),
            "filename": _pdf_filename(request.plan),
        }

    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(_pdf_filename(request.plan)),
        },
    )


def _build_pdf_bytes(request: ExportPlanRequest) -> bytes:
    harness = ToolHarness(name="pdf.export.plan", timeout_seconds=8, max_retries=1)
    result = harness.run_request(
        {
            "tool_name": "pdf.export.plan",
            "risk_level": 2,
            "session_id": request.session_id or "export_session",
            "params": {
                "plan_id": request.plan.get("id"),
                "confirmed": True,
                "confirmed_source": "export_pdf_button",
            },
            "confirmed_source": "export_pdf_button",
        },
        lambda: build_product_plan_pdf(request.plan),
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    pdf_bytes = data.get("value") if isinstance(data, dict) else None
    return pdf_bytes if isinstance(pdf_bytes, bytes) else build_product_plan_pdf(request.plan)


def _pdf_cache_token(request: ExportPlanRequest) -> str:
    payload = {
        "plan_id": request.plan.get("id") or request.plan.get("plan_id"),
        "session_id": request.session_id or "",
        "trace_id": request.trace_id or "",
        "plan": request.plan,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _cache_fresh(cached: dict[str, object]) -> bool:
    created_at = float(cached.get("created_at") or 0)
    return bool(cached.get("bytes")) and time.time() - created_at <= _PDF_CACHE_TTL_SECONDS


def _cleanup_pdf_cache() -> None:
    expired = [token for token, value in _PDF_CACHE.items() if not _cache_fresh(value)]
    for token in expired:
        _PDF_CACHE.pop(token, None)
    if len(_PDF_CACHE) <= _PDF_CACHE_MAX_ITEMS:
        return
    oldest = sorted(_PDF_CACHE.items(), key=lambda item: float(item[1].get("created_at") or 0))
    for token, _value in oldest[: max(0, len(_PDF_CACHE) - _PDF_CACHE_MAX_ITEMS)]:
        _PDF_CACHE.pop(token, None)


def _pdf_filename(plan: dict[str, object]) -> str:
    title = ""
    recommendation = plan.get("recommendation")
    if isinstance(recommendation, dict):
        title = str(recommendation.get("title") or "")
    title = title or str(plan.get("title") or "plango-plan")
    safe = "".join(ch for ch in title if ch.isalnum() or ch in {"-", "_"})
    return f"{safe[:40] or 'plango-plan'}.pdf"


def _content_disposition(filename: str) -> str:
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"plango-plan.pdf\"; filename*=UTF-8''{encoded}"
