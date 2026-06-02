from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.models.schemas import ExportPlanRequest
from app.services.memory_service import MemoryService
from app.services.product_pdf_service import build_product_plan_pdf
from app.services.tool_harness import ToolHarness
from app.services.trace_recorder import record_trace_event, set_trace_context

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/health")
def export_health() -> dict[str, str]:
    return {"status": "ok"}


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
        MemoryService().observe_selected_plan(request.plan, user_id=request.session_id)

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
    if not isinstance(pdf_bytes, bytes):
        pdf_bytes = build_product_plan_pdf(request.plan)

    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="plango-plan.pdf"',
        },
    )
