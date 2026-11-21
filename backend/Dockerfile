FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
# 主源为清华镜像，失败时回退阿里镜像（构建环境网络差异兜底）
RUN pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple \
    || pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY app ./app
COPY tests ./tests
COPY pytest.ini .

EXPOSE 8000
# 启动即自动建表；空库自动注入演示种子数据（幂等）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
