import os
import multiprocessing
import asyncio
import threading
import logging

from flask import Flask, send_from_directory

from bst_mcp_server.bst_hr_mcp_server import bst_hr_mcp_server
from bst_mcp_server.bst_pm_info_mcp_server import bst_pm_info_mcp_server
from bst_mcp_server.bst_pm_workload_mcp_server import bst_pm_workload_mcp_server
from bst_mcp_server.config_util import load_config


# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_pm_server.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ========== 配置路径 ==========
CURRENT_FILE_PATH = os.path.abspath(__file__)
PROJECT_MODULE_DIR = os.path.dirname(CURRENT_FILE_PATH)
PROJECT_SRC = os.path.dirname(PROJECT_MODULE_DIR)
PROJECT_ROOT = os.path.dirname(PROJECT_SRC)
STATIC_FOLDER = os.path.join(PROJECT_ROOT, "visualizations")


# ========== Flask 静态文件服务 ==========
def create_static_file_server():
    logger.info("创建Flask静态文件服务器")
    app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path="")

    @app.route("/<path:filename>")
    def serve_static(filename):
        logger.debug(f"处理静态文件请求: {filename}")
        requested_path = os.path.join(app.static_folder, filename)
        if not os.path.exists(requested_path):
            logger.warning(f"文件未找到: {filename}")
            return "File not found", 404
        if not os.path.isfile(requested_path):
            logger.warning(f"路径不是文件: {filename}")
            return "Not a file", 400
        logger.debug(f"成功提供静态文件: {filename}")
        return send_from_directory(app.static_folder, filename)

    return app


# ========== 启动 Flask 服务 ==========
def run_static_file_server(host="0.0.0.0", port=8000):
    logger.info(f"启动Flask静态文件服务器: host={host}, port={port}")
    app = create_static_file_server()
    try:
        app.run(host=host, port=port)
        logger.info("Flask静态文件服务器已启动")
    except Exception as e:
        logger.error(f"启动Flask静态文件服务器时发生错误: {e}", exc_info=True)


# ========== 启动 MCP 服务 ==========
def run_mcp_server(mcp_server, name, host="0.0.0.0", port=8001):
    logger.info(f"启动MCP服务: name={name}, host={host}, port={port}")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info(f"MCP服务 {name} 开始运行")
        loop.run_until_complete(mcp_server.run(transport="streamable-http"))
        logger.info(f"MCP服务 {name} 运行完成")
    except Exception as e:
        logger.error(f"MCP服务 {name} 运行时发生错误: {e}", exc_info=True)
    finally:
        loop.close()
        logger.info(f"MCP服务 {name} 的事件循环已关闭")


# ========== 主函数：启动多个进程 ==========
def main():
    logger.info("启动BST PM服务器主程序")
    server_config = load_config().get("server_config", {})
    static_config = server_config.get("static_file_server", {})
    mcp_info_config = server_config.get("mcp_info_server", {})
    mcp_workload_config = server_config.get("mcp_workload_server", {})

    # 创建进程
    processes = []

    # Flask 静态服务
    logger.info("创建Flask静态服务进程")
    flask_process = multiprocessing.Process(
        target=run_static_file_server,
        kwargs={
            "host": "0.0.0.0",
            "port": 8000,
        },
        name="FlaskStaticServer",
    )

    # MCP Info 服务
    logger.info("创建MCP Info服务进程")
    mcp_info_process = multiprocessing.Process(
        target=run_mcp_server,
        args=(bst_pm_info_mcp_server,),
        kwargs={
            "name": "MCP-Info",
            "host": "0.0.0.0",
            "port": 8001,
        },
        name="MCP-PM-InfoServer",
    )

    # MCP Workload 服务
    logger.info("创建MCP Workload服务进程")
    mcp_workload_process = multiprocessing.Process(
        target=run_mcp_server,
        args=(bst_pm_workload_mcp_server,),
        kwargs={
            "name": "MCP-Workload",
            "host": "0.0.0.0",
            "port": 8002,
        },
        name="MCP-PM-WorkloadServer",
    )

    # MCP HR 服务
    logger.info("创建MCP HR服务进程")
    mcp_hr_process = multiprocessing.Process(
        target=run_mcp_server,
        args=(bst_hr_mcp_server,),
        kwargs={
            "name": "MCP-HR",
            "host": "0.0.0.0",
            "port": 8003,
        },
        name="MCP-HR-Server",
    )

    def run_bst_pm_info_mcp_server():
        logger.info("启动BST PM Info MCP服务器线程")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            logger.info("BST PM Info MCP服务器开始运行")
            loop.run_until_complete(
                bst_pm_info_mcp_server.run(transport="streamable-http")
            )
            logger.info("BST PM Info MCP服务器运行完成")
        except Exception as e:
            logger.error(f"BST PM Info MCP服务器运行时发生错误: {e}", exc_info=True)
        finally:
            loop.close()
            logger.info("BST PM Info MCP服务器的事件循环已关闭")

    run_bst_pm_info_mcp_server_thread = threading.Thread(
        target=run_bst_pm_info_mcp_server
    )
    # run_bst_pm_info_mcp_server_thread.start()

    # 添加进程并启动
    processes.append(flask_process)
    processes.append(mcp_info_process)
    processes.append(mcp_hr_process)
    processes.append(mcp_workload_process)

    logger.info("启动所有进程")
    for p in processes:
        p.start()

    logger.info("等待所有进程完成")
    for p in processes:
        p.join()
    # run_bst_pm_info_mcp_server_thread.join()

    logger.info("所有服务已关闭")


if __name__ == "__main__":
    main()
