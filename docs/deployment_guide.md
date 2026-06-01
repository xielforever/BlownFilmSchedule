# APS 排程系统多场景部署与运维指南

本指南详细介绍了将 **医疗 PE 薄膜吹膜机 APS 智能排程系统** 部署到各种不同生产与开发环境的技术指南，包括 **Kubernetes (K8s) 原生集群部署**、**Helm 工艺编排一键交付** 以及 **本地物理机/开发机原生部署**。

---

## 1. Kubernetes (K8s) 原生集群部署

在 K8s 环境中，我们将服务拆分为无状态 Web 容器（前端与后端）以及有状态数据库（PostgreSQL）。

### A. 整体架构清单
建议在集群中创建一个独立的 Namespace（例如 `aps-system`），并使用以下三组资源：

```text
aps-manifests/
├── k8s-secrets.yaml       # 敏感证书及配置
├── postgres-stateful.yaml # 有状态 PG 数据库 (StatefulSet + PVC)
├── backend-deploy.yaml    # 无状态 FastAPI 后端服务
└── frontend-deploy.yaml   # 无状态 Frontend + Nginx 静态服务
```

### B. K8s 配置文件实例

#### 1. 配置与敏感信息管理 (`k8s-secrets.yaml`)
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: aps-system
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: aps-config
  namespace: aps-system
data:
  APS_DB_HOST: "postgres-svc"
  APS_DB_PORT: "5432"
  APS_DB_NAME: "ap"
  APS_DB_USER: "ap_user"
---
apiVersion: v1
kind: Secret
metadata:
  name: aps-secret
  namespace: aps-system
type: Opaque
data:
  # Base64 编码后的 "uat_secure_password_123" 和 "uat_jwt_secret_token"
  APS_DB_PASSWORD: dWF0X3NlY3VyZV9wYXNzd29yZF8xMjM=
  APS_JWT_SECRET: dWF0X2p3dF9zZWNyZXRfdG9rZW5fY2hhbmdlX2luX3Byb2Q=
```

#### 2. PostgreSQL 有状态持久化部署 (`postgres-stateful.yaml`)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-svc
  namespace: aps-system
spec:
  ports:
    - port: 5432
  selector:
    app: postgres
  clusterIP: None # Headless 保证内部域名稳定
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: aps-system
spec:
  serviceName: "postgres-svc"
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:15-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_NAME
            - name: POSTGRES_USER
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_USER
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: aps-secret
                  key: APS_DB_PASSWORD
          volumeMounts:
            - name: pg-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pg-data
      spec:
        accessModes: [ "ReadWriteOnce" ]
        resources:
          requests:
            storage: 10Gi # 视历史审计记录规模动态扩展
```

#### 3. FastAPI 后端计算节点部署 (`backend-deploy.yaml`)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-svc
  namespace: aps-system
spec:
  ports:
    - port: 8000
      targetPort: 8000
  selector:
    app: backend
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: aps-system
spec:
  replicas: 2 # 双副本高可用计算
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
        - name: backend
          image: your-registry.com/aps/backend:latest # 指向构建好的私有镜像
          ports:
            - containerPort: 8000
          env:
            - name: APS_DB_HOST
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_HOST
            - name: APS_DB_PORT
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_PORT
            - name: APS_DB_NAME
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_NAME
            - name: APS_DB_USER
              valueFrom:
                configMapKeyRef:
                  name: aps-config
                  key: APS_DB_USER
            - name: APS_DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: aps-secret
                  key: APS_DB_PASSWORD
            - name: APS_JWT_SECRET
              valueFrom:
                secretKeyRef:
                  name: aps-secret
                  key: APS_JWT_SECRET
          resources:
            requests:
              cpu: "1000m"  # CP-SAT 求解器耗 CPU，保障算力申请
              memory: "2Gi"
            limits:
              cpu: "4000m"
              memory: "4Gi"
```

#### 4. 前端 Nginx 静态节点部署 (`frontend-deploy.yaml`)
```yaml
apiVersion: v1
kind: Service
metadata:
  name: frontend-svc
  namespace: aps-system
spec:
  type: NodePort # 生产环境建议对接 Ingress / LoadBalancer
  ports:
    - port: 80
      targetPort: 80
      nodePort: 30080
  selector:
    app: frontend
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: aps-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
        - name: frontend
          image: your-registry.com/aps/frontend:latest
          ports:
            - containerPort: 80
```

---

## 2. Helm 工艺包一键发布与交付

通过编写 Helm Chart，可实现多环境（UAT、生产、演练）一键配置替换与多应用版本回滚。

### A. Helm 目录结构推荐
```text
charts/aps-schedule-system/
├── Chart.yaml              # Chart 元数据
├── values.yaml             # 环境配置文件（数据库密码、副本数等）
└── templates/              # 模板文件目录
    ├── configmap.yaml
    ├── secrets.yaml
    ├── postgres-stateful.yaml
    ├── backend-deploy.yaml
    ├── frontend-deploy.yaml
    └── _helpers.tpl
