from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any


def build_plan_ics(plan: dict[str, Any]) -> str:
    """把当前方案转换成标准 ICS 日历文本。

    v1 不接真实日历 API，只生成可下载文件；用户可以导入系统日历、Google Calendar 或 Outlook。
    """

    title = _escape_ics(plan.get("title") or "LifeRoute 本地生活方案")
    timeline = plan.get("timeline", []) if isinstance(plan.get("timeline"), list) else []
    base_date = datetime.now().date()
    events = []
    for index, item in enumerate(timeline, start=1):
        if not isinstance(item, dict):
            continue
        start = _parse_time(base_date, str(item.get("start_time") or "14:00"))
        end = _parse_time(base_date, str(item.get("end_time") or "")) or (
            start + timedelta(minutes=int(item.get("stay_minutes", 60) or 60))
        )
        events.append(
            _event_block(
                summary=f"{index}. {item.get('title') or item.get('category') or '行程'}",
                description=item.get("address") or "",
                start=start,
                end=end,
            )
        )
    if not events:
        start = datetime.now() + timedelta(hours=1)
        events.append(_event_block(title, "LifeRoute 方案", start, start + timedelta(hours=2)))

    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LifeRouteAgent//Local Life Plan//CN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{title}",
        *events,
        "END:VCALENDAR",
        "",
    ])


def _event_block(summary: str, description: str, start: datetime, end: datetime) -> str:
    uid = f"{uuid.uuid4().hex}@liferoute.local"
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return "\r\n".join([
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{_escape_ics(summary)}",
        f"DESCRIPTION:{_escape_ics(description)}",
        "END:VEVENT",
    ])


def _parse_time(base_date, text: str) -> datetime | None:
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    return datetime.combine(
        base_date,
        datetime.strptime(f"{int(match.group(1)):02d}:{int(match.group(2)):02d}", "%H:%M").time(),
    )


def _escape_ics(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace("\n", "\\n")
    return text.replace(",", "\\,").replace(";", "\\;")
