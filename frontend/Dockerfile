# 前端镜像：构建产物交给 nginx 静态托管，顺手把 /api 反代到后端容器
#
# 为什么要 nginx 而不是 `vite preview`：vite 的 preview 明确写着不是生产服务器，
# 它没有合适的缓存头、也没有把 /api 转给后端的配置。演示可以，交付不行。
FROM node:22-slim AS build

RUN corepack enable

WORKDIR /app

# 先只拷依赖清单：源码改动不会让这一层缓存失效
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
