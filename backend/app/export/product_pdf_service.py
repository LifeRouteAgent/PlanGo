from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen


def build_product_plan_pdf(plan: dict[str, Any]) -> bytes:
    """生成 PlanGo 产品化中文 PDF。

    该导出只读取结构化方案中的已有事实，不编造地点、价格、路线或图片。
    版式上去掉路线地图、二维码和行程概览，避免信息堆叠造成遮挡。
    """

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ModuleNotFoundError as exc:  # pragma: no cover
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

    steps = _steps(plan)
    tags = _highlight_tags(plan)
    title = _title(plan)
    total_minutes = int(plan.get("total_duration_min") or plan.get("total_duration_minutes") or 0)
    route_minutes = sum(
        int(seg.get("duration_min") or seg.get("duration_minutes") or 0) for seg in _segments(plan)
    )
    distance_km = _distance_km(plan)
    budget = int(plan.get("total_cost") or plan.get("estimated_budget") or 0)
    modes = _transport_modes(plan)

    # 第 1 页：方案概览
    _draw_page_background(c, width, height, theme)
    _draw_logo(c, 34, height - 42, theme)
    _draw_text(c, title, 34, height - 92, 28, theme["ink"], max_width=510, leading=34)
    _draw_text(c, "为你精心规划的本地生活方案", 34, height - 136, 12, theme["text"], max_width=340)
    _draw_generated_at(c, width, height, theme)

    _metric_cards(
        c,
        [
            ("总时长", _minute_text(total_minutes), _time_range(plan)),
            (
                "预算",
                f"约 ¥{budget}" if budget else "待确认",
                "以现场为准" if not budget else "预算可控",
            ),
            (
                "总距离",
                f"{distance_km:.1f} 公里" if distance_km else "待确认",
                "路线待确认" if not distance_km else "轻松不赶路",
            ),
            (
                "出行方式",
                " / ".join(modes) if modes else "待确认",
                f"交通约 {route_minutes} 分钟" if route_minutes else "交通待确认",
            ),
        ],
        x=34,
        y=height - 238,
        theme=theme,
    )

    _draw_image_card(c, _first_image(plan, steps), 34, height - 424, 458, 150, theme, ImageReader)
    _draw_tags_card(c, 34, height - 538, 458, 78, tags, theme)
    _draw_reason_card(c, 520, height - 424, 286, 264, plan, steps, theme)
    _draw_footer(c, width, "第 1 页 / 共 2 页", theme)
    c.showPage()

    # 第 2 页：详细行程 + 优缺点 + 出行清单
    _draw_page_background(c, width, height, theme)
    _draw_logo(c, 34, height - 42, theme)
    _draw_text(c, "详细行程安排", 34, height - 76, 18, theme["ink"], max_width=260)
    _draw_timeline(c, 34, 76, 492, height - 154, steps, _segments(plan), theme, ImageReader)
    _draw_analysis_panel(c, 552, height - 286, 260, 196, plan, theme)
    _draw_pack_list(c, 552, 120, 260, 112, tags, theme)
    _draw_footer(c, width, "第 2 页 / 共 2 页", theme)
    c.save()
    return buffer.getvalue()


def _draw_page_background(c: Any, width: float, height: float, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["bg"])
    c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setFillColorRGB(0.90, 0.97, 1.00, alpha=0.86)
    c.circle(width * 0.16, height * 0.86, 180, stroke=0, fill=1)
    c.setFillColorRGB(0.88, 1.00, 0.96, alpha=0.78)
    c.circle(width * 0.88, height * 0.18, 165, stroke=0, fill=1)


