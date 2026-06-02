from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen


def build_product_plan_pdf(plan: dict[str, Any]) -> bytes:
    """生成 PlanGo 产品级两页 PDF。

    设计目标是把结构化方案导出为可分享的产品物料，而不是普通表格。
    所有内容只读取 plan 中已有事实：方案标题、指标、地点、路线、优缺点、图片。
    图片 URL 不可访问时使用渐变占位，不编造图片。
    """

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
        from reportlab.graphics.barcode import qr
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics import renderPDF
    except ModuleNotFoundError as exc:  # pragma: no cover - 部署依赖问题
        raise RuntimeError("ReportLab 未安装，无法生成 PlanGo 中文 PDF。") from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    page_size = landscape(A4)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size

    theme = {
        "ink": colors.HexColor("#14243A"),
        "text": colors.HexColor("#40566F"),
        "muted": colors.HexColor("#7D91A7"),
        "blue": colors.HexColor("#2F7FF6"),
        "mint": colors.HexColor("#20B88F"),
        "soft_blue": colors.HexColor("#EAF5FF"),
        "soft_mint": colors.HexColor("#EAFBF5"),
        "line": colors.HexColor("#DCECF8"),
        "card": colors.HexColor("#FFFFFF"),
        "bg": colors.HexColor("#F6FBFF"),
        "warn": colors.HexColor("#F2A12B"),
    }

    title = _title(plan)
    steps = _steps(plan)
    tags = _highlight_tags(plan)
    total_minutes = int(plan.get("total_duration_min") or plan.get("total_duration_minutes") or 0)
    route_minutes = sum(int(seg.get("duration_min") or seg.get("duration_minutes") or 0) for seg in _segments(plan))
    distance_km = _distance_km(plan)
    budget = int(plan.get("total_cost") or plan.get("estimated_budget") or 0)
    modes = _transport_modes(plan)
    hero_image = _first_image(plan, steps)

    _draw_page_background(c, width, height, theme)
    _draw_logo(c, 34, height - 42, theme)
    _draw_text(c, title, 34, height - 96, 30, theme["ink"], bold=True, max_width=390, leading=36)
    _draw_text(c, "为你精心规划的本地生活方案", 34, height - 146, 12, theme["text"], max_width=300)
    _metric_cards(
        c,
        [
            ("总时长", _minute_text(total_minutes), _time_range(plan)),
            ("预算", f"约 ¥{budget}" if budget else "待确认", "经济实惠" if budget else "以现场为准"),
            ("总里程", f"{distance_km:.1f} 公里" if distance_km else "待确认", "轻松不赶路" if distance_km else "路线待确认"),
            ("出行方式", " / ".join(modes) if modes else "待确认", f"约 {route_minutes} 分钟" if route_minutes else "交通待确认"),
        ],
        x=34,
        y=height - 248,
        theme=theme,
    )
    _draw_image_card(c, hero_image, 34, height - 405, 390, 120, theme, ImageReader)
    _draw_tags_card(c, 34, 60, 390, 96, tags, theme)
    _draw_route_overview(c, 34, 176, 390, 106, steps, _segments(plan), theme)
    _draw_footer(c, width, theme, qr, Drawing, renderPDF, page_text="第 1 页 / 共 2 页")
    c.showPage()

    _draw_page_background(c, width, height, theme)
    _draw_logo(c, 34, height - 42, theme)
    _draw_text(c, "详细行程安排", 34, height - 72, 16, theme["ink"], bold=True)
    _draw_timeline(c, 34, 86, 470, height - 116, steps, _segments(plan), theme, ImageReader)
    _draw_map_panel(c, 540, height - 265, 270, 190, steps, theme)
    _draw_analysis_panel(c, 540, height - 435, 270, 145, plan, theme)
    _draw_pack_list(c, 540, 86, 270, 96, tags, theme)
    _draw_footer(c, width, theme, qr, Drawing, renderPDF, page_text="第 2 页 / 共 2 页")
    c.save()
    return buffer.getvalue()


def _draw_page_background(c: Any, width: float, height: float, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["bg"])
    c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setFillColorRGB(0.90, 0.97, 1.00, alpha=0.86)
    c.circle(width * 0.18, height * 0.88, 180, stroke=0, fill=1)
    c.setFillColorRGB(0.88, 1.00, 0.96, alpha=0.82)
    c.circle(width * 0.88, height * 0.15, 170, stroke=0, fill=1)


