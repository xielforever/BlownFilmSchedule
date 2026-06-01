# ─── 阶段一：构建阶段 ───
FROM node:18-alpine AS build

WORKDIR /app

# 复制 package 配置文件并安装依赖
COPY package*.json ./
RUN npm ci

# 复制前端项目文件
COPY . .

# 编译静态资源包
RUN npm run build

# ─── 阶段二：托管与代理服务（Nginx） ───
FROM nginx:1.25-alpine

# 复制编译后的前端静态文件到 Nginx 托管目录
COPY --from=build /app/dist /usr/share/nginx/html

# 复制生产级 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
