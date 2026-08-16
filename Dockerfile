# 多阶段构建：API 与 Worker 共用同一镜像
FROM python:3.11-slim

WORKDIR /app

# 系统依赖：编译部分包 + 中文字体可选（出图）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

EXPOSE 8000

# 默认起 API；Worker 在 compose 里覆盖 command
CMD ["python", "main.py"]
