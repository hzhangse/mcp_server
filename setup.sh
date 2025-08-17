#!/bin/bash

# 在脚本开头添加set -e，使脚本在出现错误时立即退出
set -e

# 检查是否是 root 用户，如果不是则使用 sudo
SUDO=''
if (( $EUID != 0 )); then
    SUDO='sudo'
fi

# 获取操作系统类型
OS="$(uname -s)"
case "$OS" in
    Linux*)     OS=Linux;;
    Darwin*)    OS=macOS;;
    CYGWIN*)    OS=Windows;;
    MINGW*)     OS=Windows;;
    *)          OS="Unknown";;
esac

# 包文件路径
PACKAGE_FILE="dist/*.whl"
DOCKER_IMAGE_NAME="bst_mcp_server"
DOCKER_CONTAINER_NAME="bst-mcp-server"

# 新增：日志记录函数
log() {
    local level=$1
    local message=$2
    local timestamp=$(date +"%Y-%m-%d %T")
    echo "[$timestamp] [$level] $message"
}

# 新增：检查pyenv是否存在，如果不存在则安装
setup_pyenv() {
    log "INFO" "Setting up pyenv..."
    if ! command -v pyenv &> /dev/null; then
        log "INFO" "Installing pyenv..."
        if [ "$OS" = "macOS" ]; then
            brew install pyenv
        else
            curl https://pyenv.run | bash
        fi
    fi
    
    # 将pyenv添加到PATH
    export PATH="$HOME/.pyenv/bin:$PATH"
    eval "$(pyenv init --path)"
    eval "$(pyenv init -)"
    log "INFO" "pyenv setup completed"
}

# 修改install_python函数（原函数修改）
install_python() {
    local PYTHON_VERSION=${1:-3.12.11}  # 默认版本改为3.12与pyproject.toml一致
    
    log "INFO" "Installing Python $PYTHON_VERSION using pyenv..."
    
    # 安装依赖（原内容保持不变）
    if [ "$(command -v apt)" ]; then
        $SUDO apt install -y build-essential libssl-dev zlib1g-dev \
        libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
        libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
        elif [ "$(command -v dnf)" ]; then
        $SUDO dnf install -y git gcc make openssl-devel bzip2-devel \
        readline-devel sqlite-devel xz-devel libffi-devel
        elif [ "$OS" = "macOS" ]; then
        # macOS需要额外安装Xcode命令行工具
        xcode-select --install || true
    fi
    
    # 安装指定版本
    pyenv install -s "$PYTHON_VERSION"
    pyenv global "$PYTHON_VERSION"
    log "INFO" "Python $(pyenv version-name) installed successfully"
}


