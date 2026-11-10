# 报数机器人AI · FastAPI 后端镜像
# 基础镜像与服务器现有可行性报告项目保持一致（python:3.13-slim）
#
# 构建：docker build -f server/Dockerfile -t jinribao-backend .
# （构建上下文 = 仓库根，保证 COPY server/ 时路径正确）
FROM python:3.13-slim

WORKDIR /app

# 系统依赖（PyMySQL 不需要，requests 纯 Python）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 依赖
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y pytest pytest-cov 2>/dev/null || true

# 应用代码（构建上下文 = 仓库根）
COPY server/ ./server/

# 运行期可写目录
RUN mkdir -p /app/server/var

# 非 root 用户
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app/server/var
USER appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/server

EXPOSE 8000

# gunicorn + uvicorn worker（单实例足够，需要扩展再加 gevent worker）
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", \
     "-b", "0.0.0.0:8000", \
     "--timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app.main:app"]
