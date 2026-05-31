from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.models.schemas import ExportPlanRequest
from app.services.markdown_pdf_service import build_markdown_pdf
from app.services.memory_service import MemoryService
from app.services.tool_harness import ToolHarness
from app.services.trace_recorder import record_trace_event, set_trace_context

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/health")
def export_health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/plan/pdf")
def export_plan_pdf(request: ExportPlanRequest) -> Response:
    """导出中文 Markdown 排版 PDF。

    导出内容先从结构化方案生成 Markdown，再由 ReportLab 渲染为正式 PDF。
    PDF 使用中文字体、方案概览表、分节标题、时间线、地点详情和路线信息，
    面向产品演示与实际分享，而不是最小 PDF 占位。
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
    harness = ToolHarness(name="pdf.export.plan", timeout_seconds=3, max_retries=1)
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
        lambda: build_markdown_pdf(request.plan),
    )
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    pdf_bytes = data.get("value") if isinstance(data, dict) else None
    if not isinstance(pdf_bytes, bytes):
        pdf_bytes = build_markdown_pdf(request.plan)
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="liferoute-plan.pdf"',
        },
    )
