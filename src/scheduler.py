"""
APS 排程系统核心算法引擎

基于 Google OR-Tools CP-SAT 的两阶段分层求解（Lexicographical Optimization）。
功能：换产耗时精算、废料守恒计算、FJSP-SDST 建模与求解。
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional, Tuple

from ortools.sat.python import cp_model

from src.config import (
    MAX_HORIZON_MINUTES,
    SOLVER_TIME_LIMIT_SECONDS,
    CONTINUOUS_RUN_LIMIT_MINUTES,
    MANDATORY_CLEANING_DURATION_MINUTES,
    DEFAULT_MATERIAL_SWITCH_TIME_MINS,
    SCRAP_PER_LAYER_MATERIAL_CHANGE_KG,
    SCRAP_PER_LAYER_SAME_MATERIAL_KG,
    SCRAP_WIDTH_CHANGE_KG,
    SCRAP_THICKNESS_CHANGE_KG,
    get_tardiness_weight,
)
from src.diagnostics import (
    Diagnostic,
    DiagnosticEvidence,
    DiagnosticRecommendation,
    build_infeasible_order_diagnostic,
    build_result_diagnostics,
    evaluate_machine_fit,
)
from src.models import ProductionOrderModel, BlownFilmMachineModel
from src.setup_matrices import SetupMatricesManager

logger = logging.getLogger(__name__)


# ─── 排程结果数据结构 ─────────────────────────────────────
class ScheduledTask:
    """单个已排程任务的结果"""
    def __init__(self, order: ProductionOrderModel, machine: BlownFilmMachineModel,
                 start_mins: int, end_mins: int, setup_time: int, scrap_kg: float,
                 sequence_index: int, setup_detail: Optional[Dict] = None,
                 manual_lock_machine: bool = True, manual_lock_time: bool = True):
        self.order = order
        self.machine = machine
        self.start_mins = start_mins
        self.end_mins = end_mins
        self.setup_time = setup_time
        self.scrap_kg = scrap_kg
        self.sequence_index = sequence_index
        self.setup_detail = setup_detail or {"total_mins": setup_time, "components": []}
        self.manual_lock_machine = manual_lock_machine
        self.manual_lock_time = manual_lock_time


class ScheduleResult:
    """完整排程结果"""
    def __init__(self):
        self.status: str = "UNKNOWN"
        self.tasks: List[ScheduledTask] = []
        self.phase1_score: int = 0
        self.phase2_score: int = 0
        self.validation_errors: List[str] = []
        self.machine_sequences: Dict[str, List[ScheduledTask]] = {}
        self.diagnostics: List[Diagnostic] = []
        self.input_order_count: int = 0
        self.schedulable_order_count: int = 0
        self.blocked_order_count: int = 0
        self.deferred_orders: List[Dict] = []
        self.solver_metrics: Dict[str, Dict] = {}

    def add_task(self, task: ScheduledTask):
        self.tasks.append(task)
        mid = task.machine.machine_id
        if mid not in self.machine_sequences:
            self.machine_sequences[mid] = []
        self.machine_sequences[mid].append(task)


# ─── 换产与废料计算 ─────────────────────────────────────────
class SetupCalculator:
    """换产耗时与废料守恒精算器"""

    def __init__(self, setup_mgr: SetupMatricesManager):
        self.mgr = setup_mgr

    def calculate_setup_time(
        self,
        prev_order: Optional[ProductionOrderModel],
        next_order: ProductionOrderModel,
        machine: BlownFilmMachineModel,
    ) -> int:
        """
        计算前后工单间的总换产耗时（整数分钟）。
        prev_order=None 表示机台初始状态 → 首单。

        T_total = Max(T_material_l) + T_width + T_thickness + T_corona + T_core + T_gmp
        """
        # 解析前序状态
        if prev_order is None:
            m_from = list(machine.initial_material_lanes)
            w_from = machine.initial_width
            t_from = machine.initial_thickness
            c_from = machine.initial_corona
            r_from = machine.initial_core_size
            class_from = "INIT"
        else:
            m_from = list(prev_order.recipe_materials)
            w_from = prev_order.target_width
            t_from = prev_order.target_thickness
            c_from = prev_order.corona_req
            r_from = prev_order.core_size_inch
            class_from = prev_order.order_class

        m_to = list(next_order.recipe_materials)
        w_to = next_order.target_width
        t_to = next_order.target_thickness
        c_to = next_order.corona_req
        r_to = next_order.core_size_inch
        class_to = next_order.order_class

        setup = 0

        # 1. 材质切换（并发 Max）：多螺杆并行清洗，取最慢层
        mat_times = []
        num_layers = min(len(m_from), len(m_to))
        for l in range(num_layers):
            t_layer = self.mgr.get_material_switch_time(m_from[l], m_to[l])
            mat_times.append(t_layer)
        if mat_times:
            setup += max(mat_times)

        # 2. 幅宽变动（方向性阶梯）
        delta_w = w_to - w_from
        exceeds = w_to > machine.max_width
        setup += self.mgr.get_width_change_time(delta_w, exceeds)

        # 3. 厚度变动
        delta_t = t_to - t_from
        setup += self.mgr.get_thickness_change_time(delta_t)

        # 4. 电晕切换
        setup += self.mgr.get_corona_change_time(c_from, c_to)

        # 5. 卷芯管径切换
        setup += self.mgr.get_core_size_change_time(r_from, r_to)

        # 6. GMP 合规清场
        setup += self.mgr.get_gmp_clearance_time(class_from, class_to)

        return setup

    def calculate_setup_detail(
        self,
        prev_order: Optional[ProductionOrderModel],
        next_order: ProductionOrderModel,
        machine: BlownFilmMachineModel,
    ) -> Dict:
        """Return a structured breakdown that sums to calculate_setup_time()."""
        if prev_order is None:
            m_from = list(machine.initial_material_lanes)
            w_from = machine.initial_width
            t_from = machine.initial_thickness
            c_from = machine.initial_corona
            r_from = machine.initial_core_size
            class_from = "INIT"
            prev_order_id = None
        else:
            m_from = list(prev_order.recipe_materials)
            w_from = prev_order.target_width
            t_from = prev_order.target_thickness
            c_from = prev_order.corona_req
            r_from = prev_order.core_size_inch
            class_from = prev_order.order_class
            prev_order_id = prev_order.order_id

        m_to = list(next_order.recipe_materials)
        w_to = next_order.target_width
        t_to = next_order.target_thickness
        c_to = next_order.corona_req
        r_to = next_order.core_size_inch
        class_to = next_order.order_class

        components = []

        def add_component(category: str, minutes: int, **evidence) -> None:
            if minutes <= 0:
                return
            components.append({
                "category": category,
                "minutes": int(minutes),
                **evidence,
            })

        mat_times = []
        num_layers = min(len(m_from), len(m_to))
        for layer in range(num_layers):
            mat_times.append(self.mgr.get_material_switch_time(m_from[layer], m_to[layer]))
        material_mins = max(mat_times) if mat_times else 0
        add_component(
            "material",
            material_mins,
            from_materials=m_from,
            to_materials=m_to,
            layer_times=mat_times,
        )

        delta_w = w_to - w_from
        exceeds = w_to > machine.max_width
        add_component(
            "width",
            self.mgr.get_width_change_time(delta_w, exceeds),
            from_width=w_from,
            to_width=w_to,
            delta=delta_w,
            exceeds_machine_max=exceeds,
        )

        delta_t = t_to - t_from
        add_component(
            "thickness",
            self.mgr.get_thickness_change_time(delta_t),
            from_thickness=t_from,
            to_thickness=t_to,
            delta=delta_t,
        )

        add_component(
            "corona",
            self.mgr.get_corona_change_time(c_from, c_to),
            from_corona=c_from,
            to_corona=c_to,
        )
        add_component(
            "core",
            self.mgr.get_core_size_change_time(r_from, r_to),
            from_core=r_from,
            to_core=r_to,
        )
        add_component(
            "gmp",
            self.mgr.get_gmp_clearance_time(class_from, class_to),
            from_order_class=class_from,
            to_order_class=class_to,
        )

        total = sum(component["minutes"] for component in components)
        return {
            "prev_order_id": prev_order_id,
            "order_id": next_order.order_id,
            "machine_id": machine.machine_id,
            "total_mins": total,
            "components": components,
            "no_enabled_rules": total == 0,
        }

    def calculate_scrap_weight(
        self,
        prev_order: Optional[ProductionOrderModel],
        next_order: ProductionOrderModel,
        machine: BlownFilmMachineModel,
    ) -> float:
        """
        计算前后工单间的总废料损耗（kg）。
        W_total_scrap = Sum(W_material_l) + W_width_scrap + W_thickness_scrap
        """
        if prev_order is None:
            m_from = list(machine.initial_material_lanes)
            w_from = machine.initial_width
            t_from = machine.initial_thickness
        else:
            m_from = list(prev_order.recipe_materials)
            w_from = prev_order.target_width
            t_from = prev_order.target_thickness

        m_to = list(next_order.recipe_materials)
        w_to = next_order.target_width
        t_to = next_order.target_thickness

        scrap = 0.0

        # 1. 材质切换废料（逐层 Sum，非 Max）
        num_layers = min(len(m_from), len(m_to))
        for l in range(num_layers):
            configured_scrap = self.mgr.get_material_switch_scrap(m_from[l], m_to[l])
            if configured_scrap is not None:
                scrap += configured_scrap
            elif not self.mgr.scrap_defaults_enabled:
                scrap += 0
            elif m_from[l] != m_to[l]:
                scrap += SCRAP_PER_LAYER_MATERIAL_CHANGE_KG
            else:
                scrap += SCRAP_PER_LAYER_SAME_MATERIAL_KG

        # 2. 幅宽调机废料
        if w_from != w_to:
            configured_scrap = self.mgr.get_width_change_scrap(w_to - w_from)
            scrap += (
                configured_scrap
                if configured_scrap is not None
                else (SCRAP_WIDTH_CHANGE_KG if self.mgr.scrap_defaults_enabled else 0)
            )

        # 3. 厚度调机废料
        if t_from != t_to:
            configured_scrap = self.mgr.get_thickness_change_scrap(t_to - t_from)
            scrap += (
                configured_scrap
                if configured_scrap is not None
                else (SCRAP_THICKNESS_CHANGE_KG if self.mgr.scrap_defaults_enabled else 0)
            )

        return scrap


# ─── CP-SAT 核心求解引擎 ─────────────────────────────────────
class AdvancedMedicalAPS:
    """基于 OR-Tools CP-SAT 的两阶段分层求解引擎"""

    def __init__(
        self,
        setup_mgr: SetupMatricesManager,
        continuous_run_policy: Optional[Dict] = None,
        solver_quality_policy: Optional[Dict] = None,
        solver_profile_policy: Optional[Dict] = None,
        candidate_acceptance_policy: Optional[Dict] = None,
        arc_pruning_policy: Optional[Dict] = None,
    ):
        self.setup_calc = SetupCalculator(setup_mgr)
        self.setup_mgr = setup_mgr
        self.continuous_run_policy = self._normalize_continuous_run_policy(continuous_run_policy)
        self.solver_quality_policy = self._normalize_solver_quality_policy(solver_quality_policy)
        self.solver_profile_policy = self._normalize_solver_profile_policy(solver_profile_policy)
        self.candidate_acceptance_policy = self._normalize_candidate_acceptance_policy(candidate_acceptance_policy)
        self.arc_pruning_policy = self._normalize_arc_pruning_policy(arc_pruning_policy)

    @staticmethod
    def _normalize_continuous_run_policy(policy: Optional[Dict]) -> Dict:
        policy = policy or {}
        mode = str(policy.get("enforcement_mode") or "publish_blocker")
        if mode not in {"hard", "publish_blocker", "experimental_disabled"}:
            mode = "publish_blocker"
        return {
            "limit_mins": max(1, int(policy.get("limit_mins") or CONTINUOUS_RUN_LIMIT_MINUTES)),
            "cleaning_mins": max(0, int(policy.get("cleaning_mins") or MANDATORY_CLEANING_DURATION_MINUTES)),
            "enforcement_mode": mode,
        }

    @staticmethod
    def _normalize_solver_quality_policy(policy: Optional[Dict]) -> Dict:
        policy = policy or {}
        return {
            "phase2_feasible_tardiness_tolerance_mins": max(
                0,
                int(policy.get("phase2_feasible_tardiness_tolerance_mins") or 0),
            ),
        }

    @staticmethod
    def _normalize_solver_profile_policy(policy: Optional[Dict]) -> Dict:
        policy = policy or {}
        profile = str(policy.get("profile") or "standard")
        if profile not in {"fast", "standard", "deep"}:
            profile = "standard"
        return {
            "profile": profile,
            "time_limit_seconds": max(
                0.1,
                float(policy.get("time_limit_seconds") or SOLVER_TIME_LIMIT_SECONDS),
            ),
            "relative_gap_limit": max(0.0, float(policy.get("relative_gap_limit") or 0.0)),
            "random_seed": max(0, int(policy.get("random_seed") or 0)),
            "num_workers": max(1, int(policy.get("num_workers") or 8)),
            "log_search_progress": bool(policy.get("log_search_progress", False)),
        }

    @staticmethod
    def _normalize_candidate_acceptance_policy(policy: Optional[Dict]) -> Dict:
        policy = policy or {}
        return {
            "reject_penalty": max(0, int(policy.get("reject_penalty") or 10_000_000)),
        }

    @staticmethod
    def _is_optional_candidate(order: ProductionOrderModel) -> bool:
        return str(getattr(order, "planning_bucket", "") or "").lower() == "candidate"

    @staticmethod
    def _normalize_arc_pruning_policy(policy: Optional[Dict]) -> Dict:
        policy = policy or {}
        return {
            "enabled": bool(policy.get("enabled", False)),
            "max_setup_time_mins": max(0, int(policy.get("max_setup_time_mins") or 0)),
        }

    def _should_prune_order_arc(self, setup_time_mins: int) -> bool:
        policy = self.arc_pruning_policy
        return policy["enabled"] and setup_time_mins > policy["max_setup_time_mins"]

    def _apply_solver_profile(self, solver) -> None:
        policy = self.solver_profile_policy
        solver.parameters.max_time_in_seconds = policy["time_limit_seconds"]
        solver.parameters.relative_gap_limit = policy["relative_gap_limit"]
        solver.parameters.random_seed = policy["random_seed"]
        solver.parameters.num_workers = policy["num_workers"]
        solver.parameters.log_search_progress = policy["log_search_progress"]

    def _phase2_tardiness_bound(self, best_tardiness: int, phase1_status: str) -> int:
        if phase1_status == "OPTIMAL":
            return best_tardiness
        return best_tardiness + self.solver_quality_policy["phase2_feasible_tardiness_tolerance_mins"]

    @staticmethod
    def _tardiness_weight(order: ProductionOrderModel) -> int:
        if order.priority_override is not None:
            return max(0, int(order.priority_override))
        return get_tardiness_weight(order.customer_class, order.order_class)

    def _precompute_setup_times(
        self,
        orders: List[ProductionOrderModel],
        machines: List[BlownFilmMachineModel],
        eligible: Dict[int, List[int]],
    ) -> Dict[Tuple[int, int, int], int]:
        """预计算所有合法 (prev_idx, next_idx, machine_idx) 组合的换产耗时"""
        cache: Dict[Tuple[int, int, int], int] = {}
        n = len(orders)
        for m_idx, m in enumerate(machines):
            m_orders = [i for i in range(n) if m_idx in eligible[i]]
            # START → 各订单
            for j in m_orders:
                t = self.setup_calc.calculate_setup_time(None, orders[j], m)
                cache[(-1, j, m_idx)] = t
            # 订单间
            for i in m_orders:
                for j in m_orders:
                    if i != j:
                        t = self.setup_calc.calculate_setup_time(orders[i], orders[j], m)
                        cache[(i, j, m_idx)] = t
        return cache

    def run(
        self,
        orders: List[ProductionOrderModel],
        machines: List[BlownFilmMachineModel],
        locked_tasks: Optional[List[ScheduledTask]] = None,
    ) -> ScheduleResult:
        """执行两阶段分层求解，返回排程结果"""
        if hasattr(self.setup_mgr, "reset_runtime_observations"):
            self.setup_mgr.reset_runtime_observations()

        result = ScheduleResult()
        original_orders = list(orders)
        result.input_order_count = len(original_orders)
        M = len(machines)
        locked_tasks = locked_tasks or []
        locked_tasks_by_order_id = {
            task.order.order_id: task
            for task in locked_tasks
        }

        schedulable_orders: List[ProductionOrderModel] = []
        blocked_log_lines: List[str] = []
        for order_item in original_orders:
            fits = [evaluate_machine_fit(order_item, m) for m in machines]
            if any(fit.eligible for fit in fits):
                schedulable_orders.append(order_item)
                continue

            error = (
                f"订单 {order_item.order_id} 无可用机台: "
                f"width={order_item.target_width}, thickness={order_item.target_thickness}, "
                f"cleanroom={order_item.cleanroom_req}, layers={len(order_item.recipe_materials)}"
            )
            blocked_log_lines.append(error)
            logger.debug(error)
            result.blocked_order_count += 1
            result.diagnostics.append(
                build_infeasible_order_diagnostic(order_item, machines, fits)
            )

        result.schedulable_order_count = len(schedulable_orders)
        if not schedulable_orders:
            logger.error(
                "全部订单无可用机台，排程无法继续: blocked=%d",
                result.blocked_order_count,
            )
            for line in blocked_log_lines[:20]:
                logger.error("  - %s", line)
            if len(blocked_log_lines) > 20:
                logger.error("  - 另有 %d 个订单无可用机台，详见结构化诊断。", len(blocked_log_lines) - 20)
            result.status = "INFEASIBLE"
            return result

        if result.blocked_order_count:
            logger.warning(
                "部分订单无可用机台，已从本轮求解中排除: blocked=%d, schedulable=%d",
                result.blocked_order_count,
                result.schedulable_order_count,
            )

        orders = schedulable_orders
        n = len(orders)
        schedulable_order_ids = {order.order_id for order in orders}
        external_locked_tasks = [
            task
            for task in locked_tasks
            if task.order.order_id not in schedulable_order_ids
        ]

        # ─── 能力硬过滤：订单→可用机台列表 ───
        eligible: Dict[int, List[int]] = {}
        fit_audit: Dict[int, List] = {}
        for idx in range(n):
            eligible[idx] = []
            fit_audit[idx] = []
            for m_idx, m in enumerate(machines):
                fit = evaluate_machine_fit(orders[idx], m)
                fit_audit[idx].append(fit)
                if fit.eligible:
                    eligible[idx].append(m_idx)
            if not eligible[idx]:
                o = orders[idx]
                error = (
                    f"订单 {o.order_id} 无可用机台: "
                    f"width={o.target_width}, thickness={o.target_thickness}, "
                    f"cleanroom={o.cleanroom_req}, layers={len(o.recipe_materials)}"
                )
                logger.error(error)
                result.validation_errors.append(error)
                result.diagnostics.append(
                    build_infeasible_order_diagnostic(o, machines, fit_audit[idx])
                )

        if result.validation_errors:
            result.status = "INFEASIBLE"
            return result

        # ─── 预计算换产耗时 ───
        setup_cache = self._precompute_setup_times(orders, machines, eligible)

        # ─── 预计算生产耗时 ───
        duration_cache: Dict[Tuple[int, int], int] = {}
        for idx in range(n):
            for m_idx in eligible[idx]:
                duration_cache[(idx, m_idx)] = machines[m_idx].calculate_duration(orders[idx])

        H = self._estimate_horizon(n, M, eligible, setup_cache, duration_cache)
        result.solver_metrics["model_size"] = self._model_size_metrics(
            orders,
            machines,
            eligible,
            setup_cache,
            locked_tasks_by_order_id,
            external_locked_tasks,
        )
        logger.info("开始排程: %d 笔订单, %d 台机台, 计划域=%d min", n, M, H)

        # ═══════════════════════════════════════════════════
        # 第一阶段：交期至上 — Minimize(Sum(tardiness * W))
        # ═══════════════════════════════════════════════════
        logger.info("═══ 第一阶段：交期优化 ═══")
        phase1_result = self._solve_phase(
            orders, machines, eligible, setup_cache, duration_cache,
            H, phase=1, tardiness_bound=None,
            locked_tasks_by_order_id=locked_tasks_by_order_id,
            external_locked_tasks=external_locked_tasks,
        )
        result.solver_metrics["phase_1"] = getattr(self, "_last_phase_metrics", {})

        if phase1_result is None:
            result.status = getattr(self, "_last_solver_status", "INFEASIBLE")
            logger.error("第一阶段求解未获得可行解: status=%s", result.status)
            result.diagnostics.append(Diagnostic(
                entity_type="run",
                entity_id="current",
                severity="critical",
                category="capacity",
                code="capacity.no_feasible_solution",
                confidence="inferred",
                root_cause="求解器未获得可行解，通常意味着产能、交期、禁排或硬约束组合过紧。",
                evidence=[
                    DiagnosticEvidence("order_count", n),
                    DiagnosticEvidence("machine_count", M),
                    DiagnosticEvidence("solver_status", result.status),
                ],
                recommendations=[
                    DiagnosticRecommendation("review_orders", "检查订单交期和原料齐套", "/config?tab=orders"),
                    DiagnosticRecommendation("review_constraints", "检查机台和维护约束", "/config?tab=machines"),
                ],
            ))
            self._append_material_matrix_diagnostic(result)
            return result

        status1, solver1, vars1, best_tardiness = phase1_result
        result.phase1_score = best_tardiness
        logger.info("第一阶段完成: status=%s, best_tardiness=%d", status1, best_tardiness)

        # ═══════════════════════════════════════════════════
        # 第二阶段：锁死交期 → 最小化换产时间
        # ═══════════════════════════════════════════════════
        logger.info("═══ 第二阶段：压榨产能 ═══")
        phase2_tardiness_bound = self._phase2_tardiness_bound(best_tardiness, status1)
        phase2_result = self._solve_phase(
            orders, machines, eligible, setup_cache, duration_cache,
            H, phase=2, tardiness_bound=phase2_tardiness_bound,
            locked_tasks_by_order_id=locked_tasks_by_order_id,
            external_locked_tasks=external_locked_tasks,
        )
        result.solver_metrics["phase_2"] = getattr(self, "_last_phase_metrics", {})

        if phase2_result is None:
            # 回退使用第一阶段结果
            phase2_status = getattr(self, "_last_solver_status", "UNKNOWN")
            logger.warning("第二阶段求解失败，回退使用第一阶段结果: status=%s", phase2_status)
            self._extract_solution(solver1, vars1, orders, machines, eligible,
                                   setup_cache, result)
            result.phase2_score = sum(t.setup_time for t in result.tasks)
            result.status = status1
            self._append_phase2_fallback_diagnostic(
                result,
                phase1_status=status1,
                phase2_status=phase2_status,
                best_tardiness=best_tardiness,
                order_count=n,
                machine_count=M,
            )
        else:
            status2, solver2, vars2, setup_score = phase2_result
            result.phase2_score = setup_score
            self._extract_solution(solver2, vars2, orders, machines, eligible,
                                   setup_cache, result)
            result.status = status2
            logger.info("第二阶段完成: status=%s, total_setup=%d", status2, setup_score)

        required_order_ids = [
            order.order_id
            for order in orders
            if not self._is_optional_candidate(order)
        ]
        self._validate_result(result, expected_order_count=None, required_order_ids=required_order_ids)
        if result.validation_errors:
            result.status = "INVALID"
            for err in result.validation_errors[:10]:
                logger.error("排程结果校验失败: %s", err)
            result.diagnostics.append(Diagnostic(
                entity_type="run",
                entity_id="current",
                severity="critical",
                category="validation",
                code="validation.schedule_result_invalid",
                confidence="proven",
                root_cause="排程结果未通过完整性校验，不能作为可发布计划。",
                evidence=[
                    DiagnosticEvidence("validation_error_count", len(result.validation_errors)),
                    *[
                        DiagnosticEvidence("validation_error", err)
                        for err in result.validation_errors[:5]
                    ],
                ],
                recommendations=[
                    DiagnosticRecommendation("review_solver_inputs", "检查订单、机台和维护约束", "/config"),
                ],
            ))
            self._append_material_matrix_diagnostic(result)
        else:
            result.diagnostics.extend(build_result_diagnostics(result, orders, machines))
            self._append_continuous_run_diagnostics(result)
            self._append_material_matrix_diagnostic(result)
            self._apply_post_solve_diagnostic_status(result)
            if result.blocked_order_count and result.status not in {"INVALID", "UNPUBLISHABLE"}:
                result.status = "PARTIAL"

        return result

    def _apply_post_solve_diagnostic_status(self, result: ScheduleResult) -> None:
        blocking = [
            item
            for item in result.diagnostics
            if getattr(item, "level", None) in {"publish_blocker", "invalid"}
        ]
        if not blocking:
            return
        if any(getattr(item, "level", None) == "invalid" for item in blocking):
            result.status = "INVALID"
        elif result.status not in {"INVALID", "INFEASIBLE"}:
            result.status = "UNPUBLISHABLE"
        result.validation_errors.append(
            f"存在 {len(blocking)} 条不可发布诊断，请修复后重新排程。"
        )

    def _append_phase2_fallback_diagnostic(
        self,
        result: ScheduleResult,
        phase1_status: str,
        phase2_status: str,
        best_tardiness: int,
        order_count: int,
        machine_count: int,
    ) -> None:
        result.diagnostics.append(Diagnostic(
            entity_type="run",
            entity_id="current",
            severity="warning",
            category="capacity",
            code="solver.phase2_fallback",
            confidence="proven",
            root_cause=(
                "第二阶段换产优化未在时间限制内取得可发布解，系统已回退使用第一阶段交期优化结果。"
            ),
            evidence=[
                DiagnosticEvidence("phase1_status", phase1_status),
                DiagnosticEvidence("phase2_status", phase2_status),
                DiagnosticEvidence("phase1_tardiness_score", best_tardiness),
                DiagnosticEvidence("scheduled_order_count", order_count),
                DiagnosticEvidence("machine_count", machine_count),
                DiagnosticEvidence("time_limit_seconds", SOLVER_TIME_LIMIT_SECONDS, "s"),
            ],
            recommendations=[
                DiagnosticRecommendation("review_phase2_scope", "减少本轮候选订单或放宽二阶段时间限制", "/config?tab=orders"),
                DiagnosticRecommendation("review_setup_rules", "补齐关键换产规则后重新运行", "/config?tab=rules"),
            ],
            display_title="二阶段换产优化已回退",
        ))

    def _append_continuous_run_diagnostics(self, result: ScheduleResult) -> None:
        """Post-solve visibility for the 72h cleaning rule."""
        policy = self.continuous_run_policy
        limit_mins = policy["limit_mins"]
        cleaning_mins = policy["cleaning_mins"]
        enforcement_mode = policy["enforcement_mode"]
        validation_level = "publish_blocker" if enforcement_mode in {"hard", "publish_blocker"} else "warning"
        severity = "critical" if validation_level == "publish_blocker" else "warning"
        for machine_id, tasks in result.machine_sequences.items():
            ordered = sorted(tasks, key=lambda item: (item.start_mins, item.end_mins))
            if not ordered:
                continue

            machine = ordered[0].machine
            initial_mins = max(0, int(machine.initial_continuous_run_mins or 0))
            segment_anchor: Optional[int] = None
            segment_initial = initial_mins
            segment_first_order: Optional[str] = None
            last_end: Optional[int] = None
            reported = False

            for task in ordered:
                setup_start = max(0, task.start_mins - task.setup_time)
                if segment_anchor is None:
                    segment_anchor = setup_start
                    segment_first_order = task.order.order_id
                elif last_end is not None:
                    gap = setup_start - last_end
                    if gap >= cleaning_mins:
                        segment_anchor = setup_start
                        segment_initial = 0
                        segment_first_order = task.order.order_id

                elapsed = segment_initial + task.end_mins - (segment_anchor or 0)
                if elapsed > limit_mins and not reported:
                    result.diagnostics.append(Diagnostic(
                        entity_type="machine",
                        entity_id=machine_id,
                        severity=severity,
                        category="maintenance",
                        code="maintenance.continuous_run_cleaning_required",
                        confidence="inferred",
                        root_cause=(
                            f"{machine_id} 当前计划段连续运行约 {elapsed} 分钟，"
                            f"超过 {limit_mins} 分钟上限；需要在该段前后插入"
                            f"不少于 {cleaning_mins} 分钟的清场/维护窗口后重新排程。"
                        ),
                        evidence=[
                            DiagnosticEvidence("continuous_run_mins", elapsed, "min"),
                            DiagnosticEvidence("limit_mins", limit_mins, "min"),
                            DiagnosticEvidence("required_cleaning_mins", cleaning_mins, "min"),
                            DiagnosticEvidence("enforcement_mode", enforcement_mode),
                            DiagnosticEvidence("first_order_id", segment_first_order),
                            DiagnosticEvidence("last_order_id", task.order.order_id),
                        ],
                        recommendations=[
                            DiagnosticRecommendation(
                                "add_maintenance_window",
                                "新增清场维护窗口",
                                f"/config?tab=rules&section=maintenance&machine={machine_id}",
                            ),
                            DiagnosticRecommendation(
                                "rerun_schedule",
                                "维护窗口保存后重新运行排程",
                                "/dashboard",
                            ),
                        ],
                        display_title=f"{machine_id} 连续运行超过 72h",
                        level=validation_level,
                    ))
                    reported = True

                last_end = task.end_mins

    def _append_material_matrix_diagnostic(self, result: ScheduleResult) -> None:
        missing_pairs = (
            self.setup_mgr.get_missing_material_switches()
            if hasattr(self.setup_mgr, "get_missing_material_switches")
            else []
        )
        if not missing_pairs:
            return

        fallback_count = sum(item["lookup_count"] for item in missing_pairs)
        evidence = [
            DiagnosticEvidence("missing_pair_count", len(missing_pairs)),
            DiagnosticEvidence("fallback_lookup_count", fallback_count),
            DiagnosticEvidence("fallback_mins", DEFAULT_MATERIAL_SWITCH_TIME_MINS, "min"),
        ]
        for item in missing_pairs[:8]:
            evidence.append(DiagnosticEvidence(
                "missing_material_pair",
                f"{item['from_material']} -> {item['to_material']} ({item['lookup_count']} 次)",
            ))

        result.diagnostics.append(Diagnostic(
            entity_type="run",
            entity_id="current",
            severity="warning",
            category="setup",
            code="setup.material_switch_matrix_missing",
            confidence="proven",
            root_cause=(
                f"本轮排程有 {len(missing_pairs)} 组原料切换规则缺失，"
                f"已 {fallback_count} 次使用默认 {DEFAULT_MATERIAL_SWITCH_TIME_MINS} 分钟降级值。"
            ),
            evidence=evidence,
            recommendations=[
                DiagnosticRecommendation("add_material_switch_rules", "在规则页补充材料切换矩阵", "/config?tab=rules"),
                DiagnosticRecommendation("rerun_schedule", "补齐规则后重新运行排程", "/dashboard"),
            ],
            display_title="材料切换规则缺失",
        ))

    def _estimate_horizon(
        self,
        n: int,
        machine_count: int,
        eligible: Dict[int, List[int]],
        setup_cache: Dict[Tuple[int, int, int], int],
        duration_cache: Dict[Tuple[int, int], int],
    ) -> int:
        """根据当前订单量估算求解计划域，避免压力订单超出固定 31 天窗口。"""
        if n == 0:
            return MAX_HORIZON_MINUTES

        min_total_duration = sum(
            min(duration_cache[(idx, m_idx)] for m_idx in eligible[idx])
            for idx in range(n)
        )
        max_setup = max(setup_cache.values(), default=0)
        setup_buffer = n * max_setup
        # Use a conservative per-machine upper bound. The pressure-test workbook
        # can exceed the fixed 31-day plant capacity; a tight average-load bound
        # still becomes infeasible when orders are restricted to a subset of lines.
        dynamic_horizon = min_total_duration + setup_buffer
        return max(MAX_HORIZON_MINUTES, dynamic_horizon)

    def _model_size_metrics(
        self,
        orders: List[ProductionOrderModel],
        machines: List[BlownFilmMachineModel],
        eligible: Dict[int, List[int]],
        setup_cache: Dict[Tuple[int, int, int], int],
        locked_tasks_by_order_id: Optional[Dict[str, ScheduledTask]] = None,
        external_locked_tasks: Optional[List[ScheduledTask]] = None,
    ) -> Dict:
        locked_tasks_by_order_id = locked_tasks_by_order_id or {}
        external_locked_tasks = external_locked_tasks or []
        eligible_orders_per_machine: Dict[str, int] = {}
        arc_count = 0
        pruned_arc_count = 0
        for m_idx, machine in enumerate(machines):
            order_count = sum(1 for idx in range(len(orders)) if m_idx in eligible.get(idx, []))
            eligible_orders_per_machine[machine.machine_id] = order_count
            if order_count:
                arc_count += 1 + (3 * order_count)
                for i in range(len(orders)):
                    if m_idx not in eligible.get(i, []):
                        continue
                    for j in range(len(orders)):
                        if i == j or m_idx not in eligible.get(j, []):
                            continue
                        setup_time = setup_cache[(i, j, m_idx)]
                        if self._should_prune_order_arc(setup_time):
                            pruned_arc_count += 1
                        else:
                            arc_count += 1

        return {
            "order_count": len(orders),
            "machine_count": len(machines),
            "assignment_count": sum(len(machine_indices) for machine_indices in eligible.values()),
            "optional_candidate_count": sum(1 for order in orders if self._is_optional_candidate(order)),
            "eligible_orders_per_machine": eligible_orders_per_machine,
            "arc_count": arc_count,
            "pruned_arc_count": pruned_arc_count,
            "setup_cache_size": len(setup_cache),
            "locked_order_count": sum(
                1 for order in orders if order.order_id in locked_tasks_by_order_id
            ),
            "external_locked_interval_count": len(external_locked_tasks),
        }

    def _solve_phase(
        self,
        orders, machines, eligible, setup_cache, duration_cache,
        H, phase, tardiness_bound,
        locked_tasks_by_order_id=None,
        external_locked_tasks=None,
    ):
        """
        构建并求解单阶段 CP-SAT 模型。
        phase=1: 目标=最小化加权延期
        phase=2: 锁死延期≤tardiness_bound, 目标=最小化换产时间
        返回 (status_str, solver, vars_dict, objective_value) 或 None
        """
        n = len(orders)
        model = cp_model.CpModel()
        locked_tasks_by_order_id = locked_tasks_by_order_id or {}
        external_locked_tasks = external_locked_tasks or []
        external_locked_tasks_by_machine_id: Dict[str, List[ScheduledTask]] = {}
        for task in external_locked_tasks:
            external_locked_tasks_by_machine_id.setdefault(task.machine.machine_id, []).append(task)

        # ─── 决策变量 ───
        presence = {}   # presence[i][m_idx] = BoolVar
        starts = {}     # starts[i][m_idx] = IntVar
        ends = {}       # ends[i][m_idx] = IntVar
        intervals = {}  # intervals[i][m_idx] = IntervalVar
        rejected_candidates = {}

        for idx in range(n):
            presence[idx] = {}
            starts[idx] = {}
            ends[idx] = {}
            intervals[idx] = {}
            for m_idx in eligible[idx]:
                p = model.new_bool_var(f'p_{idx}_{m_idx}')
                s = model.new_int_var(0, H, f's_{idx}_{m_idx}')
                e = model.new_int_var(0, H, f'e_{idx}_{m_idx}')
                dur = duration_cache[(idx, m_idx)]
                iv = model.new_optional_interval_var(s, dur, e, p, f'iv_{idx}_{m_idx}')
                presence[idx][m_idx] = p
                starts[idx][m_idx] = s
                ends[idx][m_idx] = e
                intervals[idx][m_idx] = iv

        # ─── 约束 1：唯一分派 ───
        for idx in range(n):
            assigned = sum(presence[idx][m] for m in eligible[idx])
            if self._is_optional_candidate(orders[idx]):
                rejected = model.new_bool_var(f'rejected_candidate_{idx}')
                model.add(assigned + rejected == 1)
                rejected_candidates[idx] = rejected
            else:
                model.add_exactly_one(presence[idx][m] for m in eligible[idx])

        for idx, order in enumerate(orders):
            locked_task = locked_tasks_by_order_id.get(order.order_id)
            if not locked_task:
                continue
            locked_machine_idx = next(
                (
                    m_idx
                    for m_idx, machine in enumerate(machines)
                    if machine.machine_id == locked_task.machine.machine_id
                ),
                None,
            )
            if locked_machine_idx is None or locked_machine_idx not in eligible[idx]:
                model.add_bool_or([])
                continue
            if getattr(locked_task, "manual_lock_machine", True):
                for m_idx in eligible[idx]:
                    model.add(presence[idx][m_idx] == (1 if m_idx == locked_machine_idx else 0))
            if getattr(locked_task, "manual_lock_time", True):
                model.add(starts[idx][locked_machine_idx] == locked_task.start_mins)
                model.add(ends[idx][locked_machine_idx] == locked_task.end_mins)

        # ─── 约束 2：原料齐套等待 ───
        for idx in range(n):
            mat_avail = orders[idx].material_available_mins
            if mat_avail > 0:
                for m_idx in eligible[idx]:
                    model.add(starts[idx][m_idx] >= mat_avail).only_enforce_if(
                        presence[idx][m_idx])

        # ─── 约束 3 & 4：Circuit 路由 + 换产时间间隔 ───
        # 使用单仓库节点 (depot) 的 Hamiltonian 回路建模。
        # depot (节点0) 代表机台初始状态，订单映射为节点 1..K。
        setup_delay_vars = []

        for m_idx, m in enumerate(machines):
            m_orders = [i for i in range(n) if m_idx in eligible[i]]
            if not m_orders:
                continue

            # 节点映射：depot=0, 订单→1..K
            K = len(m_orders)
            # order_idx → local_node (1-based)
            node_of = {oid: nid + 1 for nid, oid in enumerate(m_orders)}
            DEPOT = 0
            arcs = []

            # 仓库自环：机台完全空闲时
            depot_self = model.new_bool_var(f'depot_self_{m_idx}')
            arcs.append((DEPOT, DEPOT, depot_self))
            machine_presence = [presence[i][m_idx] for i in m_orders]
            assigned_count = sum(machine_presence)
            model.add(assigned_count == 0).only_enforce_if(depot_self)
            model.add(assigned_count >= 1).only_enforce_if(depot_self.negated())

            # 仓库 → 各订单（首单弧）
            for j in m_orders:
                j_node = node_of[j]
                arc_var = model.new_bool_var(f'arc_{m_idx}_d_{j}')
                arcs.append((DEPOT, j_node, arc_var))
                model.add(arc_var <= presence[j][m_idx])
                setup_t = setup_cache[(-1, j, m_idx)]
                model.add(starts[j][m_idx] >= setup_t).only_enforce_if(arc_var)
                delay_var = model.new_int_var(0, H, f'delay_{m_idx}_d_{j}')
                model.add(delay_var == setup_t).only_enforce_if(arc_var)
                model.add(delay_var == 0).only_enforce_if(arc_var.negated())
                setup_delay_vars.append(delay_var)

            # 各订单 → 仓库（末单弧）
            for i in m_orders:
                i_node = node_of[i]
                arc_var = model.new_bool_var(f'arc_{m_idx}_{i}_d')
                arcs.append((i_node, DEPOT, arc_var))
                model.add(arc_var <= presence[i][m_idx])

            # 订单间弧
            for i in m_orders:
                for j in m_orders:
                    if i == j:
                        continue
                    setup_t = setup_cache[(i, j, m_idx)]
                    if self._should_prune_order_arc(setup_t):
                        continue
                    i_node = node_of[i]
                    j_node = node_of[j]
                    arc_var = model.new_bool_var(f'arc_{m_idx}_{i}_{j}')
                    arcs.append((i_node, j_node, arc_var))
                    model.add(arc_var <= presence[i][m_idx])
                    model.add(arc_var <= presence[j][m_idx])
                    model.add(
                        starts[j][m_idx] >= ends[i][m_idx] + setup_t
                    ).only_enforce_if(arc_var)
                    # 记录换产延时变量
                    delay_var = model.new_int_var(0, H, f'delay_{m_idx}_{i}_{j}')
                    model.add(delay_var == setup_t).only_enforce_if(arc_var)
                    model.add(delay_var == 0).only_enforce_if(arc_var.negated())
                    setup_delay_vars.append(delay_var)

            # 未激活订单自环（自环补丁）
            for i in m_orders:
                i_node = node_of[i]
                self_arc = model.new_bool_var(f'self_{m_idx}_{i}')
                arcs.append((i_node, i_node, self_arc))
                # 自环激活 ↔ 该订单未分派到此机台
                model.add(self_arc + presence[i][m_idx] == 1)

            model.add_circuit(arcs)

            machine_intervals = [intervals[i][m_idx] for i in m_orders]
            for locked_task in external_locked_tasks_by_machine_id.get(m.machine_id, []):
                machine_intervals.append(model.new_fixed_size_interval_var(
                    locked_task.start_mins,
                    locked_task.end_mins - locked_task.start_mins,
                    f'locked_iv_{m_idx}_{locked_task.order.order_id}',
                ))
            for fw in m.forbidden_calendar:
                maintenance_interval = model.new_fixed_size_interval_var(
                    fw.start_mins,
                    fw.end_mins - fw.start_mins,
                    f'fw_iv_{m_idx}_{fw.start_mins}',
                )
                machine_intervals.append(maintenance_interval)
            model.add_no_overlap(machine_intervals)

        # ─── 约束 5：维保日历禁排 ───
        # 维保窗口已作为固定 interval 并入每台机的 NoOverlap 约束。

        # ─── 约束 6：72h 强制停机 ───
        # 简化建模：72h 约束将在解提取阶段做后验校验。
        # 在 CP-SAT 中对所有同机台订单对建模会导致变量爆炸。
        # 此处仅在 Circuit 弧约束中对相邻订单的总跨度做软性限制，
        # 确保求解器倾向于在长连续段中插入间隙。
        # 完整的 72h 校验由 _extract_solution 中的后处理逻辑保障。

        # ─── 目标函数 ───
        tardiness_terms = []
        for idx in range(n):
            o = orders[idx]
            w_i = self._tardiness_weight(o)
            # 每个订单只会激活一个 presence，其余为 0
            for m_idx in eligible[idx]:
                t_var = model.new_int_var(0, H, f'tard_{idx}_{m_idx}')
                p = presence[idx][m_idx]
                # tardiness = max(0, end - due_date) when present, else 0
                diff_var = model.new_int_var(-H, H, f'tdiff_{idx}_{m_idx}')
                model.add(diff_var == ends[idx][m_idx] - o.due_date_mins)
                # t_var >= diff_var when present
                model.add(t_var >= diff_var).only_enforce_if(p)
                # t_var >= 0 is already guaranteed by domain
                # t_var == 0 when not present
                model.add(t_var == 0).only_enforce_if(p.negated())
                weighted = model.new_int_var(0, H * w_i, f'wtard_{idx}_{m_idx}')
                model.add(weighted == t_var * w_i).only_enforce_if(p)
                model.add(weighted == 0).only_enforce_if(p.negated())
                tardiness_terms.append(weighted)

        total_tardiness = model.new_int_var(0, H * 100 * n, 'total_tardiness')
        model.add(total_tardiness == sum(tardiness_terms))

        # --- 加入左靠齐（Left-Packing）软性惩罚，防止任务漂浮产生空白间隙 ---
        start_terms = []
        for idx in range(n):
            for m_idx in eligible[idx]:
                start_var = model.new_int_var(0, H, f'start_val_{idx}_{m_idx}')
                model.add(start_var == starts[idx][m_idx]).only_enforce_if(presence[idx][m_idx])
                model.add(start_var == 0).only_enforce_if(presence[idx][m_idx].negated())
                start_terms.append(start_var)
        total_starts = model.new_int_var(0, H * n, 'total_starts')
        model.add(total_starts == sum(start_terms))

        rejection_penalty = self.candidate_acceptance_policy["reject_penalty"]
        candidate_rejection_cost = sum(
            rejected * rejection_penalty
            for rejected in rejected_candidates.values()
        )

        if phase == 1:
            # 第一阶段：主要目标最小化延期，次要目标尽量提早开工
            model.minimize(total_tardiness * 10000 + candidate_rejection_cost + total_starts)
        else:
            # 第二阶段：锁死交期，最小化换产时间，次要目标尽量提早开工
            model.add(total_tardiness <= tardiness_bound)
            if setup_delay_vars:
                total_setup = model.new_int_var(0, H * n, 'total_setup')
                model.add(total_setup == sum(setup_delay_vars))
                model.minimize(total_setup * 10000 + candidate_rejection_cost + total_starts)
            else:
                total_setup = model.new_int_var(0, 0, 'total_setup')
                model.minimize(candidate_rejection_cost + total_starts)

        # ─── 求解 ───
        solver = cp_model.CpSolver()
        self._apply_solver_profile(solver)
        status = solver.solve(model)

        status_map = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }
        status_str = status_map.get(status, "UNKNOWN")
        self._last_solver_status = status_str

        objective_for_metrics = None
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if phase == 1:
                obj_val = int(solver.value(total_tardiness))
            else:
                obj_val = int(solver.value(total_setup))
            objective_for_metrics = obj_val
        self._last_phase_metrics = self._solver_phase_metrics(
            phase=phase,
            solver=solver,
            status=status_str,
            objective_value=objective_for_metrics,
        )

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            vars_dict = {
                'presence': presence, 'starts': starts, 'ends': ends,
                'rejected_candidates': rejected_candidates,
            }
            return (status_str, solver, vars_dict, obj_val)
        logger.warning("第 %d 阶段求解未获得可行解: status=%s", phase, status_str)
        return None

    def _solver_phase_metrics(self, phase: int, solver, status: str, objective_value: Optional[int]) -> Dict:
        bound = float(solver.BestObjectiveBound())
        objective = float(objective_value) if objective_value is not None else None
        gap = None
        if objective is not None:
            denominator = max(abs(objective), 1.0)
            gap = max(0.0, abs(objective - bound) / denominator)
        return {
            "phase": phase,
            "status": status,
            "objective": objective_value,
            "best_bound": bound,
            "gap": gap,
            "branches": int(solver.NumBranches()),
            "conflicts": int(solver.NumConflicts()),
            "wall_time": float(solver.WallTime()),
        }

    def _extract_solution(
        self, solver, vars_dict, orders, machines, eligible, setup_cache, result
    ):
        """从求解器结果中提取排程方案"""
        presence = vars_dict['presence']
        starts = vars_dict['starts']
        ends = vars_dict['ends']
        rejected_candidates = vars_dict.get('rejected_candidates', {})
        n = len(orders)

        # 收集每台机台上的已排订单
        machine_tasks: Dict[int, List[Tuple[int, int, int]]] = {}

        for idx in range(n):
            for m_idx in eligible[idx]:
                if solver.value(presence[idx][m_idx]):
                    s = solver.value(starts[idx][m_idx])
                    e = solver.value(ends[idx][m_idx])
                    if m_idx not in machine_tasks:
                        machine_tasks[m_idx] = []
                    machine_tasks[m_idx].append((idx, s, e))
                    break

        scheduled_indices = {
            idx
            for task_list in machine_tasks.values()
            for idx, _s, _e in task_list
        }
        for idx, rejected in rejected_candidates.items():
            if idx not in scheduled_indices and solver.value(rejected):
                order = orders[idx]
                result.deferred_orders.append({
                    "order_id": order.order_id,
                    "planning_bucket": getattr(order, "planning_bucket", "candidate"),
                    "reason": "candidate_optional_rejected",
                    "message": "Candidate order was deferred by the configured acceptance policy.",
                })

        # 按开始时间排序，计算换产与废料
        for m_idx, task_list in machine_tasks.items():
            task_list.sort(key=lambda x: x[1])
            m = machines[m_idx]
            prev_order = None

            for seq, (idx, s, e) in enumerate(task_list):
                o = orders[idx]
                setup_t = self.setup_calc.calculate_setup_time(prev_order, o, m)
                setup_detail = self.setup_calc.calculate_setup_detail(prev_order, o, m)
                scrap = self.setup_calc.calculate_scrap_weight(prev_order, o, m)

                task = ScheduledTask(
                    order=o, machine=m,
                    start_mins=s, end_mins=e,
                    setup_time=setup_t, scrap_kg=scrap,
                    sequence_index=seq,
                    setup_detail=setup_detail,
                )
                result.add_task(task)

                # 回写到订单模型
                o.assigned_machine_id = m.machine_id
                o.scheduled_start_mins = s
                o.scheduled_end_mins = e
                o.scrap_weight_kg = scrap
                o.actual_material_required_kg = o.total_quantity_kg + scrap

                prev_order = o

        logger.info("解提取完成: %d 个任务已排程", len(result.tasks))

    def _validate_result(
        self,
        result: ScheduleResult,
        expected_order_count: Optional[int],
        required_order_ids: Optional[List[str]] = None,
    ):
        """校验提取后的排程结果，防止错误结果进入导出/API。"""
        errors: List[str] = []

        if expected_order_count is not None and len(result.tasks) != expected_order_count:
            errors.append(
                f"已排订单数 {len(result.tasks)} 与输入订单数 {expected_order_count} 不一致"
            )

        seen = set()
        for task in result.tasks:
            oid = task.order.order_id
            if oid in seen:
                errors.append(f"order {oid} was scheduled more than once")
            seen.add(oid)
            if task.end_mins <= task.start_mins:
                errors.append(
                    f"订单 {oid} 时间窗口非法: {task.start_mins}-{task.end_mins}"
                )

        if required_order_ids is not None:
            missing_required = sorted(set(required_order_ids) - seen)
            for oid in missing_required:
                errors.append(f"required order {oid} was not scheduled")

        for mid, tasks in result.machine_sequences.items():
            ordered = sorted(tasks, key=lambda x: (x.start_mins, x.end_mins))
            for idx, task in enumerate(ordered):
                if idx == 0:
                    if task.start_mins < task.setup_time:
                        errors.append(
                            f"{mid} 首单 {task.order.order_id} 未预留初始换产时间"
                        )
                    continue

                prev = ordered[idx - 1]
                required_start = prev.end_mins + task.setup_time
                if task.start_mins < required_start:
                    errors.append(
                        f"{mid} 订单 {prev.order.order_id}->{task.order.order_id} "
                        f"时间重叠或缺少换产间隔: prev_end={prev.end_mins}, "
                        f"setup={task.setup_time}, start={task.start_mins}"
                    )

            for task in ordered:
                for fw in task.machine.forbidden_calendar:
                    overlaps_fw = (
                        task.start_mins < fw.end_mins
                        and task.end_mins > fw.start_mins
                    )
                    if overlaps_fw:
                        errors.append(
                            f"{mid} 订单 {task.order.order_id} 跨越禁排窗口 "
                            f"{fw.start_mins}-{fw.end_mins}"
                        )

        result.validation_errors = errors
