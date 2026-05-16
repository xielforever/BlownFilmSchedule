# 吹膜排程 MVP

这是一个本地运行的吹膜排程 MVP：前端上传订单 Excel，后端读取本地机台能力表并使用确定性启发式算法生成排程结果、异常清单、约束审计和导出文件。

订单 Excel 只表达订单需求：

- `orders`：只放订单需求字段，例如订单号、计划完成、配方、物料编码、生产规格、数量、批量、工时等。
- 排程结果中的机台、开始时间、结束时间由算法生成。
- MVP 不接收生产状态、既有计划或外部排程表。

## 运行

安装依赖后启动后端：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend
```

启动前端：

```powershell
cd frontend
npm run dev
```

浏览器访问：

```text
http://127.0.0.1:5173
```

## 样例数据

本地机台能力表：

```text
data/machines.xlsx
```

前端启动后会默认从后端读取这份本地机台表；上传订单只提供订单需求，不需要再上传机台表。

样例订单工作簿：

```text
examples/blownfilm_mvp_mock_v2.xlsx
```

该样例是从截图转录订单中整理出的生产压力演示/回归数据集：只保留订单需求字段，包含紧急、同交期、换料、调机和大批量订单，排程计划由算法自动生成。

重新生成样例：

```powershell
.\.venv\Scripts\python backend\scripts\generate_mock_excel.py
```

## MVP 边界

- 订单 Excel 是唯一上传输入；其中 `orders` 是订单基础表。
- 机台能力和规则从本地 `data/machines.xlsx` 读取。
- 不引入 OR-Tools，先使用可审计的启发式算法。
- 机台适配按 `best`、`recommended`、`marginal`、`blocked` 分级；边界可做机台会被降权。
- 生产时长优先按 `batch_kg / 机台平均产能` 估算，`work_hours` 仅作产能缺失时的兜底。
- 换料和调机会写入排程总占用时间，并拆分输出生产时长、换型时长。
- 预览阶段会校验重复订单号、交期倒挂/过松、同交期同配方集中、批量与数量克重不一致、批量/工时折算产能异常。
- 排程结果会输出候选机台审计：每单保留主要候选机台评分、时间、换型和未选原因。
