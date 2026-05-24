from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from app.models.schemas import ExportPlanRequest
from app.services.memory_service import MemoryService
from app.services.trace_recorder import record_trace_event, set_trace_context

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/health")
def export_health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/plan/pdf")
def export_plan_pdf(request: ExportPlanRequest) -> Response:
    """导出一个真正有页面内容的轻量 PDF。

    当前不引入额外 PDF 渲染依赖，直接生成最小 PDF 对象树和文本页。PDF 内置字体对中文
    支持有限，所以正文会把非 ASCII 字符转成 `\\uXXXX` 形式，至少保证打开不是空白，
    且能看到方案标题、时间、预算、地点和优缺点。后续接 Playwright/ReportLab 后可升级
    为完整中文排版。
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
    pdf_bytes = _build_minimal_pdf(_plan_to_pdf_lines(request.plan))
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="liferoute-plan.pdf"',
        },
    )


def _plan_to_pdf_lines(plan: dict[str, Any]) -> list[str]:
    """把方案结构转成 PDF 页面上的文本行。"""

    lines = [
        "LifeRouteAgent Weekend Plan",
        f"Title: {_ascii_pdf_text(plan.get('title', 'Untitled Plan'))}",
        f"Score: {plan.get('plan_score', 'N/A')}",
        f"Duration: {plan.get('total_duration_minutes', 'N/A')} minutes",
        (
            f"Route: {plan.get('route_minutes', 'N/A')} minutes /"
            f" {plan.get('total_distance_km', 'N/A')} km"
        ),
        f"Budget: {plan.get('estimated_budget', 'N/A')}",
        "",
        "Reason:",
        _ascii_pdf_text(plan.get("recommendation_reason", "N/A")),
        "",
        "Pros:",
    ]
    lines.extend(f"- {_ascii_pdf_text(item)}" for item in plan.get("pros", [])[:3])
    lines.append("")
    lines.append("Cons:")
    lines.extend(f"- {_ascii_pdf_text(item)}" for item in plan.get("cons", [])[:3])
    lines.append("")
    lines.append("Stops:")
    for index, item in enumerate(plan.get("items", [])[:8], start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"{index}. {_ascii_pdf_text(item.get('name', 'Unknown'))} | "
            f"rating={item.get('rating', 'N/A')} | {_ascii_pdf_text(item.get('address', ''))}"
        )
        reason = item.get("recommendation_reason") or item.get("reason")
        if reason:
            lines.append(f"   reason: {_ascii_pdf_text(reason)}")
    return lines[:42]


def _build_minimal_pdf(lines: list[str]) -> bytes:
    """生成一个单页、可打开、可见文本的最小 PDF。"""

    content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    for index, line in enumerate(lines):
        escaped = _escape_pdf_literal(line)
        if index == 0:
            content_lines.append(f"({escaped}) Tj")
        else:
            content_lines.append(f"T* ({escaped}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R"
            b" >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def _ascii_pdf_text(value: Any) -> str:
    """把中文等非内置字体字符转成 ASCII 转义，避免 PDF 内置字体渲染空白。"""

    return str(value).encode("unicode_escape").decode("ascii")


def _escape_pdf_literal(value: str) -> str:
    """转义 PDF literal string 中的特殊字符。"""

    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:120]
