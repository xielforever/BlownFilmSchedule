"""
APS 排程系统 PostgreSQL 数据库访问层

提供连接管理、DDL 初始化、主数据导入和排程结果持久化。
"""

from __future__ import annotations
import os
import datetime
import json
import logging
from typing import List, Optional

import psycopg2
import psycopg2.extras

from src.config import DATABASE_CONFIG, BASELINE_TIME
from src.scheduler import ScheduleResult

logger = logging.getLogger(__name__)

DDL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "init_schema.sql")


class DatabaseManager:
    """PostgreSQL 数据库管理器"""

    def __init__(self, config: dict = None):
        self.config = config or DATABASE_CONFIG
        self.conn = None

    def connect(self):
        """建立数据库连接"""
        self.conn = psycopg2.connect(
            host=self.config["host"],
            port=self.config["port"],
            dbname=self.config["database"],
            user=self.config["username"],
            password=self.config["password"],
        )
        self.conn.autocommit = False
        logger.info("数据库连接成功: %s:%s/%s",
                     self.config["host"], self.config["port"], self.config["database"])

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    # ─── DDL 初始化 ───────────────────────────────────────

    def init_schema(self):
        """执行 DDL 建表脚本"""
        with open(DDL_PATH, "r", encoding="utf-8") as f:
            sql = f.read()
        with self.conn.cursor() as cur:
            cur.execute(sql)
        self.conn.commit()
        logger.info("数据库 Schema 初始化完成（15 张表）")

    # ─── 主数据导入 ───────────────────────────────────────

    def save_master_data(self, machines, orders, recipes_map, setup_mgr):
        """将从 Excel 解析的主数据批量导入数据库"""
        with self.conn.cursor() as cur:
            self._save_raw_materials(cur, recipes_map, setup_mgr)
            self._save_products(cur, recipes_map)
            self._save_recipes(cur, recipes_map)
            self._save_customers(cur, orders)
            self._save_machines(cur, machines)
            self._save_orders(cur, orders)
            self._save_setup_matrices(cur, setup_mgr)
        self.conn.commit()
        logger.info("主数据导入完成")

    def _save_raw_materials(self, cur, recipes_map, setup_mgr):
        """导入原料牌号"""
        grades = set()
        for materials in recipes_map.values():
            grades.update(materials)
        # 从机台初始挂料和换产矩阵中收集更多牌号
        for key in setup_mgr.material_switch_matrix:
            grades.add(key[0])
            grades.add(key[1])

        for g in grades:
            is_special = "Special" in g
            category = "SPECIAL" if is_special else (
                "MEDICAL_HIGH" if "Borealis" in g else (
                "PACKAGING" if ("Dow" in g or "Bird" in g) else "MEDICAL_STD"
            ))
            cur.execute("""
                INSERT INTO raw_materials (material_grade, material_category, is_special)
                VALUES (%s, %s, %s)
                ON CONFLICT (material_grade) DO NOTHING
            """, (g, category, is_special))

    def _save_products(self, cur, recipes_map):
        """导入产品类型"""
        for prod_type, mats in recipes_map.items():
            layer_type = "5层共挤" if len(mats) == 5 else "3层共挤"
            cur.execute("""
                INSERT INTO products (product_type, layer_type)
                VALUES (%s, %s)
                ON CONFLICT (product_type) DO NOTHING
            """, (prod_type, layer_type))

    def _save_recipes(self, cur, recipes_map):
        """导入工艺配方"""
        layer_labels = ["A", "B", "C", "D", "E"]
        for prod_type, materials in recipes_map.items():
            for i, mat in enumerate(materials):
                layer = layer_labels[i] if i < len(layer_labels) else str(i)
                cur.execute("""
                    INSERT INTO recipes (recipe_id, product_type, layer, material_grade)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_type, layer) DO NOTHING
                """, (f"REC-{prod_type[:3].upper()}-{i:02d}", prod_type, layer, mat))

    def _save_customers(self, cur, orders):
        """从订单中提取并去重导入客户"""
        seen = set()
        for o in orders:
            cid = o.customer_class  # 暂用 VIP/STANDARD 作为客户ID
            if cid not in seen:
                seen.add(cid)
                cur.execute("""
                    INSERT INTO customers (customer_id, customer_name, customer_class)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (customer_id) DO NOTHING
                """, (cid, f"{cid} 客户群", cid))

    def _save_machines(self, cur, machines):
        """导入机台主数据和初始状态"""
        for m in machines:
            cur.execute("""
                INSERT INTO machines (machine_id, name, cleanroom_level, layer_structure,
                    die_diameter_mm, min_width, max_width, min_thickness, max_thickness,
                    hourly_output_kg, max_slitting_lanes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (machine_id) DO UPDATE SET
                    name=EXCLUDED.name, updated_at=NOW()
            """, (m.machine_id, m.name, m.cleanroom_level, m.layer_structure,
                  m.die_diameter_mm, m.min_width, m.max_width, m.min_thickness,
                  m.max_thickness, m.hourly_output_kg, m.max_slitting_lanes))
            # 初始状态
            cur.execute("""
                INSERT INTO machine_current_state
                    (machine_id, current_material_lanes, current_width, current_thickness)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (machine_id) DO UPDATE SET
                    current_material_lanes=EXCLUDED.current_material_lanes,
                    current_width=EXCLUDED.current_width,
                    current_thickness=EXCLUDED.current_thickness,
                    updated_at=NOW()
            """, (m.machine_id, m.initial_material_lanes,
                  m.initial_width, m.initial_thickness))
            # 维保日历
            for fw in m.forbidden_calendar:
                base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
                st = base + datetime.timedelta(minutes=fw.start_mins)
                et = base + datetime.timedelta(minutes=fw.end_mins)
                cur.execute("""
                    INSERT INTO machine_maintenance_calendar
                        (machine_id, start_time, end_time, maintenance_type, reason, is_recurring)
                    VALUES (%s, %s, %s, 'GMP_CLEANING', %s, TRUE)
                """, (m.machine_id, st, et, fw.reason))

    def _save_orders(self, cur, orders):
        """导入生产订单"""
        base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
        for o in orders:
            order_date = base + datetime.timedelta(minutes=o.order_date_mins) if o.order_date_mins else None
            due_date = base + datetime.timedelta(minutes=o.due_date_mins)
            mat_avail = base + datetime.timedelta(minutes=o.material_available_mins) if o.material_available_mins > 0 else None
            cur.execute("""
                INSERT INTO production_orders
                    (order_id, customer_id, product_type, target_width, target_thickness,
                     total_quantity_kg, cleanroom_req, order_class, corona_req,
                     core_size_inch, order_date, due_date, material_available_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (order_id) DO NOTHING
            """, (o.order_id, o.customer_class, o.product_type,
                  o.target_width, o.target_thickness, o.total_quantity_kg,
                  o.cleanroom_req, o.order_class, o.corona_req,
                  o.core_size_inch, order_date, due_date, mat_avail))

    def _save_setup_matrices(self, cur, setup_mgr):
        """导入换产矩阵"""
        for (f, t), mins in setup_mgr.material_switch_matrix.items():
            cur.execute("""
                INSERT INTO material_switch_matrix (from_material, to_material, switch_time_mins)
                VALUES (%s, %s, %s)
                ON CONFLICT (from_material, to_material) DO NOTHING
            """, (f, t, mins))
        for (fc, tc), mins in setup_mgr.gmp_clearance_matrix.items():
            cur.execute("""
                INSERT INTO gmp_clearance_matrix (from_order_class, to_order_class, clearance_time_mins)
                VALUES (%s, %s, %s)
                ON CONFLICT (from_order_class, to_order_class) DO NOTHING
            """, (fc, tc, mins))

    # ─── 排程结果持久化 ───────────────────────────────────

    def save_schedule_result(self, result: ScheduleResult):
        """保存排程结果到数据库"""
        base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")

        with self.conn.cursor() as cur:
            # 将之前的排程标记为非活跃
            cur.execute("UPDATE schedule_runs SET is_active = FALSE WHERE is_active = TRUE")

            total_setup = sum(t.setup_time for t in result.tasks)
            total_scrap = sum(t.scrap_kg for t in result.tasks)
            late = [t for t in result.tasks if t.end_mins > t.order.due_date_mins]
            vip_late = [t for t in late
                        if t.order.customer_class == "VIP" or t.order.order_class == "URGENT"]

            cur.execute("""
                INSERT INTO schedule_runs
                    (baseline_time, status, total_orders, total_machines_used,
                     phase1_tardiness_score, phase2_setup_score,
                     total_setup_time_mins, total_scrap_kg,
                     total_late_orders, vip_late_orders, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                RETURNING run_id
            """, (base, result.status, len(result.tasks),
                  len(result.machine_sequences),
                  result.phase1_score, result.phase2_score,
                  total_setup, total_scrap,
                  len(late), len(vip_late)))
            run_id = cur.fetchone()[0]

            # 保存任务明细
            for mid in sorted(result.machine_sequences.keys()):
                tasks = sorted(result.machine_sequences[mid], key=lambda x: x.start_mins)
                prev_oid = None
                for t in tasks:
                    st = base + datetime.timedelta(minutes=t.start_mins)
                    et = base + datetime.timedelta(minutes=t.end_mins)
                    setup_st = base + datetime.timedelta(minutes=max(0, t.start_mins - t.setup_time))

                    cur.execute("""
                        INSERT INTO scheduled_tasks
                            (run_id, order_id, machine_id, sequence_index,
                             setup_start_time, start_time, end_time,
                             start_mins, end_mins, duration_mins, setup_time_mins,
                             scrap_kg, net_weight_kg, actual_material_required_kg,
                             is_late, tardiness_mins, prev_order_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (run_id, t.order.order_id, t.machine.machine_id,
                          t.sequence_index, setup_st, st, et,
                          t.start_mins, t.end_mins,
                          t.end_mins - t.start_mins, t.setup_time,
                          t.scrap_kg, t.order.total_quantity_kg,
                          t.order.total_quantity_kg + t.scrap_kg,
                          t.end_mins > t.order.due_date_mins,
                          max(0, t.end_mins - t.order.due_date_mins),
                          prev_oid))
                    prev_oid = t.order.order_id

            # 更新订单状态
            for t in result.tasks:
                cur.execute("""
                    UPDATE production_orders SET status='SCHEDULED', updated_at=NOW()
                    WHERE order_id=%s AND status='PENDING'
                """, (t.order.order_id,))

            # 更新机台当前状态（最后一个订单的末态）
            for mid, tasks in result.machine_sequences.items():
                last = sorted(tasks, key=lambda x: x.end_mins)[-1]
                o = last.order
                cur.execute("""
                    UPDATE machine_current_state SET
                        current_material_lanes=%s, current_width=%s,
                        current_thickness=%s, current_corona=%s,
                        current_core_size=%s, last_order_id=%s, updated_at=NOW()
                    WHERE machine_id=%s
                """, (o.recipe_materials, o.target_width, o.target_thickness,
                      o.corona_req, o.core_size_inch, o.order_id, mid))

        self.conn.commit()
        logger.info("排程结果已入库: run_id=%d, %d 个任务", run_id, len(result.tasks))
        return run_id
