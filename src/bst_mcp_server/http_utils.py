# http_utils.py

import logging
import json
import requests
import os
from typing import Optional, Dict, Any
from bst_mcp_server.config_util import load_config
from requests.auth import HTTPBasicAuth
from logging.handlers import RotatingFileHandler  # 可选：支持日志轮转
from urllib.parse import urlencode

# 创建 logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False  # 防止日志向上层传播

# 防止重复添加 handler
if not logger.handlers:
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    log_dir = "log"
    os.makedirs(log_dir, exist_ok=True)
    log_filename = os.path.join(log_dir, f"{__name__.split('.')[-1]}.log")

    # 使用 RotatingFileHandler 防止日志文件过大
    file_handler = RotatingFileHandler(
        log_filename, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# --- end 日志配置 ---


def render_template(template: dict, **kwargs) -> dict:
    """
    渲染模板，递归替换 ${variable} 占位符（支持嵌套 dict 和 list）

    :param template: 原始模板字典
    :param kwargs: 用于替换变量的参数（可以是嵌套结构）
    :return: 渲染后的字典
    """

    def _render_value(value):
        if isinstance(value, dict):
            return {k: _render_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_render_value(v) for v in value]
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1].strip()

            # 支持 dot 表示法取值
            parts = var_name.split(".")
            current = kwargs
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return value  # 找不到则保留原字符串
            return current
        else:
            return value

    return _render_value(template)


# ... existing code ...


