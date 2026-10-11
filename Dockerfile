# AI Drama · 群聊剧情模拟系统
# 可插拔 LLM（OpenAI 兼容）：容器内通过 data/config.json 提供 api_key / base_url / model。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# 运行时数据（会话/角色记忆/config.json）通过卷挂载，避免写进镜像
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8008

# 容器内需允许外部访问，故监听 0.0.0.0；本地裸机运行仍建议 127.0.0.1
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8008"]
