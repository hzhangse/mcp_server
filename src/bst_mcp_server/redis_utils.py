from datetime import datetime
import redis
import logging
import json
import os

from bst_mcp_server.config_util import load_config
from bst_mcp_server.holiday_util import date_range

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "redis_utils.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

config_root = "redis"


class RedisUtils:
    _instance = None  # 用于保存单例实例

    def __new__(cls, *args, **kwargs):
        """实现单例模式的__new__方法"""
        if cls._instance is None:
            cls._instance = super(RedisUtils, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # 避免重复初始化
        if hasattr(self, "initialized") and self.initialized:
            return

        logger.info("初始化RedisUtils")
        self.config = load_config().get(config_root, {})
        self.host = self.config.get("host")
        self.port = self.config.get("port")
        self.db = self.config.get("db")
        logger.info(f"Redis配置: host={self.host}, port={self.port}")

        try:
            self.redis = redis.StrictRedis(host=self.host, port=self.port, db=self.db)
            # 标记为已初始化
            self.initialized = True
            logger.info("Redis连接初始化成功")
        except Exception as e:
            logger.error(f"Redis连接初始化失败: {e}")
            self.initialized = False

    @classmethod
    def get_instance(cls) -> "RedisUtils":
        """获取单例实例的方法"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_data_with_date(self, key, date, data):
        logger.debug(f"设置带日期的Redis数据: key={key}, date={date}")
        full_key = f"{key}:{date}"
        return self.set_data(full_key, data)

    def get_data_with_date(self, key, date):
        logger.debug(f"获取带日期的Redis数据: key={key}, date={date}")
        full_key = f"{key}:{date}"
        return self.get_data(full_key)

    def set_data(self, key, data):
        logger.debug(f"设置Redis数据: key={key}")
        try:
            json_data = json.dumps(data, ensure_ascii=False)
            result = self.redis.set(key, json_data)
            logger.debug(f"Redis数据设置成功: key={key}")
            return result
        except Exception as e:
            logger.error(f"设置Redis数据失败: key={key}, error={e}")
            return None

    def get_data(self, key):
        logger.debug(f"获取Redis数据: key={key}")
        try:
            json_data = self.redis.get(key)
            if json_data is None:
                logger.debug(f"Redis中未找到数据: key={key}")
                return None
            try:
                result = json.loads(json_data)
                logger.debug(f"Redis数据获取成功: key={key}")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"解析Redis数据失败: key={key}, error={e}")
                return None
        except Exception as e:
            logger.error(f"获取Redis数据失败: key={key}, error={e}")
            return None

    def is_key_exist(self, *keys):
        """
        判断多个 key 是否存在

        参数:
            *keys: 可变参数，传入多个 key 字符串

        返回:
            int: 存在的 key 的数量
        """
        logger.debug(f"检查Redis key是否存在: keys={keys}")
        if not keys:
            error_msg = "至少需要传入一个 key"
            logger.error(error_msg)
            raise ValueError(error_msg)

        result = self.redis.exists(*keys)
        logger.debug(f"存在 {result} 个key: keys={keys}")
        return result

    def get_ranged_data(self, type: str, assignee: str, startDate: str, endDate: str):
        """
        根据日期范围查询数据：
            - 若查询范围完全在 Redis 缓存范围内，直接从缓存返回数据；
            - 否则从数据库查询，并更新 Redis 缓存。

        参数:
            type: Redis key 类型前缀，如 "userKqInfo"
            assignee: 用户标识
            startDate: 起始日期 (YYYY-MM-DD)
            endDate: 结束日期 (YYYY-MM-DD)

        返回:
            list: 查询结果列表
        """
        logger.info(
            f"获取范围数据: type={type}, assignee={assignee}, startDate={startDate}, endDate={endDate}"
        )
        _key_prefix = f"{type}:{assignee}:"
        pattern = _key_prefix + "*"
        result = None
        # 1. 获取所有匹配的 key 并提取日期
        keys = self.get_sorted_keys(pattern)  # 使用你已有的方法获取排序后的 key 列表
        logger.debug(f"找到 {len(keys)} 个匹配的key")

        date_list = []
        for key in keys:
            try:
                key_str = key.decode()
                date_str = key_str.replace(_key_prefix, "", 1)
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                date_list.append(dt.strftime("%Y-%m-%d"))
            except (ValueError, IndexError):
                logger.warning(f"忽略不符合格式的key: {key}")
                continue  # 忽略不符合格式的 key

        if date_list:
            # 2. 找出缓存中的最早和最晚日期
            min_cached_date = min(date_list)
            max_cached_date = max(date_list)

            min_cached_dt = datetime.strptime(min_cached_date, "%Y-%m-%d")
            max_cached_dt = datetime.strptime(max_cached_date, "%Y-%m-%d")

            # 3. 将输入日期转为 datetime 对象
            input_start = datetime.strptime(startDate, "%Y-%m-%d")
            input_end = datetime.strptime(endDate, "%Y-%m-%d")

            # 4. 判断输入日期是否完全在缓存范围内
            if input_start >= min_cached_dt and input_end <= max_cached_dt:
                logger.info("查询范围完全在缓存内，从缓存加载数据")
                result = self._load_from_cache(
                    type, assignee, startDate, endDate, date_list
                )
            else:
                logger.info("查询范围不完全在缓存内")

        logger.info("范围数据获取完成")
        return result

    def _load_from_cache(
        self, type: str, assignee: str, startDate: str, endDate: str, cached_dates: list
    ):
        """从缓存中加载指定日期范围的数据"""
        logger.info(
            f"从缓存加载数据: type={type}, assignee={assignee}, startDate={startDate}, endDate={endDate}"
        )
        dates = list(date_range(startDate, endDate))
        result = []

        for dt in dates:
            current_date = dt.strftime("%Y-%m-%d")
            if current_date in cached_dates:
                data = self.get_data_with_date(f"{type}:{assignee}", current_date)
                if data:
                    result.append(data)
                    logger.debug(f"从缓存加载数据成功: date={current_date}")

        logger.info(f"缓存数据加载完成，共加载 {len(result)} 条数据")
        return result

    def get_sorted_keys(self, pattern="*", reverse=False):
        logger.debug(f"获取排序后的Redis key: pattern={pattern}")
        keys = []
        cursor = "0"
        while cursor != 0:
            cursor, partial_keys = self.redis.scan(cursor=cursor, match=pattern)
            keys.extend(partial_keys)
        result = sorted(keys, reverse=reverse)
        logger.debug(f"获取到 {len(result)} 个key")
        return result
