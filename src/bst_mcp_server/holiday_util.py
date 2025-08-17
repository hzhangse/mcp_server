from datetime import datetime, timedelta
import logging
import os
from typing import Generator

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "holiday_util.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class HolidayUtil:
    def __init__(self):
        logger.info("初始化HolidayUtil")
        self.holidays = self._load_holidays()
        logger.info(f"节假日数据加载完成，共{len(self.holidays)}个节假日")

    def _load_holidays(self):
        """加载中国大陆法定节假日"""
        logger.debug("加载中国大陆法定节假日数据")
        holidays = {
            # 2024年法定节假日
            "2024-01-01",  # 元旦
            "2024-02-10",
            "2024-02-11",
            "2024-02-12",
            "2024-02-13",
            "2024-02-14",
            "2024-02-15",
            "2024-02-16",  # 春节
            "2024-04-04",
            "2024-04-05",
            "2024-04-06",  # 清明节
            "2024-05-01",
            "2024-05-02",
            "2024-05-03",
            "2024-05-04",  # 劳动节
            "2024-06-08",
            "2024-06-09",
            "2024-06-10",  # 端午节
            "2024-09-15",
            "2024-09-16",
            "2024-09-17",  # 中秋节
            "2024-10-01",
            "2024-10-02",
            "2024-10-03",
            "2024-10-04",
            "2024-10-05",
            "2024-10-06",  # 国庆节
            # 2025年法定节假日
            "2025-01-01",  # 元旦
            "2025-01-28",
            "2025-01-29",
            "2025-01-30",
            "2025-01-31",
            "2025-02-01",
            "2025-02-02",
            "2025-02-03",  # 春节
            "2025-04-04",
            "2025-04-05",
            "2025-04-06",  # 清明节
            "2025-05-01",
            "2025-05-02",
            "2025-05-03",  # 劳动节
            "2025-06-07",
            "2025-06-08",
            "2025-06-09",  # 端午节
            "2025-09-15",
            "2025-09-16",
            "2025-09-17",  # 中秋节
            "2025-10-01",
            "2025-10-02",
            "2025-10-03",
            "2025-10-04",
            "2025-10-05",
            "2025-10-06",
            "2025-10-07",  # 国庆节
        }
        logger.debug(f"节假日数据加载完成，共{len(holidays)}个节假日")
        return holidays

    def is_holiday(self, date_str):
        """判断给定日期是否为法定节假日"""
        logger.debug(f"检查日期是否为节假日: {date_str}")
        result = date_str in self.holidays
        logger.debug(f"日期 {date_str} {'是' if result else '不是'}节假日")
        return result


def date_range(startDate: str, endDate: str) -> Generator[datetime, None, None]:
    """
    顺序遍历两个日期间的所有日期

    参数:
        startDate: 起始日期字符串 (格式: YYYY-MM-DD)
        endDate: 结束日期字符串 (格式: YYYY-MM-DD)

    返回:
        生成器，按顺序生成从开始到结束的每个日期

    抛出:
        ValueError: 当日期格式不正确或开始日期晚于结束日期时
    """
    logger.info(f"生成日期范围: {startDate} 到 {endDate}")
    try:
        # 解析输入日期字符串为datetime对象
        start_date = datetime.strptime(startDate, "%Y-%m-%d")
        end_date = datetime.strptime(endDate, "%Y-%m-%d")
        logger.debug(f"解析日期完成: 开始={start_date}, 结束={end_date}")
    except ValueError as e:
        error_msg = f"日期格式错误，应为YYYY-MM-DD格式: {e}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # 验证日期顺序
    if start_date > end_date:
        error_msg = "开始日期不能晚于结束日期"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # 生成日期范围
    current_date = start_date
    days_count = 0
    while current_date <= end_date:
        logger.debug(f"生成日期: {current_date}")
        yield current_date
        current_date += timedelta(days=1)
        days_count += 1

    logger.info(f"日期范围生成完成，共{days_count}天")
