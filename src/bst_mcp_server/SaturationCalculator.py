import re
import os
import logging
from typing import Dict

from bst_mcp_server.config_util import load_config

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "saturation_calculator.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class SaturationCalculator:
    def __init__(self):
        """初始化饱和度计算器"""
        self.config = load_config()
        self.assignee_metrics = {}
        self.variables = {}
        logger.info("SaturationCalculator 初始化完成")

    def load_assignee_metrics(self, assignee: str, metric_results: Dict) -> None:
        """加载员工指标数据"""
        logger.info(f"加载员工 {assignee} 的指标数据")
        metrics_config = self.config.get("saturation", {}).get("metrics", [])
        assignee_metrics = {}

        for metric in metrics_config:
            if metric in metric_results.get(assignee, {}):
                assignee_metrics[metric] = metric_results.get(assignee, {}).get(metric)
            # assignee_metrics[metric] = metric_results.get(metric)

        self.assignee_metrics[assignee] = assignee_metrics
        logger.debug(f"员工 {assignee} 的指标数据加载完成: {assignee_metrics}")

    def calculate_workload_rules(self, assignee: str) -> Dict:
        """计算工作量规则"""
        logger.info(f"计算员工 {assignee} 的工作量规则")
        if assignee not in self.assignee_metrics:
            logger.warning(f"员工 {assignee} 没有指标数据")
            return {}

        workload_rules = self.config.get("saturation", {}).get("workload_rules", {})
        result = {}
        self.variables = {}

        # 首先计算变量
        for var_name, expression in workload_rules.items():
            if var_name.startswith("$"):
                continue  # 跳过已计算的变量

            try:
                value = self._evaluate_expression(expression, assignee)
                self.variables[var_name] = value
                result[var_name] = value
                logger.debug(f"计算变量 {var_name} = {value}")
            except Exception as e:
                logger.error(f"计算变量 {var_name} 失败: {e}")
                result[var_name] = 0

        # 然后计算使用变量的表达式
        for var_name, expression in workload_rules.items():
            if not var_name.startswith("$"):
                continue  # 只处理使用$前缀的变量

            try:
                value = self._evaluate_expression(expression, assignee)
                result[var_name] = value
                logger.debug(f"计算表达式 {var_name} = {value}")
            except Exception as e:
                logger.error(f"计算表达式 {var_name} 失败: {e}")
                result[var_name] = 0

        logger.info(f"员工 {assignee} 的工作量规则计算完成")
        return result

    def _evaluate_expression(self, expression: str, assignee: str) -> float:
        """评估表达式，增强异常处理和边界检查"""
        logger.debug(f"评估表达式: {expression} for 员工 {assignee}")
        try:
            # 替换变量引用
            var_pattern = r"\$([a-zA-Z_][a-zA-Z0-9_]*)"
            while re.search(var_pattern, expression):
                expression = re.sub(
                    var_pattern,
                    lambda m: str(self.variables.get(m.group(1), 0)),
                    expression,
                )

            # 替换指标引用
            metric_pattern = r"([a-zA-Z_][a-zA-Z0-9_]*)"
            expression = re.sub(
                metric_pattern,
                lambda m: str(self.assignee_metrics[assignee].get(m.group(1), 0)),
                expression,
            )

            # 检查除法中的除数是否为零
            if "/" in expression:
                parts = expression.split("/")
                divisor = parts[1].strip()
                try:
                    divisor_value = eval(divisor)
                    if abs(divisor_value) < 1e-10:
                        logger.warning(f"警告: 除数接近零，表达式: {expression}")
                        return 0
                except:
                    logger.error(f"无法计算除数: {divisor}")
                    return 0

            # 安全计算表达式
            result = eval(expression)
            if not isinstance(result, (int, float)):
                logger.warning(f"结果不是数字类型: {result}")
                return 0
            logger.debug(f"表达式计算结果: {result}")
            return result

        except ZeroDivisionError:
            logger.error(f"错误: 除数为零，表达式: {expression}")
            return 0
        except Exception as e:
            logger.error(f"表达式计算异常: {expression} - {e}")
            return 0

    def calculate_weighted_saturation(self, assignee: str) -> float:
        """
        根据配置文件中的权重计算饱和度指标

        参数:
        assignee (str): 员工ID

        返回:
        float: 加权后的饱和度值
        """
        logger.info(f"计算员工 {assignee} 的加权饱和度")
        if assignee not in self.assignee_metrics:
            logger.warning(f"员工 {assignee} 没有指标数据")
            return 0.0

        # 获取饱和度配置
        saturation_config = self.config.get("saturation", {})
        # 初始化加权饱和度
        weighted_saturation = 0.0

        # 检查饱和度计算是否启用
        weight_enabled = saturation_config.get("enabled", False)
        if not weight_enabled:
            logger.info("饱和度计算未启用")
            return weighted_saturation

        # 获取权重配置
        weight_ratios = saturation_config.get("weight_ratio", {})

        # 获取工作量计算结果
        workload_results = self.calculate_workload_rules(assignee)

        # 合并基础指标和工作量计算结果
        all_metrics = {**self.assignee_metrics[assignee], **workload_results}

        # 遍历权重配置，计算加权饱和度
        for metric_name, weight in weight_ratios.items():
            # 从合并后的指标字典中获取对应指标值
            metric_value = all_metrics.get(metric_name, 0.0)

            # 计算加权值并累加
            weighted_value = metric_value * weight
            weighted_saturation += weighted_value

            logger.info(
                f"指标: {metric_name}, 权重: {weight}, 值: {metric_value}, 加权值: {weighted_value}"
            )

        logger.info(f"员工 {assignee} 的加权饱和度计算完成: {weighted_saturation}")
        return workload_results.get("actualWorkload"), weighted_saturation, all_metrics

    def get_saturation_results(self, assignee: str) -> Dict:
        """获取饱和度计算结果"""
        logger.info(f"获取员工 {assignee} 的饱和度计算结果")
        metrics = self.assignee_metrics.get(assignee, {})
        workload = self.calculate_workload_rules(assignee)
        base_saturation, weighted_saturation, all_metrics = (
            self.calculate_weighted_saturation(assignee)
        )

        result = {
            "工作指标项": all_metrics,
            "工作负荷指标": workload,
            "加权工作饱和度": weighted_saturation,
            "基础工作饱和度": base_saturation,
        }
        logger.debug(f"员工 {assignee} 的饱和度计算结果: {result}")
        return result