def call_restful_api(
    config_root: str,
    api_endpoint: str,
    header_params: Dict[str, Any] = None,
    request_params: Dict[str, Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    调用 RESTful API，支持 GET/POST，根据配置自动识别请求方式

    :param config_root: 配置根路径（如 "jira"）
    :param api_endpoint: 接口名（如 "jira-timesheet-leave"）
    :param header_params: 自定义请求头
    :param request_params: 请求参数
    :return: JSON 响应 或 None
    """
    logger.info(f"开始调用API: config_root={config_root}, api_endpoint={api_endpoint}")

    config = load_config().get(config_root, {})
    if not config:
        error_msg = f"未找到配置根路径: {config_root}"
        logger.error(error_msg)
        return {"error": error_msg}

    api_endpoint_config = config.get(api_endpoint, {})
    if not api_endpoint_config:
        error_msg = f"未找到API端点配置: {api_endpoint}"
        logger.error(error_msg)
        return {"error": error_msg}

    # 获取接口基础 URL + path
    base_url = config.get("url")
    if not base_url:
        error_msg = f"Base URL not configured for {config_root}"
        logger.error(error_msg)
        return {"error": error_msg}

    endpoint_path = api_endpoint_config.get("path", "")
    url = f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"

    # 添加日志输出用于调试
    # print(f"Calling API: {api_endpoint}")
    # print(f"Base URL: {base_url}")
    # print(f"Endpoint Path: {endpoint_path}")
    # print(f"Final URL: {url}")

    # 获取认证信息
    auth = None
    auth_config = api_endpoint_config.get("auth")
    if auth_config and auth_config.get("type") == "basic":
        auth = HTTPBasicAuth(auth_config["username"], auth_config["password"])
        logger.debug("使用Basic认证")

    # 获取请求头
    default_headers = api_endpoint_config.get("headers", {})
    headers = {**default_headers, **(header_params or {})}
    logger.debug(f"请求头: {headers}")

    # 获取请求方式，默认为 POST
    method = api_endpoint_config.get("method", "POST").upper()
    logger.info(f"请求方法: {method}")

    template_section = f"{config_root}.{api_endpoint}.requestbody"
    logger.info(f"调用API: {url}")

    try:
        # 根据 method 类型发送请求
        if method == "GET":
            logger.info("发送GET请求")
            # 构建请求参数
            payload = (
                build_request_body(template_section, **(request_params or {})) or {}
            )
            logger.debug(f"请求参数: {payload}")

            # 修改URL参数拼接逻辑，使用requests.utils.urlencode
            filtered_payload = {k: v for k, v in payload.items() if v is not None}

            # 使用标准库来编码参数，确保正确性
            params_str = urlencode(filtered_payload)

            # 改进URL拼接逻辑
            if "?" in url:
                final_url = f"{url}&{params_str}" if params_str else url
            else:
                final_url = f"{url}?{params_str}" if params_str else url

            logger.info(f"发送GET请求到: {final_url}")

            response = requests.get(
                final_url, headers=headers, auth=auth, timeout=30  # 增加超时设置到30秒
            )
        elif method == "POST":
            logger.info("发送POST请求")
            # 发送请求
            response = post_request(
                url,
                headers=headers,
                auth=auth,
                verify=True,  # 启用SSL验证
                template_section=template_section,
                **request_params or {},
            )
        else:
            error_msg = f"不支持的请求方式: {method}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # 添加详细的响应日志
        logger.info(f"响应状态码: {response.status_code}")
        logger.debug(f"响应头: {response.headers}")

        response.raise_for_status()

        try:
            result = response.json()
            logger.debug(f"响应JSON: {result}")
        except json.JSONDecodeError:
            result = {"raw_response": response.text}
            logger.debug("响应不是JSON格式")

        logger.info("API调用成功")
        return result

    except requests.exceptions.Timeout:
        error_msg = "请求超时"
        logger.error(error_msg)
        return {"error": "Request timeout"}
    except requests.exceptions.ConnectionError:
        error_msg = "网络连接异常"
        logger.error(error_msg)
        return {"error": "Network connection error"}
    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP 错误: {e}"
        logger.error(error_msg)
        return {"error": f"HTTP error occurred: {e}"}
    except Exception as e:
        error_msg = f"请求失败: {e}"
        logger.error(error_msg, exc_info=True)
        return {"error": str(e)}


# def call_restful_api(
#     config_root: str,
#     api_endpoint: str,
#     header_params: Dict[str, Any] = None,
#     request_params: Dict[str, Any] = None,
# ) -> Optional[Dict[str, Any]]:
#     config = load_config().get(config_root, {})
#     api_endpoint_config = config.get(api_endpoint, {})
#     url =config.get("url") + api_endpoint_config.get("path")
#     template_section = f"{config_root}.{api_endpoint}.requestbody"

#     auth = api_endpoint_config.get("auth",{})
#     if auth and api_endpoint_config["auth"]["type"] == "basic":
#         auth = HTTPBasicAuth(
#             api_endpoint_config["auth"]["username"], api_endpoint_config["auth"]["password"]
#         )
#     default_headers = api_endpoint_config.get("headers", {})

#     # 合并并覆盖默认 headers
#     headers = {**default_headers, **(header_params or {})}  # dict merge，后者优先级更高

#     # 发送请求
#     response = post_request(
#         url,
#         headers=headers,
#         auth=auth,
#         verify=False,
#         template_section=template_section,
#         **request_params or {},
#     )

#     if response:
#         # 🔁 重定向 stdout 到日志文件
#         sys.stdout = Logger(f"{api_endpoint}")
#         print(json.dumps(response, indent=2, ensure_ascii=False))
#         sys.stdout.close()
#         sys.stdout = sys.__stdout__
#         return response
#     else:
#         print(f"Failed to call {config_root}:{api_endpoint} API.")
#         return None


def build_request_body(template_section: str, **kwargs) -> dict:
    """
    根据 config.yaml 中的模板 section 构建请求体

    :param template_section: config.yaml 中的字段名（如 'jira-timesheet.requestbody'）
    :param kwargs: 替换变量
    :return: 渲染后的请求体
    """
    logger.debug(f"构建请求体: template_section={template_section}")
    config = load_config()
    sections = template_section.split(".")
    template = config

    for sec in sections:
        template = template.get(sec, {})
        if not template:
            logger.warning(f"模板段落未找到: {template_section}")
            return None

    if not isinstance(template, dict):
        error_msg = f"模板 {template_section} 不是一个有效的字典"
        logger.error(error_msg)
        raise ValueError(error_msg)

    payload = render_template(template, **kwargs)
    # 过滤掉 None 或空值字段
    filtered_payload = {
        k: v
        for k, v in payload.items()
        if v is not None
        and v != ""
        and (not isinstance(v, str) or not v.startswith("${"))
    }
    logger.debug(f"构建的请求体: {filtered_payload}")
    return filtered_payload


def post_request(
    url: str,
    headers: Optional[Dict] = None,
    auth: Optional[Any] = None,
    verify: bool = False,
    template_section: Optional[str] = None,
    **kwargs,
):
    """
    发送 POST 请求，支持自动判断 Content-Type，并处理无 payload 的情况

    参数:
        url: 请求地址
        headers: 请求头
        auth: 认证信息 (如 HTTPBasicAuth)
        verify: 是否验证 SSL 证书
        template_section: config.yaml 中模板路径（如 'jira-timesheet.requestbody'）
        kwargs: 用于替换模板变量的参数

    返回:
        JSON 响应内容 或 None
    """
    logger.info(f"准备发送POST请求到: {url}")
    logger.debug(f"请求头: {headers}")
    logger.debug(f"认证信息: {auth}")
    logger.debug(f"验证SSL证书: {verify}")
    logger.debug(f"模板段落: {template_section}")
    logger.debug(f"其他参数: {kwargs}")

    try:
        # 尝试构建 payload
        payload = None
        if template_section:
            logger.info(f"使用模板构建请求体: {template_section}")
            payload = build_request_body(template_section, **kwargs)
            logger.debug(f"构建的请求体: {payload}")
        elif kwargs:
            payload = kwargs  # 直接使用传入的参数作为 payload
            logger.debug(f"使用传入参数作为请求体: {payload}")
        else:
            logger.info("无请求体参数")

        # 构造 headers 默认值
        final_headers = headers.copy() if headers else {}

        # 自动设置 Content-Type（如果没有指定）
        content_type = final_headers.get("Content-Type")
        if not content_type:
            final_headers["Content-Type"] = "application/json"
            content_type = "application/json"  # 同步更新 content_type
            logger.debug("设置默认Content-Type为application/json")

        # 判断是否发送 payload
        if payload and "x-www-form-urlencoded" in content_type:
            logger.info("发送表单数据")
            response = requests.post(
                url,
                data=payload,
                headers=final_headers,
                auth=auth,
                verify=verify,
                timeout=30,
            )
        elif payload:
            logger.info("发送JSON数据")
            response = requests.post(
                url,
                json=payload,
                headers=final_headers,
                auth=auth,
                verify=verify,
                timeout=30,
            )
        else:
            logger.info("发送无请求体请求")
            response = requests.post(
                url, headers=final_headers, auth=auth, verify=verify, timeout=30
            )  # 无 payload

        logger.info(f"收到响应，状态码: {response.status_code}")
        return response

    except requests.exceptions.Timeout:
        error_msg = "请求超时"
        logger.error(error_msg)
        return None
    except requests.exceptions.ConnectionError:
        error_msg = "网络连接异常"
        logger.error(error_msg)
        return None
    except requests.exceptions.RequestException as e:
        error_msg = f"请求失败: {e}"
        logger.error(error_msg, exc_info=True)
        return None
    except Exception as e:
        error_msg = f"未知错误: {e}"
        logger.error(error_msg, exc_info=True)
        return None
