# 使用多阶段构建
# 第一阶段：构建阶段
FROM python:3.12-slim AS builder

WORKDIR /app

# 设置环境变量：使用清华源
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TIMEOUT=60 \
    PIP_RETRIES=3

# 安装 uv（使用清华源）
RUN pip install uv

# 复制项目文件
COPY pyproject.toml .
COPY src/ ./src/

# 构建 wheel（uv 会继承 pip 的源设置）
RUN uv build --wheel .

# 第二阶段：运行阶段
FROM python:3.12-slim

WORKDIR /app

# 使用阿里云 APT 源
RUN set -x && \
    > /etc/apt/sources.list && \
    rm -f /etc/apt/sources.list.d/* && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm main non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian-security/ bookworm-security main non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main non-free non-free-firmware" >> /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 \
        libsm6 \
        graphviz 
        
#    rm -rf /var/lib/apt/lists/*

# 设置 pip 源
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 uv
RUN pip install uv

# 复制并安装 wheel（使用 --system）
# 复制并安装 wheel（使用 --system）
COPY --from=builder /app/dist/*.whl /tmp/
RUN whl_file=$(ls /tmp/*.whl) && uv pip install --system "$whl_file"

EXPOSE 8000 8001 8002
#ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bst_mcp_server"]