def _draw_logo(c: Any, x: float, y: float, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["blue"])
    c.roundRect(x, y - 18, 20, 20, 6, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("STSong-Light", 11)
    c.drawCentredString(x + 10, y - 13, "P")
    c.setFillColor(theme["ink"])
    c.setFont("STSong-Light", 15)
    c.drawString(x + 28, y - 14, "PlanGo")


def _draw_generated_at(c: Any, width: float, height: float, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["muted"])
    c.setFont("STSong-Light", 8)
    c.drawRightString(
        width - 34, height - 42, f"生成时间：{datetime.now().strftime('%Y年%m月%d日')}"
    )


def _metric_cards(
    c: Any, metrics: list[tuple[str, str, str]], x: float, y: float, theme: dict[str, Any]
) -> None:
    for index, (label, value, hint) in enumerate(metrics):
        card_x = x + index * 116
        _card(c, card_x, y, 102, 68, theme)
        c.setFillColor(theme["muted"])
        c.setFont("STSong-Light", 8)
        c.drawString(card_x + 12, y + 47, label)
        c.setFillColor(theme["ink"])
        c.setFont("STSong-Light", 13)
        c.drawString(card_x + 12, y + 26, value)
        c.setFillColor(theme["text"])
        c.setFont("STSong-Light", 7)
        c.drawString(card_x + 12, y + 10, hint[:16])


def _draw_image_card(
    c: Any,
    image_url: str | None,
    x: float,
    y: float,
    w: float,
    h: float,
    theme: dict[str, Any],
    image_reader: Any,
) -> None:
    _card(c, x, y, w, h, theme)
    image = _load_image(image_url, image_reader)
    if image:
        c.drawImage(image, x + 8, y + 8, w - 16, h - 16, preserveAspectRatio=True, mask="auto")
        return
    c.setFillColor(theme["soft_blue"])
    c.roundRect(x + 8, y + 8, w - 16, h - 16, 18, stroke=0, fill=1)
    c.setFillColor(theme["blue"])
    c.setFont("STSong-Light", 18)
    c.drawCentredString(x + w / 2, y + h / 2 + 5, "PlanGo")
    c.setFillColor(theme["muted"])
    c.setFont("STSong-Light", 9)
    c.drawCentredString(x + w / 2, y + h / 2 - 16, "图片待确认，方案内容不受影响")


def _draw_tags_card(
    c: Any, x: float, y: float, w: float, h: float, tags: list[str], theme: dict[str, Any]
) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "方案亮点", x + 16, y + h - 24, 11, theme["ink"], max_width=160)
    for index, tag in enumerate(tags[:4]):
        px = x + 16 + index * 106
        py = y + 22
        c.setFillColor(theme["soft_mint"] if index % 2 else theme["soft_blue"])
        c.roundRect(px, py, 92, 28, 14, stroke=0, fill=1)
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.setFont("STSong-Light", 8)
        c.drawCentredString(px + 46, py + 10, tag[:8])


def _draw_reason_card(
    c: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    plan: dict[str, Any],
    steps: list[dict[str, Any]],
    theme: dict[str, Any],
) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "为什么推荐", x + 16, y + h - 26, 13, theme["ink"], max_width=160)
    reason = _string_list(plan.get("rationale"))[:2] or [
        str(plan.get("recommendation_reason") or "该方案基于当前偏好、预算和时间窗口生成。")
    ]
    cursor = y + h - 58
    for item in reason:
        _draw_text(
            c,
            f"• {_short(item, 42)}",
            x + 18,
            cursor,
            9,
            theme["text"],
            max_width=w - 36,
            leading=13,
        )
        cursor -= 44
    _draw_text(c, "关键节点", x + 16, cursor - 4, 12, theme["ink"], max_width=160)
    cursor -= 28
    for index, step in enumerate(steps[:4]):
        _draw_text(
            c,
            f"{chr(65 + index)}  {_time_range_step(step)}  {_step_title(step)}",
            x + 18,
            cursor,
            8,
            theme["text"],
            max_width=w - 36,
        )
        cursor -= 18


