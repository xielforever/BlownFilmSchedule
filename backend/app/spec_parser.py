from __future__ import annotations

import re

from .models import ParsedSpec


NUMBER = r"\d+(?:\.\d+)?"


def parse_spec(spec_raw: str | None) -> ParsedSpec:
    raw = (spec_raw or "").strip()
    if not raw:
        return ParsedSpec(raw="", parse_status="failed", parse_message="生产规格为空")

    normalized = raw.replace("×", "*").replace(" ", "")
    numbers = [float(x) for x in re.findall(NUMBER, normalized)]
    if len(numbers) < 2:
        return ParsedSpec(raw=raw, parse_status="failed", parse_message="规格中数字不足")

    thickness = _parse_thickness(normalized, numbers)
    if thickness is None:
        return ParsedSpec(raw=raw, parse_status="failed", parse_message="无法识别厚度")

    insert_width = _parse_insert_width(normalized)
    base_width = _parse_base_width(normalized, numbers)
    if base_width is None:
        return ParsedSpec(raw=raw, parse_status="failed", parse_message="无法识别宽度")

    width = base_width + (insert_width or 0)
    return ParsedSpec(
        width_mm=round(width, 3),
        thickness_mm=round(thickness, 4),
        insert_width_mm=round(insert_width, 3) if insert_width is not None else None,
        raw=raw,
        parse_status="ok",
    )


def _parse_thickness(normalized: str, numbers: list[float]) -> float | None:
    mm_match = re.search(rf"({NUMBER})mm", normalized, re.IGNORECASE)
    if mm_match:
        return float(mm_match.group(1))

    decimal_numbers = [value for value in numbers if value < 3]
    if decimal_numbers:
        return decimal_numbers[-1]
    return None


def _parse_insert_width(normalized: str) -> float | None:
    match = re.search(r"\(([^)]*)\)", normalized)
    if not match:
        return None
    values = [float(x) for x in re.findall(NUMBER, match.group(1))]
    return sum(values) if values else None


def _parse_base_width(normalized: str, numbers: list[float]) -> float | None:
    leading = re.match(rf"({NUMBER})", normalized)
    if leading:
        return float(leading.group(1))
    large_numbers = [value for value in numbers if value >= 3]
    return large_numbers[0] if large_numbers else None

