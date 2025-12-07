# ==========================================
# 第一阶段：构建环境 (Builder Stage)
# ==========================================
FROM python:3.13-slim as builder

WORKDIR /app

# 设置环境变量：不生成pyc源文件(构建时)，pip不缓存
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 安装编译依赖 (部分加密库可能需要 gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境
RUN python -m venv /opt/venv
# 激活虚拟环境
ENV PATH="/opt/venv/bin:$PATH"

# 1. 安装 requirements.txt 中的依赖 (确保 requirements.txt 里已经加了 selenium)
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# 2. 直接从 PyPI 安装指定版本的客户端
RUN pip install p123client==0.0.9.2 p115client==0.0.8.2

# 3. 复制代码并编译
COPY . /app

# 编译所有 .py 为 .pyc，并删除源文件
RUN python -m compileall -b . && \
    find . -name "*.py" -delete && \
    rm -rf requirements.txt p123client p115client

# ==========================================
# 第二阶段：最终镜像 (Final Stage)
# ==========================================
FROM python:3.13-slim

WORKDIR /app

# ### [新增部分] 安装 Chromium 和 驱动 ###
# Selenium 运行必须依赖这两个包
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量
# 1. PYTHONUNBUFFERED: 确保日志即时输出
# 2. PATH: 包含虚拟环境
# 3. [可选] CHROME_BIN / CHROME_DRIVER: 显式指定路径（通常 apt 安装后会自动在 PATH 中，可不加）
ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# 从构建阶段拷贝虚拟环境 (包含所有依赖)
COPY --from=builder /opt/venv /opt/venv

# 从构建阶段拷贝已编译的代码 (只有 .pyc)
COPY --from=builder /app /app

# 声明数据卷
VOLUME ["/app/db"]

# 运行
CMD ["python", "-O", "123bot.pyc"]