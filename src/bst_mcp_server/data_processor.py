from datetime import datetime, timedelta
import json
import logging
import os
from bst_mcp_server.config_util import load_field_mapping
from bst_mcp_server.holiday_util import HolidayUtil

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "data_processor.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

CONFIG_FILE = "field_mapping.json"


# def load_field_mapping():
#     if not os.path.exists(CONFIG_FILE):
#         print(f"找不到配置文件 {CONFIG_FILE}")
#         exit()
#     with open(CONFIG_FILE, encoding="utf-8") as f:
#         return json.load(f)


def parse_date(date_str):
    logger.debug(f"解析日期字符串: {date_str}")
    try:
        result = datetime.strptime(date_str, "%Y-%m-%d")
        return result
    except ValueError as e:
        logger.error(f"日期格式无效: {date_str}")
        raise


def date_diff(start_str, end_str):
    """
    计算两个日期之间的有效工作日天数（扣除周末和法定节假日）

    参数：
    - start_str: 开始日期字符串（格式：YYYY-MM-DD）
    - end_str: 结束日期字符串（格式：YYYY-MM-DD）

    返回：
    - 有效工作日天数
    """
    logger.info(f"计算日期差: {start_str} 到 {end_str}")
    # 日期格式验证
    try:
        start = parse_date(start_str)
        end = parse_date(end_str)
    except ValueError:
        error_msg = "日期格式无效，应为YYYY-MM-DD"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # 结束时间检查
    if start > end:
        error_msg = "结束日期不能早于开始日期"
        logger.error(error_msg)
        raise ValueError(error_msg)

    holiday_util = HolidayUtil()
    day_count = 0
    current = start

    while current <= end:
        # 判断是否为工作日（周一到周五）且不是节假日
        if current.weekday() < 5 and not holiday_util.is_holiday(
            current.strftime("%Y-%m-%d")
        ):
            day_count += 1
        current += timedelta(days=1)

    logger.info(f"有效工作日天数: {day_count}")
    return day_count


def get_predecessor_list(issue):
    """
    从 issue 的 issuelinks 中提取所有符合规则的前置任务 key，组成 list
    优先级顺序:
        'has to be done after' > 'is blocked by' > 'is child of'
    返回: list of keys
    """
    logger.debug("提取前置任务列表")
    # 定义优先级顺序
    priority_order = {"has to be done after": 0, "is blocked by": 1, "is child of": 2}

    # 存储符合条件的 links，按优先级分组
    grouped_links = {
        0: [],  # has to be done after
        1: [],  # is blocked by
        2: [],  # is child of
    }

    # 遍历所有链接
    for link in issue.get("fields", {}).get("issuelinks", []):
        inward_issue = link.get("inwardIssue")
        link_type = link.get("type", {})
        inward_type = link_type.get("inward")

        if inward_issue and inward_type in priority_order:
            predecessor_key = inward_issue.get("key")
            if predecessor_key:
                priority_level = priority_order[inward_type]
                grouped_links[priority_level].append(predecessor_key)
                logger.debug(f"找到前置任务: {predecessor_key}, 类型: {inward_type}")

    # 找出最高优先级并返回对应的所有 key
    # 找出最高优先级且非空的分组
    highest_priority_group = []
    for level in sorted(grouped_links.keys()):
        if grouped_links[level]:
            highest_priority_group = grouped_links[level].copy()
            logger.debug(f"使用优先级 {level} 的前置任务: {highest_priority_group}")
            break

    # 获取 parent 的 key（如果存在）
    # parent_key = None
    # parent = issue.get("fields", {}).get("parent")
    # if parent and isinstance(parent, dict):
    #     parent_key = parent.get("key")

    # 如果有 parent，加入列表，并去重
    # if parent_key:
    #     highest_priority_group.append(parent_key)

    # 去重并返回
    result = list(dict.fromkeys(highest_priority_group))
    logger.debug(f"最终前置任务列表: {result}")
    return result