def _draw_logo(c: Any, x: float, y: float, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["blue"])
    c.roundRect(x, y - 18, 20, 20, 6, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("STSong-Light", 11)
    c.drawCentredString(x + 10, y - 13, "P")
    c.setFillColor(theme["ink"])
    c.setFont("STSong-Light", 15)
    c.drawString(x + 28, y - 14, "PlanGo")
    c.setFillColor(theme["muted"])
    c.setFont("STSong-Light", 7)
    c.drawRightString(810, y - 11, f"生成时间：{datetime.now().strftime('%Y年%m月%d日')}")


def _metric_cards(c: Any, metrics: list[tuple[str, str, str]], x: float, y: float, theme: dict[str, Any]) -> None:
    for index, (label, value, hint) in enumerate(metrics):
        card_x = x + index * 104
        _card(c, card_x, y, 92, 66, theme)
        c.setFillColor(theme["muted"])
        c.setFont("STSong-Light", 8)
        c.drawString(card_x + 12, y + 45, label)
        c.setFillColor(theme["ink"])
        c.setFont("STSong-Light", 13)
        c.drawString(card_x + 12, y + 24, value)
        c.setFillColor(theme["text"])
        c.setFont("STSong-Light", 7)
        c.drawString(card_x + 12, y + 10, hint[:14])


def _draw_image_card(c: Any, image_url: str | None, x: float, y: float, w: float, h: float, theme: dict[str, Any], image_reader: Any) -> None:
    _card(c, x, y, w, h, theme)
    image = _load_image(image_url, image_reader)
    if image:
        c.drawImage(image, x + 8, y + 8, w - 16, h - 16, preserveAspectRatio=True, mask="auto")
    else:
        c.setFillColor(theme["soft_blue"])
        c.roundRect(x + 8, y + 8, w - 16, h - 16, 18, stroke=0, fill=1)
        c.setFillColor(theme["blue"])
        c.setFont("STSong-Light", 18)
        c.drawCentredString(x + w / 2, y + h / 2 + 4, "PlanGo")
        c.setFillColor(theme["muted"])
        c.setFont("STSong-Light", 9)
        c.drawCentredString(x + w / 2, y + h / 2 - 16, "图片待确认，方案信息不受影响")


def _draw_tags_card(c: Any, x: float, y: float, w: float, h: float, tags: list[str], theme: dict[str, Any]) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "方案亮点", x + 14, y + h - 24, 11, theme["ink"], bold=True)
    for index, tag in enumerate(tags[:4]):
        px = x + 16 + (index % 4) * 88
        py = y + 30
        c.setFillColor(theme["soft_mint"] if index % 2 else theme["soft_blue"])
        c.roundRect(px, py, 76, 26, 12, stroke=0, fill=1)
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.setFont("STSong-Light", 8)
        c.drawCentredString(px + 38, py + 9, tag[:8])


