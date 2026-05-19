"""
APS 排程系统结果输出与可视化模块

提供 JSON/CSV 导出、投料修正通知单、Markdown 排程报告、ASCII 甘特图、统计摘要。
"""

from __future__ import annotations
import json
import csv
import os
import datetime
import logging
from typing import Any, Dict, Iterable, List

from src.config import BASELINE_TIME, OUTPUT_DIR
from src.diagnostics import diagnostics_to_dicts
from src.scheduler import ScheduleResult, ScheduledTask

logger = logging.getLogger(__name__)


def _mins_to_datetime(mins: int) -> str:
    """将分钟偏移量还原为 DateTime 字符串"""
    base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
    dt = base + datetime.timedelta(minutes=mins)
    return dt.strftime("%Y-%m-%d %H:%M")


def ensure_output_dir():
    """确保输出目录存在"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def export_schedule_json(result: ScheduleResult, path: str):
    """输出结构化 JSON 排程结果"""
    ensure_output_dir()
    data = {
        "status": result.status,
        "phase1_tardiness_score": result.phase1_score,
        "phase2_setup_score": result.phase2_score,
        "machines": {},
        "diagnostics": diagnostics_to_dicts(getattr(result, "diagnostics", [])),
    }

    for mid, tasks in result.machine_sequences.items():
        machine_data = []
        for t in sorted(tasks, key=lambda x: x.start_mins):
            machine_data.append({
                "sequence": t.sequence_index,
                "order_id": t.order.order_id,
                "product_type": t.order.product_type,
                "start_time": _mins_to_datetime(t.start_mins),
                "end_time": _mins_to_datetime(t.end_mins),
                "start_mins": t.start_mins,
                "end_mins": t.end_mins,
                "duration_mins": t.end_mins - t.start_mins,
                "setup_time_mins": t.setup_time,
                "scrap_kg": round(t.scrap_kg, 2),
                "target_width": t.order.target_width,
                "target_thickness": t.order.target_thickness,
                "due_date": _mins_to_datetime(t.order.due_date_mins),
                "is_late": t.end_mins > t.order.due_date_mins,
                "tardiness_mins": max(0, t.end_mins - t.order.due_date_mins),
            })
        data["machines"][mid] = machine_data

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("排程结果已导出: %s", path)


def export_schedule_csv(result: ScheduleResult, path: str):
    """输出扁平化 CSV 排程结果"""
    ensure_output_dir()
    fieldnames = [
        "machine_id", "sequence", "order_id", "product_type",
        "start_time", "end_time", "duration_mins", "setup_time_mins",
        "scrap_kg", "target_width", "target_thickness",
        "customer_class", "order_class", "due_date", "tardiness_mins",
    ]
    rows = []
    for t in sorted(result.tasks, key=lambda x: (x.machine.machine_id, x.start_mins)):
        rows.append({
            "machine_id": t.machine.machine_id,
            "sequence": t.sequence_index,
            "order_id": t.order.order_id,
            "product_type": t.order.product_type,
            "start_time": _mins_to_datetime(t.start_mins),
            "end_time": _mins_to_datetime(t.end_mins),
            "duration_mins": t.end_mins - t.start_mins,
            "setup_time_mins": t.setup_time,
            "scrap_kg": round(t.scrap_kg, 2),
            "target_width": t.order.target_width,
            "target_thickness": t.order.target_thickness,
            "customer_class": t.order.customer_class,
            "order_class": t.order.order_class,
            "due_date": _mins_to_datetime(t.order.due_date_mins),
            "tardiness_mins": max(0, t.end_mins - t.order.due_date_mins),
        })

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("CSV 排程结果已导出: %s", path)


def export_material_correction(result: ScheduleResult, path: str):
    """输出投料修正通知清单"""
    ensure_output_dir()
    fieldnames = [
        "order_id", "product_type", "machine_id",
        "net_weight_kg", "scrap_kg", "actual_material_required_kg",
    ]
    rows = []
    for t in sorted(result.tasks, key=lambda x: x.order.order_id):
        rows.append({
            "order_id": t.order.order_id,
            "product_type": t.order.product_type,
            "machine_id": t.machine.machine_id,
            "net_weight_kg": t.order.total_quantity_kg,
            "scrap_kg": round(t.scrap_kg, 2),
            "actual_material_required_kg": round(
                t.order.total_quantity_kg + t.scrap_kg, 2),
        })

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("投料修正通知已导出: %s", path)


def _format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours} 小时 {mins} 分钟" if mins else f"{hours} 小时"


def _diagnostic_dicts(result: ScheduleResult) -> List[Dict[str, Any]]:
    return diagnostics_to_dicts(getattr(result, "diagnostics", []))


def _is_order_exception(diagnostic: Dict[str, Any]) -> bool:
    if diagnostic.get("entity_type") != "order":
        return False
    category = diagnostic.get("category")
    code = diagnostic.get("code") or ""
    return (
        category in {"eligibility", "lateness", "material", "validation"}
        or code.startswith("eligibility.")
        or code.startswith("lateness.")
        or code.startswith("material.")
    )


def _is_global_diagnostic(diagnostic: Dict[str, Any]) -> bool:
    return not _is_order_exception(diagnostic)


def _evidence_text(evidence: Iterable[Dict[str, Any]], limit: int = 5) -> str:
    items = []
    for item in evidence or []:
        actual = item.get("actual")
        if actual is None or actual == "":
            continue
        metric = item.get("metric") or "evidence"
        unit = f" {item.get('unit')}" if item.get("unit") else ""
        entity = f" ({item.get('entity_id')})" if item.get("entity_id") else ""
        items.append(f"{metric}={actual}{unit}{entity}")
        if len(items) >= limit:
            break
    return "；".join(items) if items else "-"


def _recommendation_text(recommendations: Iterable[Dict[str, str]], limit: int = 3) -> str:
    labels = [item.get("label") for item in recommendations or [] if item.get("label")]
    return "；".join(labels[:limit]) if labels else "复核订单、机台和规则配置后重新排程"


def _diagnostic_table(diagnostics: List[Dict[str, Any]], limit: int = 20) -> List[str]:
    if not diagnostics:
        return ["当前无该类诊断。"]
    lines = [
        "| 对象 | 类型 | 严重度 | 根因 | 关键证据 | 建议 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in diagnostics[:limit]:
        entity = item.get("display_title") or item.get("entity_id") or "-"
        code = item.get("code") or "-"
        severity = item.get("severity") or "-"
        root = (item.get("root_cause") or "-").replace("\n", " ")
        evidence = _evidence_text(item.get("evidence") or [])
        recommendation = _recommendation_text(item.get("recommendations") or [])
        lines.append(f"| {entity} | `{code}` | {severity} | {root} | {evidence} | {recommendation} |")
    if len(diagnostics) > limit:
        lines.append(f"\n> 另有 {len(diagnostics) - limit} 条诊断未展开，请查看 JSON 结果。")
    return lines


def _machine_summary_table(result: ScheduleResult) -> List[str]:
    if not result.machine_sequences:
        return ["当前无机台排程结果。"]

    lines = [
        "| 机台 | 订单数 | 生产时间 | 换产时间 | 逾期订单 | 时间跨度利用率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for machine_id in sorted(result.machine_sequences.keys()):
        tasks = sorted(result.machine_sequences[machine_id], key=lambda t: t.start_mins)
        prod_mins = sum(t.end_mins - t.start_mins for t in tasks)
        setup_mins = sum(t.setup_time for t in tasks)
        late_count = sum(1 for t in tasks if t.end_mins > t.order.due_date_mins)
        span = max(t.end_mins for t in tasks) - min(
            max(0, t.start_mins - t.setup_time) for t in tasks
        )
        utilization = (prod_mins / span * 100) if span > 0 else 0
        lines.append(
            f"| {machine_id} | {len(tasks)} | {_format_duration(prod_mins)} | "
            f"{_format_duration(setup_mins)} | {late_count} | {utilization:.1f}% |"
        )
    return lines


def export_schedule_report(result: ScheduleResult, path: str):
    """输出面向业务复盘的 Markdown 排程报告。"""
    ensure_output_dir()
    diagnostics = _diagnostic_dicts(result)
    order_exceptions = [item for item in diagnostics if _is_order_exception(item)]
    global_diagnostics = [item for item in diagnostics if _is_global_diagnostic(item)]
    late_tasks = [t for t in result.tasks if t.end_mins > t.order.due_date_mins]
    setup_mins = sum(t.setup_time for t in result.tasks)
    prod_mins = sum(t.end_mins - t.start_mins for t in result.tasks)
    scrap_kg = sum(t.scrap_kg for t in result.tasks)

    lines = [
        "# 吹膜机排程报告",
        "",
        "## 排程概览",
        "",
        f"- 求解状态：{result.status}",
        f"- 已排订单：{len(result.tasks)}",
        f"- 使用机台：{len(result.machine_sequences)}",
        f"- 逾期订单：{len(late_tasks)}",
        f"- 总生产时间：{_format_duration(prod_mins)}",
        f"- 总换产时间：{_format_duration(setup_mins)}",
        f"- 总废料：{scrap_kg:.1f} kg",
        f"- 诊断总数：{len(diagnostics)}",
        "",
        "## 订单异常根因",
        "",
        "本节只列无法排程、延期、原料不可用等订单级问题，适合作为 Dashboard 的同源解释。",
        "",
        *_diagnostic_table(order_exceptions),
        "",
        "## 全局排程根因分析",
        "",
        "本节汇总机台负载、低利用、未使用、换产负担、校验和其他全局诊断，用于解释整厂排程质量。",
        "",
        *_diagnostic_table(global_diagnostics),
        "",
        "## 机台排程摘要",
        "",
        *_machine_summary_table(result),
        "",
        "## 后续指导方向",
        "",
        "- 先处理 `critical` 和 `warning` 订单异常，再重新运行排程。",
        "- 对全局机台问题，优先检查高负载机台、未使用机台和换产占比较高的机台。",
        "- 若空档或低利用较多，结合甘特图查看维护、停机、原料齐套和订单分配关系。",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info("Markdown 排程报告已导出: %s", path)


def print_ascii_gantt(result: ScheduleResult):
    """控制台 ASCII 甘特图概览"""
    if not result.tasks:
        print("  [无排程结果]")
        return

    # 找到全局时间范围
    min_t = min(t.start_mins for t in result.tasks)
    max_t = max(t.end_mins for t in result.tasks)
    span = max_t - min_t if max_t > min_t else 1
    bar_width = 60

    print("\n" + "=" * 80)
    print("  ASCII 甘特图（按机台分组）")
    print("=" * 80)

    for mid in sorted(result.machine_sequences.keys()):
        tasks = sorted(result.machine_sequences[mid], key=lambda x: x.start_mins)
        print(f"\n  [{mid}]")
        for t in tasks:
            s_pos = int((t.start_mins - min_t) / span * bar_width)
            e_pos = int((t.end_mins - min_t) / span * bar_width)
            e_pos = max(e_pos, s_pos + 1)
            bar = " " * s_pos + "█" * (e_pos - s_pos)
            late = " [LATE]" if t.end_mins > t.order.due_date_mins else ""
            print(f"    {t.order.order_id:>8s} |{bar:<{bar_width}s}| "
                  f"{_mins_to_datetime(t.start_mins)}-{_mins_to_datetime(t.end_mins)}{late}")

    print("\n" + "=" * 80)


def print_summary_stats(result: ScheduleResult):
    """输出全厂汇总统计"""
    if not result.tasks:
        print("  [无排程数据]")
        return

    total_setup = sum(t.setup_time for t in result.tasks)
    total_scrap = sum(t.scrap_kg for t in result.tasks)
    total_prod = sum(t.end_mins - t.start_mins for t in result.tasks)
    late_tasks = [t for t in result.tasks if t.end_mins > t.order.due_date_mins]
    vip_late = [t for t in late_tasks
                if t.order.customer_class == "VIP" or t.order.order_class == "URGENT"]

    print("\n" + "─" * 60)
    print("  全厂排程汇总统计")
    print("─" * 60)
    print(f"  求解状态          : {result.status}")
    print(f"  已排订单数        : {len(result.tasks)}")
    print(f"  使用机台数        : {len(result.machine_sequences)}")
    print(f"  总换产时间(min)   : {total_setup}")
    print(f"  总废料重量(kg)    : {total_scrap:.1f}")
    print(f"  总生产时间(min)   : {total_prod}")
    print(f"  逾期订单数        : {len(late_tasks)}")
    print(f"  VIP/URGENT 逾期   : {len(vip_late)}")

    # 机台利用率
    print("\n  机台利用率:")
    for mid in sorted(result.machine_sequences.keys()):
        tasks = result.machine_sequences[mid]
        if not tasks:
            continue
        prod_time = sum(t.end_mins - t.start_mins for t in tasks)
        span = max(t.end_mins for t in tasks) - min(t.start_mins for t in tasks)
        util = (prod_time / span * 100) if span > 0 else 0
        print(f"    {mid}: {util:.1f}% ({len(tasks)} 订单, {prod_time} min)")

    print("─" * 60)
