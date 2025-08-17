 **可发布的 Python 包** 和对应的 **Docker 镜像**，以便你方便部署和运行这个项目

---

## 📦 一、生成可发布的 Python 包

我们使用 `setuptools` 来打包项目为 `.whl` 或 `.tar.gz` 文件。

### ✅ 步骤 1：创建 `setup.py`

在项目根目录下新建文件 `setup.py`：

```python
# setup.py
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="bst_mcp_server",
    version="0.1.0",
    author="Ryan",
    author_email="your@email.com",
    description="A mcp tool for bst_pm_mcp",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourname/bst_pm_mcp_server",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    install_requires=[
        "requests>=2.25.1",
        "python-dateutil>=2.8.1",
        "graphviz>=0.19.1"
    ],
    entry_points={
        'console_scripts': [
            'bst_pm_mcp_server=main:main',
        ],
    },
)
```

> ⚠️ 注意：确保你的代码结构中有一个 `__init__.py` 文件（即使为空）来支持 `find_packages()`。

---

### ✅ 步骤 2：添加 `README.md`（可选）

```markdown
# Critical Path Analyzer

这是一个从 Jira 导出任务并分析关键路径的工具。
```

---

### ✅ 步骤 3：构建包

```bash
pip install setuptools wheel
python setup.py sdist bdist_wheel
```

构建完成后，你会在 `dist/` 目录下看到两个文件：
- `critical_path_analyzer-0.1.0.tar.gz`
- `critical_path_analyzer-0.1.0-py3-none-any.whl`

---

### ✅ 步骤 4：安装本地包测试

```bash
pip install dist/critical_path_analyzer-0.1.0-py3-none-any.whl
```

然后你可以直接运行命令：

```bash
bst_pm_mcp_server
```

---

## 🐳 二、构建 Docker 镜像

我们可以基于官方 Python 镜像来打包整个项目。

### ✅ 步骤 1：创建 `Dockerfile`

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

### ✅ 步骤 2：构建镜像

```bash
docker build -t bst_pm_mcp_server:latest .
```

---

### ✅ 步骤 3：运行容器

```bash
docker run --rm bst_pm_mcp_server:latest
```

如果你需要挂载配置文件或输出结果到宿主机：

```bash
docker run --rm \
  -v $(pwd)/output:/app/output \
  bst_pm_mcp_server:latest
```

你可以在 `main.py` 中把可视化图保存到 `/app/output/project_graph.png`，这样就可以在宿主机看到输出了。

---

## 🧪 三、完整目录结构建议

```
critical_path/
├── critical_path.py
├── data_processor.py
├── main.py
├── field_mapping.json
├── requirements.txt
├── setup.py
├── README.md
└── __init__.py
```

---

## 📦 四、发布到 PyPI（可选）