def _draw_timeline(
    c: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    steps: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    theme: dict[str, Any],
    image_reader: Any,
) -> None:
    c.setStrokeColor(theme["line"])
    c.setLineWidth(1)
    c.line(x + 18, y + 10, x + 18, y + h - 16)
    cursor = y + h - 86
    for index, step in enumerate(steps[:4]):
        marker_y = cursor + 43
        c.setFillColor(theme["mint"] if index % 2 else theme["blue"])
        c.circle(x + 18, marker_y, 12, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("STSong-Light", 9)
        c.drawCentredString(x + 18, marker_y - 3, chr(65 + index))

        _card(c, x + 42, cursor, w - 42, 86, theme)
        image = _load_image(_step_image(step), image_reader)
        if image:
            c.drawImage(
                image, x + w - 108, cursor + 12, 78, 62, preserveAspectRatio=True, mask="auto"
            )
        c.setFillColor(theme["blue"])
        c.setFont("STSong-Light", 8)
        c.drawString(x + 60, cursor + 64, _time_range_step(step))
        c.setFillColor(theme["ink"])
        c.setFont("STSong-Light", 12)
        c.drawString(x + 60, cursor + 45, _short(_step_title(step), 24))
        if _step_cost(step):
            c.setFillColor(theme["text"])
            c.setFont("STSong-Light", 8)
            c.drawRightString(x + w - 118, cursor + 64, f"¥{_step_cost(step)}/人")
        _draw_text(
            c,
            _step_reason(step),
            x + 60,
            cursor + 27,
            8,
            theme["text"],
            max_width=w - 206,
            leading=11,
        )

        if index < len(segments):
            segment = segments[index]
            mode = segment.get("transport_mode") or "交通"
            minutes = segment.get("duration_min") or segment.get("duration_minutes")
            distance = segment.get("distance_km")
            text = f"{mode} · 约 {minutes or '待确认'} 分钟"
            if distance:
                text += f" · {float(distance):.1f} 公里"
            c.setFillColor(theme["soft_blue"])
            c.roundRect(x + 42, cursor - 31, w - 42, 24, 10, stroke=0, fill=1)
            c.setFillColor(theme["blue"])
            c.setFont("STSong-Light", 8)
            c.drawString(x + 60, cursor - 22, text)
        cursor -= 116


def _draw_analysis_panel(
    c: Any, x: float, y: float, w: float, h: float, plan: dict[str, Any], theme: dict[str, Any]
) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "优缺点分析", x + 14, y + h - 24, 12, theme["ink"], max_width=160)
    pros = _string_list(plan.get("pros")) or _string_list(plan.get("rationale"))[:2]
    cons = _string_list(plan.get("cons")) or _string_list(plan.get("risk_flags"))[:2]
    cursor = y + h - 50
    c.setFillColor(theme["mint"])
    c.setFont("STSong-Light", 9)
    c.drawString(x + 16, cursor, "优势")
    cursor -= 16
    for item in pros[:3]:
        _draw_text(
            c,
            f"✓ {_short(item, 34)}",
            x + 18,
            cursor,
            8,
            theme["text"],
            max_width=w - 32,
            leading=10,
        )
        cursor -= 18
    c.setFillColor(theme["warn"])
    c.setFont("STSong-Light", 9)
    c.drawString(x + 16, cursor - 2, "注意事项")
    cursor -= 20
    for item in cons[:3]:
        _draw_text(
            c,
            f"• {_short(item, 34)}",
            x + 18,
            cursor,
            8,
            theme["text"],
            max_width=w - 32,
            leading=10,
        )
        cursor -= 18


def _draw_pack_list(
    c: Any, x: float, y: float, w: float, h: float, tags: list[str], theme: dict[str, Any]
) -> None:
    _card(c, x, y, w, h, theme)
    _draw_text(c, "推荐物品清单", x + 14, y + h - 24, 12, theme["ink"], max_width=160)
    items = ["身份证", "充电宝", "少量现金", "纸巾湿巾"]
    if any("室内" in tag for tag in tags):
        items.append("轻便外套")
    else:
        items.append("雨伞")
    for index, item in enumerate(items[:5]):
        px = x + 16 + (index % 5) * 47
        py = y + 32
        c.setFillColor(theme["soft_blue"] if index % 2 else theme["soft_mint"])
        c.roundRect(px, py, 40, 24, 10, stroke=0, fill=1)
        c.setFillColor(theme["text"])
        c.setFont("STSong-Light", 7)
        c.drawCentredString(px + 20, py + 9, item[:5])


def _draw_footer(c: Any, width: float, page_text: str, theme: dict[str, Any]) -> None:
    c.setFillColor(theme["muted"])
    c.setFont("STSong-Light", 8)
    c.drawCentredString(width / 2, 22, page_text)
    c.drawString(34, 22, "PlanGo · 让本地生活更简单、更美好")


def _card(c: Any, x: float, y: float, w: float, h: float, theme: dict[str, Any]) -> None:
    c.setFillColorRGB(1, 1, 1, alpha=0.78)
    c.roundRect(x + 2, y - 2, w, h, 22, stroke=0, fill=1)
    c.setFillColor(theme["card"])
    c.setStrokeColor(theme["line"])
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, 22, stroke=1, fill=1)


