# 后端镜像：只管"跑起来"，不做开发环境
#
# 两个容易踩的点写在这里：
# 1. 必须装中文字体。matplotlib 找不到中文字体时不会报错，它会把中文画成方框，
#    而且是在**报告导出**时才暴露——那时人已经在答辩现场了（RK-05）。
# 2. 不装 build-essential。依赖全是 wheel，省 300 MB 与几分钟构建时间；
#    真需要编译时再加，而不是默认背上。
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY resources ./resources

# 容器里没有 .venv、也不该有；数据目录由 compose 的卷挂进来
ENV CBC_DATA_DIR=/data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
