from __future__ import annotations

from io import BytesIO
from typing import Any


def plan_to_markdown(plan: dict[str, Any]) -> str:
    """把结构化方案转换成可审阅、可导出的 Markdown 内容。

    PDF 导出以这份 Markdown 为内容源，保证导出的文本和前端展示字段一致。
    """

    title = str(plan.get("title") or plan.get("recommendation", {}).get("title") or "本地生活方案")
    lines = [
        f"# {title}",
        "",
        f"- 方案评分：{plan.get('plan_score', '待评估')}",
        f"- 总时长：{plan.get('total_duration_minutes', '待估算')} 分钟",
        f"- 路线时间：{plan.get('route_minutes', '待估算')} 分钟",
        f"- 总距离：{plan.get('total_distance_km', '待估算')} km",
        f"- 预算估算：{plan.get('estimated_budget', '待估算')} 元",
        "",
    ]

    reason = plan.get("recommendation_reason") or plan.get("fit_summary") or "该方案基于当前偏好、距离和时间窗口生成。"
    lines.extend(["## 推荐理由", "", str(reason), ""])

    pros = [str(item) for item in plan.get("pros", []) if item]
    cons = [str(item) for item in plan.get("cons", []) if item]
    if pros:
        lines.extend(["## 优点", ""])
        lines.extend(f"- {item}" for item in pros[:5])
        lines.append("")
    if cons:
        lines.extend(["## 需要注意", ""])
        lines.extend(f"- {item}" for item in cons[:5])
        lines.append("")

    timeline = plan.get("timeline") if isinstance(plan.get("timeline"), list) else []
    if timeline:
        lines.extend(["## 行程时间线", ""])
        for item in timeline:
            if not isinstance(item, dict):
                continue
            time_range = f"{item.get('start_time', '--:--')} - {item.get('end_time', '--:--')}"
            name = item.get("name") or item.get("title") or item.get("slot_type") or "行程节点"
            lines.append(f"- **{time_range}**｜{name}")
        lines.append("")

    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if items:
        lines.extend(["## 地点详情", ""])
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            lines.append(f"### {index}. {item.get('name', '未知地点')}")
            lines.append(f"- 类别：{item.get('category', '本地生活')} / {item.get('subcategory', '未分类')}")
            lines.append(f"- 地址：{item.get('address', '地址待确认')}")
            if item.get("rating") not in (None, ""):
                lines.append(f"- 评分：{item.get('rating')}")
            if item.get("price_level") not in (None, ""):
                lines.append(f"- 价格等级：{item.get('price_level')}")
            reason = item.get("recommendation_reason") or item.get("reason")
            if reason:
                lines.append(f"- 推荐理由：{reason}")
            options = item.get("option_prompts") if isinstance(item.get("option_prompts"), list) else []
            if options:
                lines.append("- 可选调整：" + "；".join(str(option) for option in options[:4]))
            lines.append("")

    route_segments = plan.get("route_segments") if isinstance(plan.get("route_segments"), list) else []
    if route_segments:
        lines.extend(["## 路线与交通", ""])
        for segment in route_segments:
            if not isinstance(segment, dict):
                continue
            from_name = segment.get("from_name") or segment.get("from_item_id") or "上一站"
            to_name = segment.get("to_name") or segment.get("to_item_id") or "下一站"
            distance = segment.get("distance_km", "待估算")
            minutes = segment.get("duration_minutes", "待估算")
            mode = segment.get("transport_mode", "推荐交通")
            lines.append(f"- {from_name} → {to_name}：{distance} km，{minutes} 分钟，{mode}")
        lines.append("")

    issues = plan.get("issues") if isinstance(plan.get("issues"), list) else []
    if issues:
        lines.extend(["## 校验提示", ""])
        for issue in issues[:8]:
            if isinstance(issue, dict):
                lines.append(f"- {issue.get('message', '存在待确认风险')}（建议：{issue.get('suggestion', '请确认后执行')}）")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_markdown_pdf(plan: dict[str, Any]) -> bytes:
    """把方案 Markdown 渲染为中文 PDF。

    使用 ReportLab 的内置中文 CID 字体 `STSong-Light`，不再把中文转成 ASCII
    转义。若运行环境缺少 ReportLab，会抛出清晰异常，调用方可记录 trace。
    """

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ModuleNotFoundError as exc:  # pragma: no cover - 依赖安装问题由部署环境处理
        raise RuntimeError("ReportLab 未安装，无法生成中文 PDF。请安装 requirements.txt。") from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    markdown = plan_to_markdown(plan)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=str(plan.get("title") or "LifeRouteAgent Plan"),
    )
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "LifeRouteBase",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=5,
    )
    h1 = ParagraphStyle(
        "LifeRouteH1",
        parent=base,
        fontSize=20,
        leading=27,
        textColor=colors.HexColor("#111827"),
        spaceAfter=12,
    )
    h2 = ParagraphStyle(
        "LifeRouteH2",
        parent=base,
        fontSize=14,
        leading=20,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=8,
        spaceAfter=6,
    )
    h3 = ParagraphStyle(
        "LifeRouteH3",
        parent=base,
        fontSize=12,
        leading=18,
        textColor=colors.HexColor("#374151"),
        spaceBefore=5,
        spaceAfter=4,
    )
    bullet = ParagraphStyle("LifeRouteBullet", parent=base, leftIndent=12, firstLineIndent=-8)

    story: list[Any] = []
    overview_rows: list[list[Any]] = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape(line[2:]), h1))
        elif line.startswith("## "):
            if overview_rows:
                story.append(_overview_table(overview_rows, base, colors, Table, TableStyle, mm))
                overview_rows = []
            story.append(Paragraph(_escape(line[3:]), h2))
        elif line.startswith("### "):
            story.append(Paragraph(_escape(line[4:]), h3))
        elif line.startswith("- "):
            content = line[2:]
            if content.startswith(("方案评分：", "总时长：", "路线时间：", "总距离：", "预算估算：")):
                key, _, value = content.partition("：")
                overview_rows.append([Paragraph(_escape(key), base), Paragraph(_escape(value), base)])
            else:
                story.append(Paragraph("• " + _escape(content), bullet))
        else:
            story.append(Paragraph(_escape(line), base))

    if overview_rows:
        story.append(_overview_table(overview_rows, base, colors, Table, TableStyle, mm))

    doc.build(story)
    return buffer.getvalue()


def _overview_table(
    rows: list[list[Any]],
    base: Any,
    colors: Any,
    table_cls: Any,
    style_cls: Any,
    mm: float,
) -> Any:
    """渲染方案概览表，让 PDF 开头更像正式导出物。"""

    table = table_cls(rows, colWidths=[42 * mm, 110 * mm])
    table.setStyle(
        style_cls(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _escape(text: Any) -> str:
    """把 Markdown 文本安全转换为 ReportLab Paragraph 可渲染文本。"""

    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("**", "")
    )
