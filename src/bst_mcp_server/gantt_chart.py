# gantt_chart.py
import json
import os
import logging
from datetime import datetime

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "gantt_chart.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def export_to_ganttecharts(
    tasks, output_file="gantt_chart.html", show_critical_path=False
):
    """
    使用真实从 Jira 获取的任务数据生成甘特图页面。
    - 数据写入 JSON 文件
    - HTML 页面异步加载 JSON 并渲染甘特图
    """
    logger.info(f"开始导出甘特图，任务数: {len(tasks) if tasks else 0}")
    logger.debug(f"输出文件: {output_file}, 显示关键路径: {show_critical_path}")

    # ✅ 确保输出目录存在（默认为当前目录）
    output_dir = os.path.dirname(output_file)
    if not output_dir:
        output_dir = "."  # 默认当前目录

    json_output_file = os.path.join("data", "tasks.json")
    logger.debug(f"JSON输出文件路径: {json_output_file}")

    # ✅ 转换时间格式为时间戳（毫秒）
    processed_tasks = []
    skipped_tasks = 0
    failed_tasks = 0

    for task in tasks:
        key = task.get("key")
        summary = task.get("Summary", key)
        start = task.get("计划开始日期") or task.get("实际开始日期")
        end = task.get("计划完成日期") or task.get("实际完成日期")

        if not start or not end:
            logger.warning(f"跳过任务 {key}：缺少时间信息")
            skipped_tasks += 1
            continue

        try:
            # ✅ 强制使用 ISO 格式解析日期字符串
            start_time = int(datetime.strptime(start, "%Y-%m-%d").timestamp()) * 1000
            end_time = int(datetime.strptime(end, "%Y-%m-%d").timestamp()) * 1000
            logger.debug(
                f"任务 {key} 时间转换成功: {start} -> {start_time}, {end} -> {end_time}"
            )
        except ValueError as e:
            logger.error(f"时间解析失败 {key}: {e}")
            failed_tasks += 1
            continue

        processed_tasks.append({"name": summary, "start": start_time, "end": end_time})

    logger.info(
        f"任务处理完成: 成功处理 {len(processed_tasks)} 个任务，跳过 {skipped_tasks} 个，失败 {failed_tasks} 个"
    )

    # ✅ 写入 JSON 文件
    try:
        os.makedirs(os.path.dirname(json_output_file), exist_ok=True)
        with open(json_output_file, "w", encoding="utf-8") as f:
            json.dump(processed_tasks, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ 成功导出甘特图数据至: {json_output_file}")
    except Exception as e:
        logger.error(f"写入JSON文件失败: {e}")
        raise

    # ✅ 读取 HTML 模板
    template_file = "./assets/template.html"
    logger.debug(f"读取HTML模板文件: {template_file}")
    if not os.path.exists(template_file):
        error_msg = f"找不到 HTML 模板文件: {template_file}"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    try:
        with open(template_file, "r", encoding="utf-8") as f:
            html_content = f.read()
        logger.debug("HTML模板读取成功")
    except Exception as e:
        logger.error(f"读取HTML模板文件失败: {e}")
        raise

    # ✅ 写入输出 HTML 文件
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"✅ 成功生成甘特图页面：{output_file}")
    except Exception as e:
        logger.error(f"写入HTML文件失败: {e}")
        raise

    logger.info("甘特图导出完成")
    return output_file
