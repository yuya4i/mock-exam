# ============================================================
# QuizGen バックエンド Dockerfile (production)
# camoufox（Firefox ベースのアンチボット検出ブラウザ）対応
#
# Runtime posture:
#   - Runs as non-root 'appuser' (UID 1000).
#   - Camoufox Firefox binary lives under /home/appuser/.cache/camoufox.
#   - /app/.cache is owned by appuser so the named volume (quiz-cache)
#     inherits that ownership on first mount.
#
# Known limitation:
#   docker-compose.dev.yml bind-mounts ./backend:/app, so the dev image
#   (Dockerfile.dev) intentionally stays root to avoid host-UID/container-
#   UID mismatch friction on WSL/Windows. Security posture for dev is
#   documented as "trusted local only" in SECURITY.md.
# ============================================================
FROM python:3.11-slim

ARG APP_UID=1000
ARG APP_GID=1000

# ---- システム依存パッケージ (as root) ----
# camoufox（Firefox）の実行に必要なライブラリ群 + 非root切替用 gosu
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    # 起動時の権限降格 (entrypoint 経由)
    gosu \
    # Firefox実行に必要なライブラリ
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libxrender1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    # Xvfb（仮想ディスプレイ）
    xvfb \
    x11-utils \
    # フォント
    fonts-liberation \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# ---- Non-root user setup ----
# UID/GID are overridable via build args in case the operator needs the
# container UID to match the host (e.g. for bind-mounted volumes during
# troubleshooting). Default is 1000 which matches the typical first user
# on WSL/Ubuntu hosts.
RUN groupadd --system --gid ${APP_GID} appuser && \
    useradd  --system --uid ${APP_UID} --gid appuser \
             --create-home --home-dir /home/appuser \
             --shell /usr/sbin/nologin appuser

WORKDIR /app

# ---- Python依存パッケージ (as root, into system site-packages) ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- camoufox browser download (as appuser so files land in /home/appuser) ----
# camoufox fetch also writes GeoLite2-City.mmdb into site-packages/camoufox/,
# so we grant appuser ownership of that directory before switching user.
RUN chown -R appuser:appuser /usr/local/lib/python3.11/site-packages/camoufox/
USER appuser
RUN python -m camoufox fetch

# ---- App code + ownership ----
USER root
COPY . /app
# Pre-create the cache dir so a fresh named volume 'quiz-cache' inherits
# appuser ownership on first mount. (Old volumes that pre-date the
# non-root switch are healed at runtime by docker-entrypoint.sh.)
RUN mkdir -p /app/.cache && \
    chown -R appuser:appuser /app

# Entrypoint: runs as root just long enough to chown an existing
# /app/.cache (idempotent), then `exec gosu appuser` replaces the shell
# with the CMD. NO `USER appuser` directive on purpose — entrypoint
# does the descent so it can fix ownership first.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 4321

# Xvfbを使った仮想ディスプレイで起動（camoufoxのheadless="virtual"対応）
CMD ["python", "-m", "flask", "--app", "app", "run", "--host=0.0.0.0", "--port=4321"]