def _draw_text(
    c: Any,
    text: str,
    x: float,
    y: float,
    size: float,
    color: Any,
    *,
    max_width: float = 240,
    leading: float | None = None,
) -> None:
    c.setFillColor(color)
    c.setFont("STSong-Light", size)
    line_height = leading or size * 1.35
    for index, line in enumerate(_wrap(text, max_width, size)):
        c.drawString(x, y - index * line_height, line)


def _wrap(text: Any, max_width: float, size: float) -> list[str]:
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
    return str(
        plan.get("title")
        or (plan.get("recommendation") or {}).get("title")
        or "PlanGo 本地生活方案"
    )


def _steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(plan.get("steps"), list):
        return [item for item in plan.get("steps", []) if isinstance(item, dict)]
    if isinstance(plan.get("items"), list):
        return [item for item in plan.get("items", []) if isinstance(item, dict)]
    return []


def _segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    if isinstance(route.get("segments"), list):
        return [item for item in route.get("segments", []) if isinstance(item, dict)]
    if isinstance(plan.get("route_segments"), list):
        return [item for item in plan.get("route_segments", []) if isinstance(item, dict)]
    return []


def _highlight_tags(plan: dict[str, Any]) -> list[str]:
    tags = _string_list(plan.get("highlight_tags"))
    if not tags:
        tags = _string_list((plan.get("recommendation") or {}).get("tags"))
    return _unique([_short(item, 8) for item in tags if item])[:4] or [
        "节奏轻松",
        "路线清晰",
        "预算可控",
        "适合分享",
    ]


def _string_list(value: Any) -> list[str]:
    return (
        [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, list)
        else []
    )


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = re.sub(r"[《》「」『』【】（）()\[\]\s,，.。:：;；、/\\|-]+", "", value).lower()
        if value and key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _minute_text(minutes: int) -> str:
    if not minutes:
        return "待确认"
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}小时{rest}分"
    return f"{hours}小时" if hours else f"{rest}分钟"


def _distance_km(plan: dict[str, Any]) -> float:
    route_distance = sum(float(seg.get("distance_km") or 0) for seg in _segments(plan))
    if route_distance:
        return route_distance
    return float(
        (plan.get("recommendation") or {}).get("distance_km") or plan.get("total_distance_km") or 0
    )


def _transport_modes(plan: dict[str, Any]) -> list[str]:
    modes = _unique([str(seg.get("transport_mode") or "").strip() for seg in _segments(plan)])
    return [mode for mode in modes if mode]


def _time_range(plan: dict[str, Any]) -> str:
    start = plan.get("start_time")
    end = plan.get("end_time")
    return (
        f"{start} - {end}"
        if start and end and start != "--:--" and end != "--:--"
        else "时间待确认"
    )


def _time_range_step(step: dict[str, Any]) -> str:
    start = step.get("start_time")
    end = step.get("end_time")
    return (
        f"{start} - {end}"
        if start and end and start != "--:--" and end != "--:--"
        else "时间待确认"
    )


def _first_image(plan: dict[str, Any], steps: list[dict[str, Any]]) -> str | None:
    recommendation = (
        plan.get("recommendation") if isinstance(plan.get("recommendation"), dict) else {}
    )
    return (
        str(
            recommendation.get("cover_image")
            or next((_step_image(step) for step in steps if _step_image(step)), "")
            or ""
        )
        or None
    )


def _step_image(step: dict[str, Any]) -> str | None:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    images = detail.get("images") if isinstance(detail.get("images"), list) else []
    return (
        str(detail.get("image_url") or (images[0] if images else "") or step.get("image_url") or "")
        or None
    )


def _step_title(step: dict[str, Any]) -> str:
    return str(step.get("title") or step.get("name") or "行程节点")


def _step_reason(step: dict[str, Any]) -> str:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    return str(
        step.get("reason")
        or step.get("recommendation_reason")
        or detail.get("description")
        or "符合当前偏好与路线安排。"
    )


def _step_cost(step: dict[str, Any]) -> int:
    detail = step.get("detail") if isinstance(step.get("detail"), dict) else {}
    return int(step.get("cost") or detail.get("cost") or step.get("estimated_cost") or 0)


def _short(text: Any, limit: int) -> str:
    value = str(text or "").replace("\n", " ").strip()
    return value if len(value) <= limit else value[:limit] + "…"