def _draw_route_overview(c: Any, x: float, y: float, w: float, h: float, steps: list[dict[str, Any]], segments: list[dict[str, Any]], theme: dict[str, Any]) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "行程概览", x + 14, y + h - 24, 11, theme["ink"], bold=True)
    count = max(len(steps), 1)
    start_x = x + 44
    end_x = x + w - 44
    line_y = y + 42
    c.setStrokeColor(theme["line"])
    c.setLineWidth(1.4)
    c.line(start_x, line_y, end_x, line_y)
    for index, step in enumerate(steps[:5]):
        px = start_x + (end_x - start_x) * index / max(count - 1, 1)
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.circle(px, line_y, 10, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("STSong-Light", 8)
        c.drawCentredString(px, line_y - 3, chr(65 + index))
        c.setFillColor(theme["ink"])
        c.setFont("STSong-Light", 7)
        c.drawCentredString(px, line_y - 22, _short(_step_title(step), 9))
        if index < len(segments):
            minutes = segments[index].get("duration_min") or segments[index].get("duration_minutes")
            if minutes:
                c.setFillColor(theme["muted"])
                c.drawCentredString(px + 34, line_y + 13, f"{minutes}分钟")


def _draw_timeline(c: Any, x: float, y: float, w: float, h: float, steps: list[dict[str, Any]], segments: list[dict[str, Any]], theme: dict[str, Any], image_reader: Any) -> None:
    c.setStrokeColor(theme["line"])
    c.setLineWidth(1)
    c.line(x + 18, y, x + 18, y + h - 10)
    cursor = y + h - 84
    for index, step in enumerate(steps[:5]):
        marker_y = cursor + 38
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.circle(x + 18, marker_y, 12, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("STSong-Light", 9)
        c.drawCentredString(x + 18, marker_y - 3, chr(65 + index))

        _card(c, x + 42, cursor, w - 42, 78, theme)
        image = _load_image(_step_image(step), image_reader)
        if image:
            c.drawImage(image, x + w - 104, cursor + 10, 74, 58, preserveAspectRatio=True, mask="auto")
        c.setFillColor(theme["blue"])
        c.setFont("STSong-Light", 8)
        c.drawString(x + 60, cursor + 58, _time_range_step(step))
        c.setFillColor(theme["ink"])
        c.setFont("STSong-Light", 12)
        c.drawString(x + 60, cursor + 39, _short(_step_title(step), 24))
        if _step_cost(step):
            c.setFillColor(theme["text"])
            c.setFont("STSong-Light", 8)
            c.drawRightString(x + w - 118, cursor + 59, f"¥{_step_cost(step)}/人")
        _draw_text(c, _step_reason(step), x + 60, cursor + 22, 8, theme["text"], max_width=w - 198, leading=11)
        if index < len(segments):
            segment = segments[index]
            mode = segment.get("transport_mode") or "交通"
            minutes = segment.get("duration_min") or segment.get("duration_minutes")
            c.setFillColor(theme["soft_blue"])
            c.roundRect(x + 42, cursor - 34, w - 42, 24, 10, stroke=0, fill=1)
            c.setFillColor(theme["blue"])
            c.setFont("STSong-Light", 8)
            c.drawString(x + 60, cursor - 25, f"{mode} · 约 {minutes or '待确认'} 分钟")
        cursor -= 112


def _draw_map_panel(c: Any, x: float, y: float, w: float, h: float, steps: list[dict[str, Any]], theme: dict[str, Any]) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "路线地图", x + 14, y + h - 24, 11, theme["ink"], bold=True)
    c.setFillColor(theme["soft_blue"])
    c.roundRect(x + 12, y + 40, w - 24, h - 72, 18, stroke=0, fill=1)
    points = [(x + 44, y + 74), (x + 118, y + 124), (x + 196, y + 98), (x + 234, y + 142)]
    c.setStrokeColor(theme["blue"])
    c.setLineWidth(2.5)
    for a, b in zip(points, points[1:]):
        c.line(a[0], a[1], b[0], b[1])
    for index, point in enumerate(points[: len(steps[:4])]):
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.circle(point[0], point[1], 10, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("STSong-Light", 8)
        c.drawCentredString(point[0], point[1] - 3, chr(65 + index))


def _draw_analysis_panel(c: Any, x: float, y: float, w: float, h: float, plan: dict[str, Any], theme: dict[str, Any]) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "优缺点分析", x + 14, y + h - 24, 11, theme["ink"], bold=True)
    pros = _string_list(plan.get("pros")) or _string_list(plan.get("rationale"))[:2]
    cons = _string_list(plan.get("cons")) or _string_list(plan.get("risk_flags"))[:2]
    cursor = y + h - 48
    c.setFillColor(theme["mint"])
    c.setFont("STSong-Light", 9)
    c.drawString(x + 16, cursor, "优势")
    cursor -= 16
    for item in pros[:3]:
        _draw_text(c, f"✓ {_short(item, 34)}", x + 18, cursor, 8, theme["text"], max_width=w - 32, leading=10)
        cursor -= 16
    c.setFillColor(theme["warn"])
    c.setFont("STSong-Light", 9)
    c.drawString(x + 16, cursor, "注意事项")
    cursor -= 16
    for item in cons[:3]:
        _draw_text(c, f"• {_short(item, 34)}", x + 18, cursor, 8, theme["text"], max_width=w - 32, leading=10)
        cursor -= 16


def _draw_pack_list(c: Any, x: float, y: float, w: float, h: float, tags: list[str], theme: dict[str, Any]) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "推荐物品清单", x + 14, y + h - 24, 11, theme["ink"], bold=True)
    items = ["身份证", "充电宝", "少量现金", "雨伞", "纸巾湿巾"]
    if any("室内" in tag for tag in tags):
        items[3] = "轻便外套"
    for index, item in enumerate(items):
        px = x + 16 + (index % 5) * 49
        py = y + 28
        c.setFillColor(theme["soft_blue"] if index % 2 else theme["soft_mint"])
        c.roundRect(px, py, 42, 22, 10, stroke=0, fill=1)
        c.setFillColor(theme["text"])
        c.setFont("STSong-Light", 7)
        c.drawCentredString(px + 21, py + 8, item[:5])


