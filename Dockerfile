# 使用 Python 3.13 瘦身版作为基础镜像
FROM python:3.13.2-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ARG APP_ENV=development
ENV APP_ENV=${APP_ENV} \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# ✨ 关键优化 1：替换 Debian 系统源为清华镜像源
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 1. 安装基础系统依赖
# ✅ [Fix] 删除了 pip install uv 行尾的反斜杠，防止 ENV 指令被吞
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && pip install --upgrade pip \
    && pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && rm -rf /var/lib/apt/lists/*

# ✨ 关键优化 2：通过环境变量设置 uv 镜像源
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 先拷贝依赖配置文件，利用 Docker 层缓存
# ✅ 同时也拷贝 README.md，防止 pip install 报错
COPY pyproject.toml README.md .

# ✨ 优化：在 Docker 内部直接使用系统 Python 环境安装依赖
RUN uv pip install --system -e .

# 3. 拷贝项目所有代码
COPY . .

# 赋予脚本执行权限
RUN chmod +x scripts/*.sh

# 暴露端口
EXPOSE 8000

# 启动应用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]