如果你想发布到 [PyPI](https://pypi.org/)，可以这样做：

```bash
pip install twine
twine upload dist/*
```

你需要先注册账号，并使用 API token 推送。

---

## ✅ 总结

| 功能 | 命令 |
|------|------|
| 构建 Python 包 | `python setup.py sdist bdist_wheel` |
| 安装本地包 | `pip install dist/*.whl` |
| 构建 Docker 镜像 | `docker build -t bst_pm_mcp_server .` |
| 运行容器 | `docker run bst_pm_mcp_server` |

---

如需我帮你：
- 自动生成 `__init__.py`
- 支持配置化输出路径（如 `/output`）
- 自动上传到私有仓库或 GitHub Packages


# 安装依赖
```
sudo apt update

sudo apt install -y \
    make \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libffi-dev \
    libncurses-dev \
    libncurses5-dev \
    libncursesw5-dev \
    libnsl-dev \
    libdb-dev \
    tk-dev \
    libgdbm-dev \
    liblzma-dev \
    uuid-dev \
    libexpat1-dev \
    xz-utils \
    wget \
    curl \
    llvm \
    python3-openssl \
    git
```
# 安装 pyenv
```
git clone https://github.com/pyenv/pyenv.git ~/.pyenv
```
# 配置环境变量（添加到 .bashrc 或 .zshrc）
```
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init --path)"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc
```
# 重新加载配置
```
source ~/.bashrc
```
# 安装 Python 3.12
```
pyenv install 3.12.3
```
# 设置全局版本
```
pyenv global 3.12.3
```



---

## 🧩 一图看懂：pyenv vs .venv

| 工具 | 类型 | 功能 | 粒度 | 示例 |
|------|------|------|------|------|
| `pyenv` | **Python 版本管理器** | 安装和切换多个 Python 解释器版本 | 全局/用户级 | 切换 Python 3.10、3.11、3.12 |
| `.venv`（或 `venv`） | **虚拟环境工具** | 在一个 Python 版本下创建隔离的开发环境 | 项目级 | 每个项目有自己的依赖包 |

---

## 📌 1. pyenv：Python 版本管理器

### ✅ 用途：
- 安装多个 Python 版本（如 3.8、3.9、3.10、3.11、3.12）
- 在这些版本之间快速切换
- 不影响系统自带的 Python（避免污染）

### 🔧 常用命令：

```bash
pyenv install 3.12.11     # 安装 Python 3.12.11
pyenv global 3.12.11      # 设置全局默认 Python 版本
pyenv local 3.11.10       # 在当前目录设置本地使用的 Python 版本
pyenv versions            # 查看已安装的版本
```

### 📁 文件结构示例：

```
~/.pyenv/versions/
├── 3.10.13/
├── 3.11.10/
└── 3.12.11/   ← 每个目录是一个完整的 Python 安装
```

---

## 📦 2. venv / .venv：虚拟环境（Virtual Environment）

### ✅ 用途：
- 在一个 Python 版本下为每个项目创建独立的依赖环境
- 避免不同项目之间的依赖冲突（比如 A 项目用 Flask 2.0，B 项目用 Flask 3.0）
- 可以有多个 `.venv` 目录，每个对应一个项目的环境

### 🔧 创建虚拟环境：

```bash
python -m venv .venv        # 使用当前 Python 创建虚拟环境
source .venv/bin/activate   # 激活虚拟环境
```

激活后提示符会变成这样：

```
(.venv) $
```

退出虚拟环境：

```bash
deactivate
```

### 📁 文件结构示例：

```
your-project/
├── .venv/         ← 虚拟环境目录
│   ├── bin/
│   │   ├── python
│   │   └── pip
│   └── lib/python3.x/site-packages/
├── your_code.py
└── requirements.txt
```

---

## 🔄 关系总结：pyenv + venv 可以一起使用！

你可以结合两者来实现**多版本 + 多项目隔离**的完美组合：

1. 用 `pyenv` 安装并切换 Python 3.12
2. 进入你的项目目录
3. 用 `python -m venv .venv` 创建虚拟环境
4. 激活 `.venv` 并安装项目依赖

> 👍 推荐工作流：
>
> ```bash
> pyenv local 3.12.11          # 使用 3.12
> python -m venv .venv         # 创建虚拟环境
> source .venv/bin/activate    # 激活
> pip install -r requirements.txt
> ```

---

## 🧠 常见误区澄清

| 错误理解 | 正确解释 |
|----------|-----------|
| `pyenv` 是用来创建虚拟环境的 | ❌ `pyenv` 是用来管理 Python 解释器版本的 |
| `.venv` 会改变系统的 Python 版本 | ❌ `.venv` 只影响当前项目的 Python 和依赖路径 |
| 我只需要 `venv` 就可以管理所有 Python | ❌ 如果你需要多个 Python 版本，必须用 `pyenv` |
| 有了 `pyenv` 就不需要 `venv` | ❌ `pyenv` 管理版本，`venv` 管理项目依赖，二者互补 |

---

## ✅ 总结对比表

| 对比项 | pyenv | venv / .venv |
|--------|-------|---------------|
| 中文名 | Python 版本管理器 | 虚拟环境工具 |
| 作用 | 切换 Python 解释器版本 | 隔离项目依赖 |
| 是否影响系统 Python | 否 | 否 |
| 是否需要安装 | 是（需从 GitHub 安装） | 否（Python 3.3+ 自带） |
| 使用场景 | 多 Python 版本共存 | 多项目依赖隔离 |
| 示例目录 | `~/.pyenv/versions/3.12.11` | `.venv/` |
| 是否需要激活 | 否 | 是（`source .venv/bin/activate`） |

---


非常棒！你已经成功安装了 `mcp`，并且它位于你的虚拟环境目录中：

```
/home/zhanghong/work/git/servers-archived/src/sqlite/.venv/lib/python3.12/site-packages
```

这也是为什么你运行：

```bash
mcp dev src/mcp_server_sqlite/server.py:wrapper
```

会提示：

```
bash: mcp: command not found
```

是因为你**没有激活虚拟环境**，所以系统找不到 `.venv/bin/mcp` 这个可执行文件。

---

## ✅ 解决方案

### ✅ 方法 1：激活虚拟环境后再运行命令（推荐）

```bash
source .venv/bin/activate
```

激活后，你的终端提示符通常会变成这样：

```
(.venv) zhanghong@...
```

然后再次运行：

```bash
mcp dev src/mcp_server_sqlite/server.py:wrapper
```

应该就能正常运行了 ✅

---

### ✅ 方法 2：使用完整路径直接调用（不激活虚拟环境）

如果你不想激活虚拟环境，也可以直接使用虚拟环境中的 `mcp` 命令：

```bash
./.venv/bin/mcp dev src/mcp_server_sqlite/server.py:wrapper
```

或者绝对路径方式：

```bash
/home/zhanghong/work/git/servers-archived/src/sqlite/.venv/bin/mcp \
    dev src/mcp_server_sqlite/server.py:wrapper
```

---

### ✅ 方法 3：使用 `uv run` 直接运行（无需激活）

因为你是通过 `uv` 安装的包，可以直接使用：

```bash
uv run mcp dev src/mcp_server_sqlite/server.py:wrapper
```

这会自动使用当前项目的虚拟环境或依赖项来运行命令。

---

## 🧠 小贴士：关于 uv + venv 的工作流程

| 操作 | 命令 |
|------|------|
| 创建虚拟环境 | `uv venv` |
| 激活虚拟环境 | `source .venv/bin/activate` |
| 安装 CLI 工具 | `uv add "mcp[cli]"` |
| 查看是否安装成功 | `uv pip show mcp` |
| 直接运行 CLI | `uv run mcp ...` |
| 使用完整路径运行 | `.venv/bin/mcp ...` |

---

## ✅ 验证是否一切正常

你可以先运行：

```bash
source .venv/bin/activate
mcp --help
```


uv run --directory /home/zhanghong/work/git/critical_path_jira bst_pm_mcp_server

# Pass arguments only
npx @modelcontextprotocol/inspector uv run --directory /home/zhanghong/work/git/critical_path_jira bst_pm_mcp_server



# 构建镜像（仅第一次较慢，后续有缓存）
docker build -t bst_pm_mcp_server .

# 运行容器
docker run --rm -it -p 8000:8000 bst_pm_mcp_server
