"""
医疗PE薄膜吹膜机 APS 智能排程系统 — 集成执行入口

使用流程:
    python main.py                    # 排程 + 文件输出
    python main.py --init-db          # 初始化数据库（建表）
    python main.py --save-db          # 排程 + 文件输出 + 入库
    python main.py --init-db --save-db  # 建表 + 排程 + 入库
"""

from __future__ import annotations
import sys
import os
import logging
import argparse

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import (
    INPUT_EXCEL_PATH,
    OUTPUT_SCHEDULE_JSON,
    OUTPUT_SCHEDULE_CSV,
    OUTPUT_MATERIAL_CORRECTION_CSV,
    OUTPUT_SCHEDULE_REPORT_MD,
)
from src.data_ingestion import BlownFilmDataIngestionPipeline
from src.scheduler import AdvancedMedicalAPS
from src.output_formatter import (
    export_schedule_json,
    export_schedule_csv,
    export_material_correction,
    export_schedule_report,
    print_ascii_gantt,
    print_summary_stats,
)

# ─── 日志配置 ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("APS-Main")


def main():
    parser = argparse.ArgumentParser(description="医疗PE薄膜吹膜机 APS 排程系统")
    parser.add_argument("--input", default=INPUT_EXCEL_PATH,
                        help="输入 Excel 文件路径")
    parser.add_argument("--init-db", action="store_true",
                        help="初始化数据库（创建 15 张表）")
    parser.add_argument("--save-db", action="store_true",
                        help="排程结果入库")
    parser.add_argument("--source", choices=["excel", "db"], default="excel",
                        help="Scheduler input source")
    parser.add_argument("--triggered-by", default=None,
                        help="HTTP/API user that triggered this schedule run")
    args = parser.parse_args()

    excel_path = args.input
    logger.info("=" * 60)
    logger.info("  医疗PE薄膜吹膜机 APS 智能排程系统 v2.0")
    logger.info("=" * 60)

    # ─── Step 0: 数据库初始化（可选） ───
    if args.init_db:
        from src.database import DatabaseManager
        logger.info("Step 0: 初始化数据库 Schema")
        with DatabaseManager() as db:
            db.init_schema()
        logger.info("  15 张表创建完成")

    # ─── Step 1: 数据加载与清洗 ───
    logger.info("Step 1: 加载数据 — %s", excel_path)
    pipeline = BlownFilmDataIngestionPipeline()
    if args.source == "db":
        from src.database import DatabaseManager
        logger.info("Step 1: 从数据库加载 UI 配置后的排程输入")
        _, _, _, fallback_setup_mgr = pipeline.load_from_excel(excel_path)
        with DatabaseManager() as db:
            machines, orders, recipes_map, setup_mgr = db.load_master_data(
                fallback_setup_mgr=fallback_setup_mgr
            )
    else:
        machines, orders, recipes_map, setup_mgr = pipeline.load_from_excel(excel_path)
    logger.info("  机台: %d, 订单: %d, 配方: %d", len(machines), len(orders), len(recipes_map))

    # ─── Step 1.5: 主数据入库（可选） ───
    if args.save_db and args.source == "excel":
        from src.database import DatabaseManager
        logger.info("Step 1.5: 主数据导入数据库")
        with DatabaseManager() as db:
            db.save_master_data(machines, orders, recipes_map, setup_mgr)

    # ─── Step 2: 构建排程引擎并求解 ───
    logger.info("Step 2: 启动两阶段分层求解引擎")
    aps = AdvancedMedicalAPS(setup_mgr)
    result = aps.run(orders, machines)

    # ─── Step 3: 输出结果 ───
    logger.info("Step 3: 导出排程结果")
    export_schedule_report(result, OUTPUT_SCHEDULE_REPORT_MD)
    if result.status in ("OPTIMAL", "FEASIBLE"):
        export_schedule_json(result, OUTPUT_SCHEDULE_JSON)
        export_schedule_csv(result, OUTPUT_SCHEDULE_CSV)
        export_material_correction(result, OUTPUT_MATERIAL_CORRECTION_CSV)
        print_ascii_gantt(result)
        print_summary_stats(result)
        logger.info("排程完成！结果已导出至 output/ 目录")

        # ─── Step 4: 排程结果入库（可选） ───
        if args.save_db:
            from src.database import DatabaseManager
            logger.info("Step 4: 排程结果持久化入库")
            with DatabaseManager() as db:
                run_id = db.save_schedule_result(result, triggered_by=args.triggered_by)
                logger.info("  入库完成: run_id=%d", run_id)
    else:
        logger.error("排程失败: %s — 请检查数据约束是否过紧", result.status)
        for err in getattr(result, "validation_errors", [])[:20]:
            logger.error("  - %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
