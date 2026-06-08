# BlownFilm Schedule Web Console

This directory contains the React + Vite frontend for the APS scheduling console.

## Runtime

- React 19
- Vite 8
- ECharts 6
- React Router 7
- Axios
- Playwright for browser regression checks

## Main Screens

- `/login`: built-in demo login flow.
- `/dashboard`: planning summary, root-cause cards, and run overview.
- `/workbench`: planner workbench for order screening, draft creation, validation, publishing, cancellation, locked-task review, and manual adjustment impact review.
- `/orders`: order list, screening status, blocked/risk buckets, and order maintenance.
- `/gantt`: schedule timeline and event detail inspection.
- `/machines`: machine capability and diagnostic view.
- `/config`: admin policy and setup configuration.

## Local Commands

```bash
npm install
npm run dev
npm run lint
npm run build
npm run e2e
```

The frontend expects the FastAPI backend to be reachable at the API base URL configured in `src/api/client.js`.

## Regression Scope

Keep these checks passing after frontend or API-contract changes:

```bash
npm run lint
npm run build
npm run e2e -- login.spec.js smoke-routes.spec.js localization.spec.js config-policy.spec.js
npm run e2e -- workbench.spec.js
```

The workbench is the primary production-user surface. UI changes should preserve the worker-focused flow: screen orders first, create a draft, review blockers, validate, then publish only when the backend allows it.

---

# 吹膜 APS 前端控制台

本目录是 APS 排程系统的 React + Vite 前端。

## 主要页面

- `/login`：内置演示账号登录。
- `/dashboard`：排程总览、根因卡片和运行状态。
- `/workbench`：排程工作台，覆盖订单初筛、草案创建、复核、校验、发布、废弃、锁定任务摘要和人工调整影响分析。
- `/orders`：订单列表、筛选状态、异常/风险订单和订单维护。
- `/gantt`：排程时间轴和事件详情。
- `/machines`：机台能力与诊断视图。
- `/config`：策略和换产配置管理。

## 本地验证

```bash
npm run lint
npm run build
npm run e2e -- login.spec.js smoke-routes.spec.js localization.spec.js config-policy.spec.js
npm run e2e -- workbench.spec.js
```

工作台是一线排程用户的主界面。改动前端时，应保持“先筛订单、再建草案、复核阻断、校验发布”的业务顺序，发布判断以后台返回为准。
