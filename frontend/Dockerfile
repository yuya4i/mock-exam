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

# ビルド成果物をコピー
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx設定（Vue Routerのhistoryモード対応 + APIプロキシ）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
