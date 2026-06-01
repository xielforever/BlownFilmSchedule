# 使用官方轻量级 Python 镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装必要的系统依赖（例如 PostgreSQL 客户端开发库等，以防编译某些依赖）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY api/ ./api
COPY src/ ./src
COPY db/ ./db
COPY input/ ./input
COPY scripts/ ./scripts
COPY main.py .

# 暴露 FastAPI 端口
EXPOSE 8000

# 生产环境/UAT环境启动命令：使用 python 数据库自初始化入口运行并加载 Web 服务
CMD ["python", "scripts/deploy_entrypoint.py"]
