from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from app.core.timeutils import format_local_date, format_local_datetime


def _to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _format_compact_value(value: float, suffix: str = "") -> str:
    if value >= 100:
        return f"{value:.0f}{suffix}"
    if value >= 10:
        return f"{value:.1f}{suffix}"
    return f"{value:.2f}{suffix}"


def build_bar_chart(
    items: Iterable[dict],
    *,
    label_key: str = "label",
    value_key: str = "value",
    suffix: str = "",
) -> dict:
    raw_items = list(items)
    values = [_to_float(item.get(value_key)) for item in raw_items]
    max_value = max(values) if values else 0.0
    chart_items: list[dict] = []
    for item, value in zip(raw_items, values, strict=False):
        pct = (value / max_value * 100.0) if max_value > 0 else 0.0
        chart_items.append(
            {
                "label": item.get(label_key, "—"),
                "value": value,
                "value_display": item.get("value_display") or _format_compact_value(value, suffix),
                "pct": max(pct, 2.0) if value > 0 else 0.0,
                "title": item.get("title") or f"{item.get(label_key, '—')}: {_format_compact_value(value, suffix)}",
                "meta": item.get("meta"),
            }
        )
    return {
        "items": chart_items,
        "has_data": any(value > 0 for value in values),
        "max_value": max_value,
        "max_value_display": _format_compact_value(max_value, suffix) if max_value else f"0{suffix}",
    }


def build_line_chart(
    points: Iterable[dict],
    *,
    value_key: str = "value",
    width: int = 760,
    height: int = 220,
    padding_x: int = 16,
    padding_y: int = 18,
    suffix: str = "",
) -> dict:
    raw_points = list(points)
    if not raw_points:
        return {
            "has_data": False,
            "svg_points": "",
            "svg_area_points": "",
            "items": [],
            "labels": [],
            "max_value_display": f"0{suffix}",
            "min_value_display": f"0{suffix}",
            "latest_value_display": f"0{suffix}",
        }

    numeric_values = [_to_float(item.get(value_key)) for item in raw_points]
    min_value = min(numeric_values)
    max_value = max(numeric_values)
    spread = max(max_value - min_value, 1.0)
    usable_width = max(width - padding_x * 2, 1)
    usable_height = max(height - padding_y * 2, 1)
    count = max(len(raw_points) - 1, 1)

    chart_items: list[dict] = []
    point_tokens: list[str] = []
    for index, (item, numeric_value) in enumerate(zip(raw_points, numeric_values, strict=False)):
        x = padding_x + usable_width * (index / count)
        offset = (numeric_value - min_value) / spread
        y = height - padding_y - usable_height * offset
        label = item.get("label") or item.get("title") or str(index + 1)
        value_display = item.get("value_display") or _format_compact_value(numeric_value, suffix)
        chart_items.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "label": label,
                "value": numeric_value,
                "value_display": value_display,
                "title": item.get("title") or f"{label}: {value_display}",
            }
        )
        point_tokens.append(f"{x:.2f},{y:.2f}")

    baseline_y = height - padding_y
    area_points = [f"{padding_x:.2f},{baseline_y:.2f}", *point_tokens, f"{padding_x + usable_width:.2f},{baseline_y:.2f}"]

    label_indexes = sorted({0, len(chart_items) // 2, len(chart_items) - 1})
    labels = [chart_items[index] for index in label_indexes]

    return {
        "has_data": any(value > 0 for value in numeric_values),
        "svg_points": " ".join(point_tokens),
        "svg_area_points": " ".join(area_points),
        "items": chart_items,
        "labels": labels,
        "max_value_display": _format_compact_value(max_value, suffix),
        "min_value_display": _format_compact_value(min_value, suffix),
        "latest_value_display": chart_items[-1]["value_display"],
    }


def label_for_datetime(value: datetime | None) -> str:
    return format_local_datetime(value) if value else "—"


def label_for_date(value: date | None) -> str:
    return format_local_date(value) if value else "—"