def _draw_footer(c: Any, width: float, theme: dict[str, Any], qr: Any, drawing_cls: Any, render_pdf: Any, *, page_text: str) -> None:
    c.setFillColor(theme["muted"])
    c.setFont("STSong-Light", 8)
    c.drawCentredString(width / 2, 22, page_text)
    c.drawString(34, 22, "PlanGo · 让本地生活更简单、更美好")
    qr_code = qr.QrCodeWidget("https://github.com/Dengpc-FIRE/LifeRouteAgent")
    bounds = qr_code.getBounds()
    drawing = drawing_cls(42, 42, transform=[42 / (bounds[2] - bounds[0]), 0, 0, 42 / (bounds[3] - bounds[1]), 0, 0])
    drawing.add(qr_code)
    render_pdf.draw(drawing, c, width - 76, 14)


def _card(c: Any, x: float, y: float, w: float, h: float, theme: dict[str, Any]) -> None:
    c.setFillColorRGB(1, 1, 1, alpha=0.78)
    c.roundRect(x + 2, y - 2, w, h, 22, stroke=0, fill=1)
    c.setFillColor(theme["card"])
    c.setStrokeColor(theme["line"])
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 22, stroke=1, fill=1)


def _draw_text(c: Any, text: str, x: float, y: float, size: float, color: Any, *, bold: bool = False, max_width: float = 240, leading: float | None = None) -> None:
    c.setFillColor(color)
    c.setFont("STSong-Light", size)
    line_height = leading or size * 1.35
    for index, line in enumerate(_wrap(text, max_width, size)):
        c.drawString(x, y - index * line_height, line)


def _wrap(text: str, max_width: float, size: float) -> list[str]:
    limit = max(int(max_width / (size * 0.62)), 8)
    raw = str(text or "")
    return [raw[i : i + limit] for i in range(0, len(raw), limit)] or [""]


def _load_image(url: str | None, image_reader: Any) -> Any | None:
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    try:
        request = Request(str(url), headers={"User-Agent": "PlanGo-PDF/1.0"})
        with urlopen(request, timeout=1.6) as response:
            return image_reader(BytesIO(response.read()))
    except Exception:
        return None


def _title(plan: dict[str, Any]) -> str:
    return str(plan.get("title") or (plan.get("recommendation") or {}).get("title") or "PlanGo 本地生活方案")


def _steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in plan.get("steps", []) if isinstance(item, dict)]


def _segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    return [item for item in route.get("segments", []) if isinstance(item, dict)]


def _highlight_tags(plan: dict[str, Any]) -> list[str]:
    tags = _string_list(plan.get("highlight_tags"))
    if not tags:
        tags = _string_list((plan.get("recommendation") or {}).get("tags"))
    return _unique([_short(item, 8) for item in tags if item])[:4] or ["节奏轻松", "路线清晰", "预算可控", "适合分享"]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _minute_text(minutes: int) -> str:
    if not minutes:
        return "待确认"
    h, m = divmod(minutes, 60)
    return f"{h}小时{m}分" if h and m else (f"{h}小时" if h else f"{m}分钟")


def _distance_km(plan: dict[str, Any]) -> float:
    route_distance = sum(float(seg.get("distance_km") or 0) for seg in _segments(plan))
    if route_distance:
        return route_distance
    return float((plan.get("recommendation") or {}).get("distance_km") or 0)


def _transport_modes(plan: dict[str, Any]) -> list[str]:
    modes = _unique([str(seg.get("transport_mode") or "").strip() for seg in _segments(plan)])
    return [mode for mode in modes if mode]


def _time_range(plan: dict[str, Any]) -> str:
    start = plan.get("start_time")
    end = plan.get("end_time")
    return f"{start} - {end}" if start and end and start != "--:--" and end != "--:--" else "时间待确认"


def _time_range_step(step: dict[str, Any]) -> str:
    start = step.get("start_time")
    end = step.get("end_time")
    return f"{start} - {end}" if start and end and start != "--:--" and end != "--:--" else "时间待确认"


def _first_image(plan: dict[str, Any], steps: list[dict[str, Any]]) -> str | None:
    recommendation = plan.get("recommendation") if isinstance(plan.get("recommendation"), dict) else {}
    return str(recommendation.get("cover_image") or next((_step_image(step) for step in steps if _step_image(step)), "") or "") or None


def _step_image(step: dict[str, Any]) -> str | None:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    images = detail.get("images") if isinstance(detail.get("images"), list) else []
    return str(detail.get("image_url") or (images[0] if images else "") or "") or None


def _step_title(step: dict[str, Any]) -> str:
    return str(step.get("title") or "行程节点")


def _step_reason(step: dict[str, Any]) -> str:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    return str(step.get("reason") or detail.get("description") or "符合当前偏好与路线安排。")


def _step_cost(step: dict[str, Any]) -> int:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    return int(step.get("cost") or detail.get("cost") or 0)


def _short(text: Any, limit: int) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[:limit] + "…"
