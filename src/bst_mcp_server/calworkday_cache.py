# src/critical_path_analyzer/calworkday_cache.py

import logging
import os
from datetime import datetime, timedelta
from typing import Dict

from bst_mcp_server.http_utils import call_restful_api

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "calworkday_cache.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class CalworkdayCache:
    _cache: Dict[str, int] = {}

    @classmethod
    def get_cached_data(cls) -> Dict[str, int]:
        """获取当前缓存的数据"""
        logger.debug("获取当前缓存数据")
        return cls._cache

    @classmethod
    def update_cache(cls, raw_data: dict) -> bool:
        """更新缓存，从原始数据中提取需要的日期信息"""
        logger.info("开始更新工作日缓存")
        try:
            # 清除旧缓存
            cls._cache = {}

            # 处理工作日
            # for date_str in raw_data.get("workdays", []):
            #     cls._cache[date_str] = 1

            # 处理假期
            holidays = raw_data.get("holidays", [])
            logger.debug(f"处理 {len(holidays)} 个假期日期")
            for date_str in holidays:
                cls._cache[date_str] = 0

            logger.info(f"成功更新缓存，共存储 {len(cls._cache)} 条记录")
            return True

        except Exception as e:
            logger.error(f"更新缓存失败: {e}", exc_info=True)
            return False

    @classmethod
    def build_cache(cls):
        logger.info("构建工作日缓存")
        current_date = datetime.now().date()
        current_date_str = current_date.strftime("%Y-%m-%d")
        six_months_ago = (current_date - timedelta(days=180)).strftime("%Y-%m-%d")

        logger.debug(f"查询日期范围: {six_months_ago} 到 {current_date_str}")
        # 在调用API的地方修改如下：
        params = {
            "startDate": current_date_str,
            "endDate": six_months_ago,
        }

        # 调用API获取原始数据
        logger.info("调用API获取工作日数据")
        raw_response = call_restful_api(
            "jira", api_endpoint="jira-timesheet-calworkday", request_params=params
        )

        # 更新缓存
        if raw_response and isinstance(raw_response, dict):
            logger.info("成功获取API响应，更新缓存")
            cls.update_cache(raw_response)
        else:
            logger.warning("无法从API获取有效数据，将继续使用现有缓存（如果有的话）")

    @classmethod
    def is_workday(cls, date_str: str) -> bool:
        """判断指定日期是否为工作日"""
        logger.debug(f"检查日期是否为工作日: {date_str}")
        result = cls._cache.get(date_str)
        if result is None:
            logger.debug(f"日期 {date_str} 不在缓存中，默认为工作日")
            return True  # 如果日期不在缓存中，默认为工作日
        else:
            is_workday = result != 0
            logger.debug(f"日期 {date_str} 是{'工作日' if is_workday else '非工作日'}")
            return is_workday

    @classmethod
    def clear_cache(cls) -> None:
        """清除缓存"""
        logger.info("清除工作日缓存")
        cls._cache = {}