install_package() {
    log "INFO" "Building Python package..."
    # 使用pyenv指定的版本创建虚拟环境
    python -m venv venv
    
    # 激活虚拟环境
    source venv/bin/activate
    
    
    log "INFO" "Upgrading pip and installing package..."
    pip install --upgrade pip
    # 检查build工具是否已安装
    # if ! python -c "import build" &> /dev/null; then
    #     log "INFO" "Installing build tools..."
    #     pip install --no-cache-dir build
    # fi
    # 构建包
    #python -m build --wheel
    
    # 安装构建好的wheel包
    #pip install dist/*.whl
    # 安装 uv
    pip install uv
    uv build --wheel .
    WHEEL_FILE=$(ls dist/*.whl | head -1)
    uv pip install "$WHEEL_FILE"
    #pip install -e .
    log "INFO" "Package installed in development mode"

}

# 修改uninstall_python函数（新增版本参数支持）
uninstall_python() {
    local PYTHON_VERSION=${1:-3.12.11}  # 版本与pyproject.toml一致
    
    log "INFO" "Uninstalling Python $PYTHON_VERSION..."
    
    if command -v pyenv &> /dev/null; then
        pyenv uninstall -f "$PYTHON_VERSION"  # 强制卸载
    else
        log "WARN" "pyenv not found, skipping Python version removal"
    fi
    
    log "INFO" "Python $PYTHON_VERSION uninstalled"
}

# 函数：打印帮助信息
usage() {
    echo "Usage: $0 {install|uninstall|build|run|stop|clean} [python_version]"
    echo "  install     : 安装系统依赖并安装 Python 包"
    echo "  uninstall   : 卸载 Python 包和系统依赖"
    echo "  build       : 构建 Python 包"
    echo "  build-image : 构建 Docker 镜像"
    echo "  run         : 运行 Docker 容器"
    echo "  stop        : 停止 Docker 容器"
    echo "  clean       : 删除 Docker 容器和镜像"
    echo "  python_version : 可选参数，指定 Python 版本（如 3.12.11）"
    exit 1
}

# 函数：安装 Graphviz（保持不变）
install_graphviz() {
    echo "Installing Graphviz..."
    if [ "$(command -v apt)" ]; then
        $SUDO apt install -y graphviz
        elif [ "$(command -v dnf)" ]; then
        $SUDO dnf install -y graphviz
        elif [ "$(command -v brew)" ]; then
        brew install graphviz
        elif [ "$(command -v choco)" ]; then
        choco install graphviz -y
    else
        echo "Unsupported OS for Graphviz installation."
        exit 1
    fi
}

# 函数：卸载 Python 包（保持不变）
uninstall_package() {
    echo "Uninstalling Python package..."
    if [ -d "venv" ]; then
        source venv/bin/activate || source venv/Scripts/activate
        pip uninstall -y bst-mcp-server || echo "No package installed or failed to uninstall."
        rm -rf venv
    fi
}

# 函数：卸载 Graphviz（保持不变）
uninstall_graphviz() {
    echo "Uninstalling Graphviz..."
    if [ "$(command -v apt)" ]; then
        $SUDO apt remove -y graphviz
        elif [ "$(command -v dnf)" ]; then
        $SUDO dnf remove -y graphviz
        elif [ "$(command -v brew)" ]; then
        brew uninstall graphviz
        elif [ "$(command -v choco)" ]; then
        choco uninstall graphviz -y
    else
        echo "Unsupported OS for Graphviz uninstallation."
    fi
}

# 函数：构建 Docker 镜像（修改为使用多阶段构建）
build_docker_image() {
    echo "Building Docker image..."
    if [ ! -f "Dockerfile" ]; then
        echo "Error: Dockerfile not found!"
        exit 1
    fi
    
    # 直接构建Docker镜像，让Dockerfile内部处理包构建
    $SUDO docker build -t $DOCKER_IMAGE_NAME .
}

# 函数：启动 Docker 容器（修改容器端口映射）
run_docker_container() {
    echo "Starting Docker container..."
    if docker ps -a | grep -q $DOCKER_CONTAINER_NAME; then
        echo "Container already exists, starting it..."
        $SUDO docker start $DOCKER_CONTAINER_NAME
    else
        echo "Creating and running new container..."
        $SUDO docker run -d --name $DOCKER_CONTAINER_NAME \
        -v ./config-prod.yaml:/app/config/config.yaml \
        -e BST_MCP_CONFIG_FILE=/app/config/config.yaml \
        -p 8000:8000 \
        -p 8001:8001 \
        -p 8002:8002 \
        --init \
        $DOCKER_IMAGE_NAME
    fi
}

# 函数：停止 Docker 容器（保持不变）
stop_docker_container() {
    echo "Stopping Docker container..."
    $SUDO docker stop $DOCKER_CONTAINER_NAME 2>/dev/null || echo "Container not running or does not exist."
}

# 函数：删除容器和镜像（保持不变）
clean_docker_artifacts() {
    echo "Cleaning up Docker artifacts..."
    stop_docker_container
    $SUDO docker rm $DOCKER_CONTAINER_NAME 2>/dev/null || echo "No container to remove."
    $SUDO docker rmi $DOCKER_IMAGE_NAME 2>/dev/null || echo "No image to remove."
}

# 主逻辑
if [ $# -lt 1 ]; then
    usage
fi

ACTION="$1"

case "$ACTION" in
    install)
        log "INFO" "Starting installation..."
        
        # 新增：检查是否提供了Python版本参数
        if [ -n "${2}" ]; then
            PYTHON_VERSION="${2}"
        else
            PYTHON_VERSION="3.12.11"
        fi
        
        setup_pyenv
        install_python "$PYTHON_VERSION"
        install_graphviz
        install_package
        
        log "INFO" "Installation completed successfully."
    ;;
    uninstall)
        log "INFO" "Starting uninstallation..."
        
        # 新增：允许传递要卸载的Python版本
        if [ -n "${2}" ]; then
            PYTHON_VERSION="${2}"
        else
            PYTHON_VERSION="3.12.11"
        fi
        
        uninstall_package
        uninstall_graphviz
        uninstall_python "$PYTHON_VERSION"
        
        log "INFO" "Uninstallation completed successfully."
    ;;
    build)
        install_package
    ;;
    build-image)
        build_docker_image
    ;;
    run)
        run_docker_container
    ;;
    stop)
        stop_docker_container
    ;;
    clean)
        clean_docker_artifacts
    ;;
    *)
        usage
    ;;
esac