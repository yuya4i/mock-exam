# ============================================================
# Stage 1: ビルド
# ============================================================
FROM node:22-alpine AS builder

WORKDIR /app

# package.jsonをコピーしてインストール（キャッシュ活用）
COPY package.json ./
RUN npm install --save-exact

# ソースをコピーしてビルド
COPY . .
RUN npm run build

# ============================================================
# Stage 2: nginx配信
# ============================================================
FROM nginx:1.27-alpine

# Runtime posture (security note for P0-7):
#   The upstream nginx:1.27-alpine image already uses a split-privilege
#   model: the master process runs as root (needed to read config and,
#   in other setups, to bind <1024 ports) and spawns worker processes
#   that drop to the 'nginx' user. All request-handling code runs as the
#   unprivileged worker. Switching the master to non-root here would
#   require moving the pid file, cache dirs, and access/error logs to
#   writable locations and picking a non-default base image (e.g.
#   nginxinc/nginx-unprivileged). That is tracked for Phase 1; at P0 we
#   rely on the upstream model, which is the standard nginx security
#   posture used in production.

# ビルド成果物をコピー
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx設定（Vue Routerのhistoryモード対応 + APIプロキシ）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 1234

CMD ["nginx", "-g", "daemon off;"]
