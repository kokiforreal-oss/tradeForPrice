# 生产：只跑应用。MySQL / Nginx 仍在宿主机。
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1"]
