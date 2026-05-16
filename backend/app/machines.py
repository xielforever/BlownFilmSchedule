from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .models import Machine


WORKSPACE_DIR = Path(__file__).resolve().parents[2]
MACHINE_DATA_PATH = WORKSPACE_DIR / "data" / "machines.xlsx"

MACHINE_COLUMNS = [
    "machine_id",
    "mold_spec",
    "capacity_min_kg_h",
    "capacity_max_kg_h",
    "insert_size_mm",
    "width_limit_br1",
    "width_recommend_br1_5",
    "width_recommend_br2",
    "width_recommend_br2_5",
    "width_over_range_br3",
    "width_limit_br3_5",
    "width_hd_limit",
    "width_hd_br2",
    "width_hd_br3",
    "width_hd_br4",
    "width_hd_br5",
    "width_hd_br6",
    "remark",
    "rule_tags",
]

REQUIRED_MACHINE_COLUMNS = ["machine_id"]
NUMERIC_MACHINE_COLUMNS = {
    "capacity_min_kg_h",
    "capacity_max_kg_h",
    "width_limit_br1",
    "width_recommend_br1_5",
    "width_recommend_br2",
    "width_recommend_br2_5",
    "width_over_range_br3",
    "width_limit_br3_5",
    "width_hd_limit",
    "width_hd_br2",
    "width_hd_br3",
    "width_hd_br4",
    "width_hd_br5",
    "width_hd_br6",
}


def built_in_machines(path: Path | None = None) -> list[Machine]:
    """Load local machine capabilities from the workspace machine workbook."""
    return load_machines_from_excel(path or MACHINE_DATA_PATH)


def load_machines_from_excel(path: Path) -> list[Machine]:
    if not path.exists():
        raise FileNotFoundError(f"本地机台能力表不存在: {path}")

    try:
        df = pd.read_excel(path, sheet_name="machines")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0)

    df = df.rename(columns={str(col).strip(): str(col).strip() for col in df.columns})
    missing = [col for col in REQUIRED_MACHINE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"机台能力表缺少必填列: {', '.join(missing)}")

    machines: list[Machine] = []
    for index, row in df.iterrows():
        raw = _clean_dict(row.to_dict())
        machine_id = _as_str(raw.get("machine_id"))
        if not machine_id:
            continue

        data: dict[str, Any] = {"machine_id": machine_id}
        for column in MACHINE_COLUMNS:
            if column == "machine_id":
                continue
            value = raw.get(column)
            if column == "rule_tags":
                data[column] = _as_tags(value)
            elif column in NUMERIC_MACHINE_COLUMNS:
                data[column] = _as_float(value)
            else:
                data[column] = _as_str(value)

        try:
            machines.append(Machine(**data))
        except Exception as exc:
            raise ValueError(f"机台能力表第 {index + 2} 行无法读取: {exc}") from exc

    if not machines:
        raise ValueError("机台能力表没有可用机台")
    return machines


def _clean_dict(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: None if pd.isna(value) else value for key, value in raw.items()}


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_tags(value: Any) -> list[str]:
    text = _as_str(value)
    if not text:
        return []
    return [tag.strip() for tag in text.replace("，", ",").replace(";", ",").split(",") if tag.strip()]
