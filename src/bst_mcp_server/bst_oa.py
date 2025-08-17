# BstOA.py

import asyncio
from datetime import datetime, timedelta
import json
import logging
import os
import random
from typing import Optional, Dict, Any
from base64 import b64encode
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from typing import List, Dict, Any

# 假设这些模块已经在项目中定义好
from bst_mcp_server.http_utils import call_restful_api, post_request
from bst_mcp_server.config_util import _get_config_value, load_config
from bst_mcp_server.holiday_util import date_range
from bst_mcp_server.redis_utils import RedisUtils
from datetime import datetime

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_oa.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

config_root = "bst_oa"


def rsa_encrypt(public_key: str, plaintext: str) -> str:
    """
    使用 RSA 公钥加密明文字符串

    :param public_key: PEM 格式的公钥字符串
    :param plaintext: 要加密的明文
    :return: Base64 编码的密文
    """
    # 如果没有 '-----BEGIN PUBLIC KEY-----' 头部，则手动加上
    if not public_key.startswith("-----"):
        public_key = (
            "-----BEGIN PUBLIC KEY-----\n" + public_key + "\n-----END PUBLIC KEY-----"
        )

    key = RSA.import_key(public_key)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plaintext.encode())
    return b64encode(encrypted).decode()


class BstOA:

    _instance = None  # 用于保存单例实例

    def __new__(cls, *args, **kwargs):
        """实现单例模式的__new__方法"""
        if cls._instance is None:
            cls._instance = super(BstOA, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """
        初始化 BstOA 实例，从配置文件中加载 OA 接口信息
        """
        logger.info("初始化BstOA实例")
        self.config = load_config().get(config_root, {})
        self.app_id = self.config.get("app_id")
        self.spk = _get_config_value(self.config, "spk", "oa.spk")
        self.skipsession = self.config.get("skipsession")
        self.token = None

        # 使用 spk 公钥加密 userid,使用 spk 公钥加密 secret
        try:
            self.user_id = rsa_encrypt(self.spk, self.config.get("user_id"))
            self.app_secret = rsa_encrypt(
                self.spk, _get_config_value(self.config, "app_secret", "oa.app_secret")
            )
            # 获取 token
            self.get_access_token()
            # 标记为已初始化
            RedisUtils.get_instance()
            self.initialized = True
            logger.info("BstOA实例初始化完成")
        except Exception as e:
            logger.error(f"_init_ oa initialized 失败: {e}")
            return None

    @classmethod
    def get_instance(cls) -> "BstOA":
        """获取单例实例的方法"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_access_token(self) -> Optional[str]:
        """
        2. 向 OA 系统发送获取 Token 请求（改进版）
        使用 appid、time、RSA 加密 secret 进行认证
        """
        logger.info("获取访问令牌")
        if not self.spk:
            error_msg = "SPK not generated. Please call register_auth first."
            logger.error(error_msg)
            raise Exception(error_msg)

        applytoken_config = self.config.get("applytoken", {})
        url = self.config.get("url") + applytoken_config.get("path")
        headers = applytoken_config.get("headers", {})

        # 获取请求参数
        time = headers.get("time", "1800")  # 默认 1800 秒

        # 构造请求体
        headers = {"appid": self.app_id, "time": time, "secret": self.app_secret}

        # 发送请求
        response = post_request(
            url,
            headers=headers,
            verify=False,
        )

        if response is None:
            logger.error("获取访问令牌失败，响应为空")
            return None

        try:
            result = response.json()
        except Exception as e:
            logger.error(f"解析访问令牌响应失败: {e}")
            return None

        if result and "token" in result:
            self.token = result["token"]
            logger.info("访问令牌获取成功")
            return self.token
        else:
            logger.error("获取访问令牌失败")
            return None

    # def call_ecology_api(
    #     self,
    #     api_endpoint: str,
    #     header_params: Dict[str, Any] = None,
    #     request_params: Dict[str, Any] = None,
    # ) -> Optional[Dict[str, Any]]:
    #     """
    #     3. 使用 Token 认证调用 ECOLOGY 系统业务接口

    #     :param api_endpoint: 接口路径（如 "/business/task/list"）
    #     :param header_params: 自定义请求头参数，用于覆盖默认值
    #     :param request_params: 请求参数
    #     :return: API 响应数据
    #     """
    #     logger.info(f"调用ECOLOGY系统API: {api_endpoint}")
    #     if not self.token:
    #         error_msg = "Token not obtained. Please call get_access_token first."
    #         logger.error(error_msg)
    #         raise Exception(error_msg)

    #     api_endpoint_config = self.config.get(api_endpoint, {})
    #     url = self.config.get("url") + api_endpoint_config.get("path")
    #     template_section = f"{config_root}.{api_endpoint}.requestbody"

    #     # 构建默认 headers
    #     default_headers = {
    #         "token": self.token,
    #         "appid": self.app_id,
    #         "userid": self.user_id,
    #         "skipsession": self.skipsession,
    #     }

    #     # 合并并覆盖默认 headers
    #     headers = {
    #         **default_headers,
    #         **(header_params or {}),
    #     }  # dict merge，后者优先级更高

    #     # 发送请求
    #     response = post_request(
    #         url,
    #         headers=headers,
    #         verify=False,
    #         template_section=template_section,
    #         **request_params or {},
    #     )

    #     if response:
    #         logger.info(f"API调用成功: {api_endpoint}")
    #         return response
    #     else:
    #         logger.error(f"Failed to call {api_endpoint} ECOLOGY API.")
    #         return None

    def get_userInfo(self, assignee: str):
        logger.info(f"获取用户信息: {assignee}")
        userInfo = RedisUtils.get_instance().get_data(f"userInfo:{assignee}")
        if userInfo is None:
            logger.info(f"用户信息未在缓存中找到，从API获取: {assignee}")
            oa = BstOA.get_instance()
            username = extract_username(assignee)

            _headers = {
                "token": oa.token,
                "appid": oa.app_id,
                "userid": oa.user_id,
                "skipsession": oa.skipsession,
            }

            params = {"params": {"loginid": username}}

            response_data = call_restful_api(
                config_root,
                api_endpoint="getHrmUserInfo",
                header_params=_headers,
                request_params=params,
            )

            # 严谨判断response_data结构和id字段是否存在
            if (
                response_data
                and isinstance(response_data, dict)
                and "data" in response_data
                and isinstance(response_data["data"], dict)
                and "dataList" in response_data["data"]
                and isinstance(response_data["data"]["dataList"], list)
                and len(response_data["data"]["dataList"]) > 0
            ):

                userInfo = response_data["data"]["dataList"][0]
                RedisUtils.get_instance().set_data(f"userInfo:{assignee}", userInfo)
                logger.info(f"用户信息获取并缓存成功: {assignee}")

        return userInfo

    async def fetch_kq_data_for_date(
        self, date: datetime, assignee: str, id_value: str
    ):
        current_date = date.strftime("%Y-%m-%d")
        logger.info(f"获取考勤数据: assignee={assignee}, date={current_date}")

        # 1. 查 Redis 缓存
        userKqInfo = RedisUtils.get_instance().get_data_with_date(
            f"userKqInfo:{assignee}", current_date
        )

        if userKqInfo is not None:
            logger.info(
                f"从Redis缓存获取到考勤数据: assignee={assignee}, date={current_date}"
            )
            return current_date, userKqInfo

        logger.info(
            f"Redis缓存中未找到考勤数据，从API获取: assignee={assignee}, date={current_date}"
        )

        _headers = {
            "token": self.token,
            "appid": self.app_id,
            "userid": self.user_id,
            "skipsession": self.skipsession,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        headers = {**_headers, **(headers or {})}
        # 2. 构建参数并调用 API
        params = {
            "kqDate": current_date,
            "resourceId": id_value,
        }

        kq_data = call_restful_api(
            config_root,
            api_endpoint="getKqDailyDetialInfo",
            header_params=headers,
            request_params=params,
        )

        if (
            kq_data
            and isinstance(kq_data, dict)
            and "table" in kq_data
            and isinstance(kq_data["table"], dict)
            and "datas" in kq_data["table"]
            and isinstance(kq_data["table"]["datas"], list)
            and len(kq_data["table"]["datas"]) > 0
        ):

            userKqInfo = kq_data["table"]["datas"]
            # 3. 写入 Redis 缓存
            RedisUtils.get_instance().set_data_with_date(
                f"userKqInfo:{assignee}", current_date, userKqInfo
            )
            logger.info(
                f"考勤数据已写入Redis缓存: assignee={assignee}, date={current_date}"
            )
        else:
            logger.warning(
                f"获取考勤数据失败或数据为空: assignee={assignee}, date={current_date}"
            )
            userKqInfo = []

        return current_date, userKqInfo

    async def get_kq_data(
        self, startDate: str, endDate: str, assignee: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        查询用户从startDate到endDate的考勤记录

        参数:
            startDate: 查询开始日期 (格式: YYYY-MM-DD)
            endDate: 查询结束日期 (格式: YYYY-MM-DD)
            assignee: 用户邮箱地址

        返回:
            一个字典，键为日期字符串，值为该日期的考勤记录列表
        """
        logger.info(
            f"开始获取考勤数据: assignee={assignee}, startDate={startDate}, endDate={endDate}"
        )

        try:
            userinfo = self.get_userInfo(assignee)
            logger.debug(f"用户信息: {userinfo}")

            # 严谨判断response_data结构和id字段是否存在
            if userinfo and isinstance(userinfo, dict) and "id" in userinfo:
                id_value = userinfo["id"]
                logger.info(f"获取到用户ID: {id_value}")
                # 初始化结果字典
                kq_records = {}

                # 只有在成功获取id_value的情况下才继续执行后续操作
                if id_value is not None:
                    # 遍历日期范围
                    try:
                        dates = list(
                            date_range(startDate, endDate)
                        )  # 将生成器转为列表以便复用
                        logger.info(f"日期范围生成完成，共{len(dates)}天")
                    except ValueError as e:
                        logger.error(f"日期范围错误: {e}")
                        return {"error": f"日期范围错误: {e}"}

                    # 异步并发执行
                    logger.info("开始并发获取考勤数据")
                    tasks = [
                        self.fetch_kq_data_for_date(date, assignee, id_value)
                        for date in dates
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    logger.info("考勤数据获取完成，开始处理结果")

                    # 整理结果
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            date_str = dates[i].strftime("%Y-%m-%d")
                            logger.error(
                                f"获取{date_str}的考勤数据时发生异常: {result}"
                            )
                            kq_records[date_str] = []
                        else:
                            current_date_str, userKqInfo = result
                            kq_records[current_date_str] = (
                                userKqInfo if userKqInfo else []
                            )

                    logger.info(f"考勤数据处理完成，共处理{len(kq_records)}天数据")
                    # 返回处理后的考勤记录字典
                    return kq_records

                else:
                    error_msg = "错误：无法获取有效的ID值，跳过后续操作"
                    logger.error(error_msg)
                    return {"error": error_msg}
            else:
                error_msg = "错误：无法获取用户信息或用户信息中缺少ID字段"
                logger.error(error_msg)
                return {"error": error_msg}
        except Exception as e:
            error_msg = f"获取考勤数据时发生异常: {e}"
            logger.error(error_msg, exc_info=True)
            return {"error": error_msg}

        # 如果无法获取到有效数据，返回空字典
        logger.warning("未能获取到有效数据")
        return {}

    async def calculate_work_hours(
        self, startDate: str, endDate: str, assignee: str
    ) -> Dict[str, str]:
        """
        计算员工的每日考勤工时

        参数:
            startDate: 查询开始日期 (格式: YYYY-MM-DD)
            endDate: 查询结束日期 (格式: YYYY-MM-DD)
            assignee: 用户邮箱地址

        返回:
            字典，键为日期字符串，值为包含实际工时和工时的JSON字符串
        """
        logger.info(
            f"计算员工每日考勤工时: assignee={assignee}, startDate={startDate}, endDate={endDate}"
        )
        result = {}
        kq_records = await self.get_kq_data(startDate, endDate, assignee)
        for date_str, records in kq_records.items():
            if len(records) < 2:
                logger.debug(f"日期 {date_str} 的记录少于2条，跳过")
                continue  # 跳过少于2条记录的日期

            # 解析所有考勤时间
            sign_times = []
            work_times = []
            actual_worktime = 0
            worktime = 0
            signStatus = ""
            for record in records:
                try:
                    signStatus = record["signStatus"]
                    if record["signTime"]:
                        sign_time = datetime.strptime(
                            date_str + " " + record["signTime"], "%Y-%m-%d %H:%M:%S"
                        )
                        sign_times.append(sign_time)
                    if record["workTime"]:
                        work_time = datetime.strptime(
                            date_str + " " + record["workTime"], "%Y-%m-%d %H:%M"
                        )
                        work_times.append(work_time)
                except (KeyError, ValueError) as e:
                    logger.warning(f"解析考勤记录时出错: {e}")
                    continue

            if len(sign_times) == 2:
                actual_worktime = calculate_actual_worktime(sign_times)
            if "假" in signStatus or "正常" in signStatus:
                worktime = 8
            elif "迟到" in signStatus or "早退" in signStatus:
                worktime = actual_worktime

            # 构建结果
            result[date_str] = {
                "actual_worktime": actual_worktime,
                "worktime": worktime,
            }
            logger.debug(
                f"日期 {date_str} 工时计算结果: actual_worktime={actual_worktime}, worktime={worktime}"
            )

        logger.info(f"工时计算完成，共处理{len(result)}天数据")
        return result


# def calculate_start_time(min_time: datetime) -> datetime:
#     """计算考勤起点时间"""
#     # 如果最小考勤时间在9点之前，则设置考勤时间起点为9点
#     if min_time.time() < datetime.strptime("09:00", "%H:%M").time():
#         return datetime.combine(min_time.date(), datetime.strptime("09:00", "%H:%M").time())
#     # 如果最小考勤时间在9点半之前，则设置考勤时间起点为9点30
#     if min_time.time() < datetime.strptime("09:30", "%H:%M").time():
#         return datetime.combine(min_time.date(), datetime.strptime("09:30", "%H:%M").time())

#     #向后取整到最近的整点时间
#     if min_time.minute > 0:
#         hour = min_time.hour + 1

#     # 如果取整时间为12点，则把考勤起点时间设置为13点
#     if hour == 12:
#         return datetime.combine(min_time.date(), datetime.strptime("13:00", "%H:%M").time())

#     return datetime.combine(min_time.date(), datetime.strptime(f"{hour:02d}:00", "%H:%M").time())

# def calculate_end_time(max_time: datetime) -> datetime:
#     """计算考勤结束时间"""
#     # 如果最大考勤时间大于等于13点，考勤结束时间设为最大考勤时间
#     if max_time.time() >= datetime.strptime("13:00", "%H:%M").time():
#         return max_time

#     # 如果最大考勤时间大于等于12点30且小于13点，考勤结束时间设为12点30
#     if datetime.strptime("12:30", "%H:%M").time() <= max_time.time() < datetime.strptime("13:00", "%H:%M").time():
#         return datetime.combine(max_time.date(), datetime.strptime("12:30", "%H:%M").time())

#     # 如果最大考勤时间大于12点小于12点30，则考勤结束时间为12点
#     if max_time.time() > datetime.strptime("12:00", "%H:%M").time():
#         return datetime.combine(max_time.date(), datetime.strptime("12:00", "%H:%M").time())

#     # 默认：向前取整到最近的整点时间
#     if max_time.minute > 0:
#         hour = max_time.hour
#     return datetime.combine(max_time.date(), datetime.strptime(f"{hour:02d}:00", "%H:%M").time())


# def calculate_actual_worktime(times) -> int:
#     """
#     计算实际工时（小时）

#     参数:
#         start_time: 考勤开始时间
#         end_time: 考勤结束时间

#     返回:
#         实际工时（整数小时）
#     """
#     try:
#         # 找出最小和最大的考勤时间
#         start_time = min(times)
#         end_time = max(times)
#         # 计算总秒数
#         total_seconds = (end_time - start_time).total_seconds()

#         # 转换为小时数，并进行取整
#         actual_hours = total_seconds / 3600

#         # 如果结束时间大于13点（13:00之后），扣减午休一小时
#         if (
#             start_time.time() < datetime.strptime("12:00", "%H:%M").time()
#             and end_time.time() > datetime.strptime("13:00", "%H:%M").time()
#         ):
#             actual_hours -= 1

#         # 确保工时不小于0
#         actual_hours = max(0, actual_hours)

#         # 返回取整后的实际工时
#         result = int(actual_hours)
#         return result

#     except Exception as e:
#         logger.error(f"计算实际工时失败: {e}")
#         return 0


def extract_username(email: str) -> str:
    username = email.split("@")[0]
    logger.debug(f"从邮箱提取用户名: {email} -> {username}")
    return username


if __name__ == "__main__":
    # 配置日志
    log_dir = "log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.debug,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "bst_oa_main.log")),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    oa = BstOA()
    oa.get_access_token()
    assignee = "song.li@bst.ai"
    username = extract_username(assignee)
    params = {"params": {"loginid": username}}
    # 构建默认 headers
    _headers = {
        "token": oa.token,
        "appid": oa.app_id,
        "userid": oa.user_id,
        "skipsession": oa.skipsession,
    }
    response_data = call_restful_api(
        config_root,
        api_endpoint="getHrmUserInfo",
        header_params=_headers,
        request_params=params,
    )
    # response_data= oa.call_ecology_api(api_endpoint="getHrmUserInfo", request_params=params)
    # 严谨判断response_data结构和id字段是否存在
    if (
        response_data
        and isinstance(response_data, dict)
        and "data" in response_data
        and isinstance(response_data["data"], dict)
        and "dataList" in response_data["data"]
        and isinstance(response_data["data"]["dataList"], list)
        and len(response_data["data"]["dataList"]) > 0
        and "id" in response_data["data"]["dataList"][0]
    ):

        id_value = response_data["data"]["dataList"][0]["id"]
        logger.info(f"ID 的值为: {id_value}")
    else:
        logger.error("Error: 无法获取ID - 响应数据结构不符合预期")
        id_value = None

    # 只有在成功获取id_value的情况下才继续执行后续操作
    if id_value is not None:
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        headers = {**_headers, **(headers or {})}
        params = {
            "kqDate": "2025-03-28",
            "resourceId": id_value,
        }
        call_restful_api(
            config_root,
            api_endpoint="getKqDailyDetialInfo",
            header_params=headers,
            request_params=params,
        )
    else:
        logger.error("错误：无法获取有效的ID值，跳过后续操作")

    logger.info(f"ID 的值为: {id_value}")
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    headers = {**_headers, **(headers or {})}
    params = {
        "kqDate": "2025-03-28",
        "resourceId": id_value,
    }
    call_restful_api(
        config_root,
        api_endpoint="getKqDailyDetialInfo",
        header_params=headers,
        request_params=params,
    )