# 示例用法
if __name__ == "__main__":
    # 配置日志
    log_dir = "log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(log_dir, "saturation_calculator_main.log")
            ),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    # 示例指标数据
    metric_results = {
        "employee1": {
            "worktime_total_hours": 40,
            "worktime_priority_total_hours": 41,
            "worktime_keytask_total_seconds": 20,  # 20小时
            "done_task_num": 8,
            "total_task_num": 10,
            "key_task_num": 3,
            "attendance_worktimeHours": 46,
            "attendance_actual_worktimeHours": 45,
            "leave_hours": 5,
        },
        "employee2": {
            "worktime_total_hours": 35,
            "worktime_priority_total_hours": 38,
            "worktime_keytask_total_seconds": 10,  # 15小时
            "done_task_num": 6,
            "total_task_num": 8,
            "key_task_num": 2,
            "attendance_worktimeHours": 40,
            "attendance_actual_worktimeHours": 45,
            "leave_hours": 2,
        },
    }

    # 初始化计算器
    calculator = SaturationCalculator()

    # 计算每个员工的饱和度
    for assignee in metric_results:
        calculator.load_assignee_metrics(assignee, metric_results)
        result = calculator.get_saturation_results(assignee)

        logger.info(f"\n员工: {assignee}")
        logger.info("基础指标:")
        for metric, value in result["工作指标项"].items():
            logger.info(f"  {metric}: {value}")

        logger.info("工作量计算:")
        for var, value in result["工作负荷指标"].items():
            logger.info(f"  {var}: {value}")

        logger.info(
            f"加权饱和度: {result['加权工作饱和度']:.2%} 基础饱和度: {result['基础工作饱和度']:.2%}"
        )
