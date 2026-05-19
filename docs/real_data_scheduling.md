# 真实订单数据排程

当前 HTTP 产品闭环以数据库作为排程数据源，直接使用 UI 配置或源工作簿导入后的订单、机台、配方和约束。

## 从当前数据库状态运行

```bash
python main.py --source db --save-db --triggered-by local
```

Dashboard 的“运行排程”按钮使用同一条数据库排程路径：

```bash
python main.py --save-db --source db --triggered-by <user>
```

## 数据前置条件

- 待排订单状态必须是 `PENDING` 或 `SCHEDULED`。
- 可参与求解的机台状态必须是 `ACTIVE`。
- 每个产品类型应在 `recipes` 中有配方记录；缺失时后端会回退到默认材料序列。
- 运行前应确认机台能力、维护窗口、当前机台状态、换产矩阵和规则表符合当前生产假设。

## 验证查询

从样例、导入数据或人工配置切回正常运行前，可用以下查询检查当前状态：

```sql
SELECT order_id, status
FROM production_orders
WHERE status IN ('PENDING', 'SCHEDULED')
ORDER BY due_date, order_id;

SELECT machine_id, status
FROM machines
ORDER BY machine_id;

SELECT run_id, triggered_by, status, is_active
FROM schedule_runs
ORDER BY run_id DESC
LIMIT 10;
```

active run 应反映最新真实订单排程，不应依赖任何合成演示场景行。