def get_prelink_list(issue):
    """
    从 issue 的 issuelinks 中提取所有符合规则的前置任务 key，组成 list
    优先级顺序:
        'has to be done after' > 'is blocked by' > 'is child of'
    返回: list of keys
    """
    logger.debug("提取前置链接列表")
    # 定义优先级顺序
    prelink_types = ["has to be done after", "is blocked by", "is child of"]

    # 用于存储结果的字典，按类型分类
    result_map = {link_type: [] for link_type in prelink_types}

    # 遍历所有链接
    for link in issue.get("fields", {}).get("issuelinks", []):
        inward_issue = link.get("inwardIssue")
        link_type = link.get("type", {})
        inward_type = link_type.get("inward")

        # 如果链接类型在我们关注的优先级类型中
        if inward_type in prelink_types and inward_issue:
            predecessor_key = inward_issue.get("key")
            if predecessor_key:
                result_map[inward_type].append(predecessor_key)
                logger.debug(f"找到前置链接: {predecessor_key}, 类型: {inward_type}")

    # 按优先级顺序合并结果
    ordered_result = []
    for link_type in prelink_types:
        ordered_result.extend(result_map[link_type])

    logger.debug(f"前置链接列表: {ordered_result}")
    return result_map


def extract_task_info(data, field_mapping):
    logger.info("开始提取任务信息")
    customfield_id_map = {}
    for field_id, field_name in data.get("names", {}).items():
        customfield_id_map[field_name] = field_id

    tasks = []
    issues = data.get("issues", [])
    logger.info(f"共处理 {len(issues)} 个问题")

    for issue in issues:
        key = issue["key"]
        logger.debug(f"处理问题: {key}")
        fields = issue.get("fields", {})

        task = {
            "key": key,
            "issueId": issue["id"],
            # 'plan_start': None,
            # 'plan_end': None,
            # 'actual_start': None,
            # 'actual_end': None,
            # 'predecessor': None
        }

        for field_key, config in field_mapping.items():
            field_type = config.get("type")
            path = config.get("path")

            if field_type == "custom":
                display = config.get("display")
                field_id = customfield_id_map.get(display)
                if field_id:
                    value = fields.get(field_id)
                    if value is not None:
                        if path:
                            value = get_value(value, path)
                            if value is not None:
                                task[field_key] = value
                                logger.debug(f"设置字段 {field_key}: {value}")
                        else:
                            task[field_key] = value
                            logger.debug(f"设置字段 {field_key}: {value}")

            elif field_type == "system":
                parts = path.split(".")
                value = fields
                value = get_value(value, path)
                if value is not None:
                    task[field_key] = value
                    logger.debug(f"设置字段 {field_key}: {value}")

        # ✅ 新增：设置前置任务列表
        predecessor_list = get_predecessor_list(issue)
        task["predecessors"] = predecessor_list
        task["prelinks"] = get_prelink_list(issue)
        tasks.append(task)

    logger.info(f"任务信息提取完成，共提取 {len(tasks)} 个任务")
    return tasks


def get_value(value, path):
    logger.debug(f"获取值: path={path}")
    parts = path.split(".")
    for part in parts:
        if isinstance(value, list) and len(value) > 0:
            found_items = []
            for item in value:
                if isinstance(item, dict) and part in item:
                    found_items.append(item[part])

            if len(found_items) > 0:
                # 如果是最后一级路径，返回整个列表
                # 否则继续处理下一级（每个元素继续向下遍历）
                value = found_items
            else:
                value = None
                break
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            value = None
            break
    logger.debug(f"获取到值: {value}")
    return value


if __name__ == "__main__":
    # 配置日志
    log_dir = "log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "data_processor_main.log")),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    field_mapping = load_field_mapping()
    with open("WORK.log", encoding="utf-8") as f:
        raw_data = json.load(f)
    tasks = extract_task_info(raw_data, field_mapping)
    # 🔁 重定向 stdout 到日志文件
    logger.info(json.dumps(tasks, ensure_ascii=False, indent=2))
