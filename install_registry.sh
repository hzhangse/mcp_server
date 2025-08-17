#!/bin/bash

# ========================================
# 一键部署 Docker Private Registry + Portainer
# 支持认证选项
# ========================================

set -e  # 出错即停止

# ========= 配置区 =========
PROJECT_DIR="./docker-registry"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
REGISTRY_PORT=5000
PORTAINER_PORT=9000

# Registry 认证设置（留空则不启用）
ENABLE_AUTH="yes"  # 设为 "no" 不启用认证
AUTH_USERNAME="admin"
AUTH_PASSWORD="admin123"

# ========= 创建项目结构 =========
echo "📁 创建项目目录: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

mkdir -p ./registry/data
if [ "$ENABLE_AUTH" = "yes" ]; then
    mkdir -p ./registry/auth
fi
mkdir -p ./portainer/data

# ========= 生成 docker-compose.yml =========
echo "📝 生成 docker-compose.yml"

cat > "$COMPOSE_FILE" << EOF
version: '3.8'

services:
  registry:
    image: registry:2
    container_name: registry
    restart: always
    ports:
      - "$REGISTRY_PORT:5000"
    volumes:
      - ./registry/data:/var/lib/registry
EOF

# 如果启用认证，追加认证配置
if [ "$ENABLE_AUTH" = "yes" ]; then
cat >> "$COMPOSE_FILE" << EOF
      - ./registry/auth:/auth
    environment:
      REGISTRY_AUTH: htpasswd
      REGISTRY_AUTH_HTPASSWD_REALM: Registry Realm
      REGISTRY_AUTH_HTPASSWD_PATH: /auth/htpasswd
EOF
else
cat >> "$COMPOSE_FILE" << EOF
    environment:
      REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY: /var/lib/registry
EOF
fi

# 继续写入 Portainer 和网络配置
cat >> "$COMPOSE_FILE" << EOF

  portainer:
    image: portainer/portainer-ce:latest
    container_name: portainer
    restart: always
    ports:
      - "$PORTAINER_PORT:9000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./portainer/data:/data
    depends_on:
      - registry
    networks:
      - registry-net

networks:
  registry-net:
    driver: bridge
EOF

# ========= 生成认证文件（如果启用） =========
if [ "$ENABLE_AUTH" = "yes" ]; then
    echo "🔐 启用 Registry 认证，生成 htpasswd 文件"

    # 检查 htpasswd 是否存在
    if ! command -v htpasswd &> /dev/null; then
        echo "⚠️ 未找到 htpasswd，请安装 apache2-utils (Ubuntu) 或 httpd-tools (CentOS)"
        echo "   Ubuntu: sudo apt-get install apache2-utils"
        echo "   CentOS: sudo yum install httpd-tools"
        exit 1
    fi

    htpasswd -Bbn "$AUTH_USERNAME" "$AUTH_PASSWORD" > ./registry/auth/htpasswd
    echo "   用户名: $AUTH_USERNAME"
    echo "   密码:   $AUTH_PASSWORD"
fi

# ========= 启动服务 =========
echo "🚀 启动 Docker 服务..."
docker-compose up -d

# ========= 输出提示 =========
SERVER_IP=$(hostname -I | awk '{print $1}')
if [ -z "$SERVER_IP" ]; then
    SERVER_IP="localhost"
fi

echo
echo "✅ 部署完成！"
echo
echo "🔗 服务访问信息："
echo "   Portainer (UI管理): http://$SERVER_IP:$PORTAINER_PORT"
echo "   Registry API:       http://$SERVER_IP:$REGISTRY_PORT/v2/_catalog"
echo
if [ "$ENABLE_AUTH" = "yes" ]; then
    echo "🔒 Registry 已启用认证"
    echo "   推送镜像前请登录: docker login http://$SERVER_IP:$REGISTRY_PORT"
    echo "   用户名: $AUTH_USERNAME"
    echo "   密码:   $AUTH_PASSWORD"
else
    echo "🔓 Registry 未启用认证"
    echo "   如需启用，请修改配置并重新部署"
    echo "   注意：生产环境建议启用认证"
fi
echo
echo "📌 使用示例："
echo "   docker tag hello-world $SERVER_IP:$REGISTRY_PORT/hello-world:latest"
echo "   docker push $SERVER_IP:$REGISTRY_PORT/hello-world:latest"