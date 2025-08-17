# config_util.py
import json
import os
import yaml
import logging
from dotenv import load_dotenv

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "config_util.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 自动加载.env文件
load_dotenv()


def load_config(config_file=None):
    """
    从指定路径加载 YAML 配置文件，并进行变量替换。

    参数：
        config_file: str, 配置文件路径（可选）。如果未提供，则使用默认路径。

    返回：
        dict: 加载后的配置字典
    """
    logger.info("开始加载配置文件")
    # 如果未传入 config_file，则使用默认路径
    config_file = os.getenv("BST_MCP_CONFIG_FILE")
    if config_file is None:
        # 获取当前模块所在目录，然后拼接到 config 目录下的 config.yaml
        current_dir = os.path.dirname(__file__)
        config_file = os.path.join(current_dir, "config", "config.yaml")
        logger.debug(f"使用默认配置文件路径: {config_file}")

    logger.info(f"加载配置文件: {config_file}")
    if not os.path.exists(config_file):
        error_msg = f"配置文件 {config_file} 不存在"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.info("配置文件加载成功")
        return config
    except Exception as e:
        logger.error(f"加载配置文件时出错: {e}")
        raise


def _get_config_value(config: dict, key: str, env_var: str) -> str:
    """
    从配置或环境变量中获取值

    :param config: 配置字典
    :param key: 配置键名
    :param env_var: 对应的环境变量名
    :return: 配置值
    """
    value = config.get(key)
    # 如果值是环境变量占位符格式，则从环境变量中获取
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_key = value[2:-1]  # 去掉 ${ 和 }
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value
    return value


def load_field_mapping(config_file=None):
    """
    从指定路径加载 field_mapping 配置文件，并进行变量替换。

    参数：
        config_file: str, 配置文件路径（可选）。如果未提供，则使用默认路径。

    返回：
        dict: 加载后的配置字典
    """
    logger.info("开始加载字段映射配置文件")
    # 如果未传入 config_file，则使用默认路径
    if config_file is None:
        # 获取当前模块所在目录，然后拼接到 config 目录下的 config.yaml
        current_dir = os.path.dirname(__file__)
        config_file = os.path.join(
            current_dir, "config", "jira_task_field_mapping.json"
        )
        logger.debug(f"使用默认字段映射文件路径: {config_file}")

    logger.info(f"加载字段映射文件: {config_file}")
    if not os.path.exists(config_file):
        error_msg = f"配置文件 {config_file} 不存在"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    try:
        with open(config_file, encoding="utf-8") as f:
            field_mapping = json.load(f)
        logger.info("字段映射文件加载成功")
        return field_mapping
    except Exception as e:
        logger.error(f"加载字段映射文件时出错: {e}")
        raise