```

### B. 核心 `values.yaml` 配置样本
```yaml
# 全局基本参数
global:
  environment: uat

# 生产级 PostgreSQL
postgres:
  storageSize: 20Gi
  dbName: ap
  dbUser: ap_user
  dbPassword: "secure_password_to_override"

# 后端 FastAPI 求解节点
backend:
  replicas: 2
  image:
    repository: your-registry.com/aps/backend
    tag: v1.0.0
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 1000m
      memory: 2Gi
    limits:
      cpu: 4000m
      memory: 4Gi
  jwtSecret: "change_me_in_production"

# 前端 Nginx 大屏幕
frontend:
  replicas: 2
  image:
    repository: your-registry.com/aps/frontend
    tag: v1.0.0
  service:
    type: LoadBalancer # 直接对接云提供商外部网关
    port: 80
```

### C. 常用发布命令
```bash
# 1. 语法合规性校验
helm lint ./charts/aps-schedule-system

# 2. 演练模拟安装（Dry Run）
helm install aps-test ./charts/aps-schedule-system --dry-run --debug

# 3. 正式部署发布
helm install aps-production ./charts/aps-schedule-system --namespace aps-system --create-namespace -f values.yaml

# 4. 灰度升级
helm upgrade aps-production ./charts/aps-schedule-system --namespace aps-system -f values.yaml

# 5. 查看历史发布与快速回滚
helm history aps-production --namespace aps-system
helm rollback aps-production 2 --namespace aps-system # 回滚到第2版本
```

---

## 3. 本地原生环境（裸机/开发机）部署

当您需要脱离 Docker，直接在物理开发机上以最高效的方式调试排程算法时，请参考本指南。

### A. 环境与依赖准备
- **操作系统**：Windows 10/11, macOS, 或主流 Linux 发行版（如 Ubuntu 20.04+）。
- **Python**: 3.9 ~ 3.11（因 `ortools` 需要稳定 C++ 支持，不推荐直接使用过于超前的最新 Python 大版本）。
- **Node.js**: 18.x 或 20.x。
- **PostgreSQL**: 14.x 或更高（需要有创建本地库的权限）。

---

### B. 开发机原生极速拉起步骤

#### 步骤 1. 配置本地 PostgreSQL 数据库
1. 启动本地 PG 服务。使用 `psql` 或桌面工具（如 `pgAdmin`）执行以下指令：
   ```sql
   CREATE DATABASE blownfilm_aps;
   CREATE USER aps_dev_user WITH PASSWORD 'dev_secure_pwd_123';
   GRANT ALL PRIVILEGES ON DATABASE blownfilm_aps TO aps_dev_user;
   ```

#### 步骤 2. 配置环境变量
在项目根目录下创建一个 `.env` 文件（或写入开发机环境变量）：
```bash
APS_DB_HOST=localhost
APS_DB_PORT=5432
APS_DB_NAME=blownfilm_aps
APS_DB_USER=aps_dev_user
APS_DB_PASSWORD=dev_secure_pwd_123
APS_JWT_SECRET=local_dev_jwt_secret_token
```

#### 步骤 3. 初始化 Python 后端开发环境
1. **创建并激活虚拟环境 (venv)**
   - *Windows*:
     ```bash
     python -m venv venv
     .\venv\Scripts\activate
     ```
   - *Linux / macOS*:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

2. **安装核心科学计算与求解依赖**
   ```bash
   pip install -r requirements.txt
   ```
   *(该步骤会自动拉取并配置 Google `ortools`、`pandas`、`openpyxl` 及 `fastapi`)*

3. **初始化数据库表结构并执行初次排程计算**
   ```bash
   python main.py --init-db --save-db
   ```
   *(该指令会自动抓取 `input/吹膜机排程数据.xlsx` 车间 Excel 配置，在本地 PG 自动建表，完成 OR-Tools 第一次排程求解计算，并完美填入数据库)*

4. **开启 FastAPI 裸跑 Web 调试服务**
   ```bash
   uvicorn api.main:app --reload --port 8000
   ```
   *(在浏览器打开 http://localhost:8000/docs 即可观赏自动生成的 Swagger RESTful APIs 接口文档。)*

---

#### 步骤 4. 初始化前端大屏 React 环境
1. **安装 Node 模块依赖**
   ```bash
   cd web
   npm install
   ```
2. **本地联调启动**
   ```bash
   npm run dev
   ```
   *(控制台会提供本地开发热重载服务器地址，默认为 http://localhost:3000。此时前端会自动通过 proxy 代理机制，将所有以 `/api` 开头的请求透明转发至刚才跑在 8000 端口的 Python FastAPI 后端进行交互。)*

---

## 4. 生产排污消杀与数据备份运维 (Day 2 Operations)

> [!WARNING]
> ### GMP 数据安全性建议
> 生产环境数据库建议开启定期备份，备份周期推荐为**每日夜间零点**。
>
> 备份命令参考：
> ```bash
> pg_dump -h <db_host> -U ap_user -d ap -F c -b -v -f "/backup/aps_db_$(date +%F).backup"
> ```
