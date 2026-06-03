# Octopus control-plane server + agent runtimes in a single image.
# 主服务与各 runtime 子进程同进程/同容器运行（见 server/services/heartbeat.py 的
# asyncio.create_subprocess_exec），因此 runtime CLI 必须与服务端打进同一镜像。
FROM python:3.12-slim-bookworm

# uv：用 uv.lock 做可复现安装（pip 无法直接读 uv.lock）
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

# 系统依赖：
#   git                 —— execution workspace 走 git checkout/worktree
#   ca-certificates/curl —— TLS 与 NodeSource 安装脚本
#   nodejs              —— claude/codex/opencode/openclaw 四个 runtime CLI 是 npm 包
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Agent runtime CLI：由服务端作为子进程拉起，命令名需在 PATH 上可解析
# （runner 用 shutil.which("opencode") 解析）。只装实际启用的 runtime 即可裁剪。
RUN npm install -g --omit=dev \
    opencode-ai \
    @anthropic-ai/claude-code@latest \
    @openai/codex@latest \
    openclaw@latest

WORKDIR /app

# 第一层：只装第三方依赖，lock 不变则命中缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project


RUN uv add asyncpg
# 第二层：一方源码（server/、packages/、alembic.ini、migrations）
# 不安装为 wheel，用 PYTHONPATH 直接跑源码，保证 runner.py 的 _project_root()
# 与 alembic.ini 路径解析正确。
COPY . .

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    OCTOPUS_HOST=0.0.0.0 \
    OCTOPUS_PORT=8000 \
    OCTOPUS_AUTO_MIGRATE=true \
    OCTOPUS_DATABASE_URL="sqlite+aiosqlite:////data/octopus.db" \
    HOME=/data

# /data 同时承载 sqlite 库文件与 per-agent runtime home
# （.octopus/runtime-homes 建在进程 CWD 下，故 WORKDIR 指向 /data）。
RUN mkdir -p /data
VOLUME ["/data"]
WORKDIR /data

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
