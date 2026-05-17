"""
APS 排程系统结果输出与可视化模块

提供 JSON/CSV 导出、投料修正通知单、ASCII 甘特图、统计摘要。
"""

from __future__ import annotations
import json
import csv
import os
import datetime
import logging
from typing import List, Dict

from src.config import BASELINE_TIME, OUTPUT_DIR
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
