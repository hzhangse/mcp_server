# src/critical_path_analyzer/human_efficiency.py

import asyncio
from datetime import datetime
import random
from typing import Dict, List, Any, Optional
from collections import defaultdict
import logging
import os

from flask import json
from bst_mcp_server.SaturationCalculator import SaturationCalculator
from bst_mcp_server.aoe_graph import find_critical_path
from bst_mcp_server.bst_oa import BstOA
from bst_mcp_server.config_util import load_config
from bst_mcp_server.critical_task_project import CriticalTaskProject
from bst_mcp_server.http_utils import call_restful_api
from bst_mcp_server.redis_utils import RedisUtils

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "human_efficiency.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class HumanEfficiencyAnalyzer:
    """
    人力资源效率分析器

    提供计算员工工作饱和度的功能，结合项目关键路径、考勤数据、工时填报和任务属性等多维度数据。
    """

    _instance = None  # 用于保存单例实例

    def __new__(cls, *args, **kwargs):
        """实现单例模式的__new__方法"""
        if cls._instance is None:
            cls._instance = super(HumanEfficiencyAnalyzer, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "HumanEfficiencyAnalyzer":
        """获取单例实例的方法"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """
        初始化人力资源效率分析器

        """
        logger.info("初始化HumanEfficiencyAnalyzer")
        # BstOA.get_instance()
        RedisUtils.get_instance()
        self.PRIORITY_FACTORS = (
            load_config().get("saturation", {}).get("PRIORITY_FACTORS", [])
        )
        logger.debug(f"优先级因子配置: {self.PRIORITY_FACTORS}")

    async def fetch_assignee_work_logs(
        self, assignee: str, start_date: str, end_date: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取多个用户在指定日期范围内的任务工时（按用户分组返回）

        参数:
            assignee: 用户邮箱地址，多个用逗号分隔（例如：a@b.com,c@d.com）
            start_date: 开始日期 (格式: YYYY-MM-DD)
            end_date: 结束日期 (格式: YYYY-MM-DD)

        返回:
            Dict[str, List[Dict]]: key 是 email，value 是该用户的工时记录列表
        """
        logger.info(
            f"获取用户任务工时: assignees={assignee}, start_date={start_date}, end_date={end_date}"
        )

        try:
            # 1. 解析 assignee 列表
            assignee_list = [
                email.strip() for email in assignee.split(",") if email.strip()
            ]
            if not assignee_list:
                logger.warning("没有提供有效的 assignee")
                return {}

            _type = "userWorklogInfo"
            # ✅ 改为字典结构：email -> worklog list
            result_map: Dict[str, List[Dict[str, Any]]] = {}

            # 2. 先从 Redis 获取每个用户的数据，记录哪些用户缺失
            missing_emails = []
            for email in assignee_list:
                worklog_data_values = RedisUtils.get_instance().get_ranged_data(
                    _type, email, start_date, end_date
                )
                if worklog_data_values is None:
                    missing_emails.append(email)
                    result_map[email] = []  # 初始化空列表
                else:
                    logger.info(
                        f"从Redis中获取到任务工时数据: assignee={email}, 记录数={len(worklog_data_values)}"
                    )
                    result_map[email] = worklog_data_values  # 直接赋值

            # 3. 如果所有用户都有缓存，直接返回
            if not missing_emails:
                logger.info("所有用户工时数据均来自 Redis 缓存")
                return result_map

            # 4. 批量调用 API 获取缺失用户的数据
            logger.info(f"Redis 缺失，从 API 批量获取工时数据: assignees={assignee}")
            params = {
                "startDate": start_date,
                "endDate": end_date,
                "userName": assignee,  # ✅ 传入原始的多个邮箱
                "maxResults": 1000,
            }

            timesheet_data = call_restful_api(
                "jira-timesheet",
                api_endpoint="jira-timesheet-worklog",
                request_params=params,
            )

            if timesheet_data and isinstance(timesheet_data, dict):
                api_work_logs = timesheet_data.get("values", [])
                logger.info(f"从API获取到 {len(api_work_logs)} 条任务工时记录（批量）")

                # 5. 按 email 分组
                worklogs_by_email: Dict[str, List[Dict[str, Any]]] = {}
                for entry in api_work_logs:
                    # 根据实际字段提取邮箱，示例使用 entry.get("author", {}).get("userName")
                    user_email = entry.get("author", {}).get("userName", "")
                    user_email = user_email.strip()

                    # 只处理目标用户
                    if user_email in assignee_list:
                        if user_email not in worklogs_by_email:
                            worklogs_by_email[user_email] = []
                        worklogs_by_email[user_email].append(entry)

                # 6. 缓存到 Redis，并更新 result_map 中缺失用户的数据
                for email in assignee_list:
                    _key = f"{_type}:{email}"
                    user_logs = worklogs_by_email.get(email, [])

                    # ✅ 更新 result_map：只覆盖缺失用户的数据
                    if email in missing_emails:
                        result_map[email] = user_logs

                    # 缓存到 Redis（每天一条）
                    for entry in user_logs:
                        start_date_of_entry = entry.get("startDate", "")
                        RedisUtils.get_instance().set_data_with_date(
                            _key, start_date_of_entry, entry
                        )

                    # 补全起止日期空缓存（防穿透）
                    if (
                        RedisUtils.get_instance().is_key_exist(f"{_key}:{start_date}")
                        == 0
                    ):
                        RedisUtils.get_instance().set_data_with_date(
                            _key, start_date, {}
                        )
                    if (
                        RedisUtils.get_instance().is_key_exist(f"{_key}:{end_date}")
                        == 0
                    ):
                        RedisUtils.get_instance().set_data_with_date(_key, end_date, {})

            else:
                logger.warning("API 返回空或无效数据，仅返回 Redis 中的数据")

            return result_map

        except Exception as e:
            logger.error(f"获取任务工时失败: {e}", exc_info=True)
            # 确保出错时也返回字典结构
            return {email.strip(): [] for email in assignee.split(",") if email.strip()}

    async def fetch_assignee_attendance_data(
        self, assignee: str, start_date: str, end_date: str
    ):
        """
        获取用户在指定日期范围内的可用工时

        参数:
            assignee: 用户邮箱地址
            start_date: 开始日期 (格式: YYYY-MM-DD)
            end_date: 结束日期 (格式: YYYY-MM-DD)

        返回:
            可用工时数
        """
        logger.info(
            f"获取用户考勤数据: assignee={assignee}, start_date={start_date}, end_date={end_date}"
        )
        try:
            # 获取考勤数据
            attendance_data = await BstOA.get_instance().calculate_work_hours(
                start_date, end_date, assignee
            )
            logger.info(
                f"考勤数据获取完成: assignee={assignee}, 数据项数={len(attendance_data) if attendance_data else 0}"
            )
            return attendance_data
        except Exception as e:
            logger.error(f"获取考勤数据失败: {e}", exc_info=True)
            return {}

    def get_year_str_from_date(self, date_str: str) -> str:
        """
        获取指定日期字符串对应的年份（字符串格式）

        参数:
            date_str (str): 日期字符串，格式为 "YYYY-MM-DD"

        返回:
            str: 日期对应的年份（字符串格式）

        抛出:
            ValueError: 如果日期格式不正确或无法解析
        """
        logger.debug(f"从日期获取年份: {date_str}")
        try:
            # 解析日期字符串
            date = datetime.strptime(date_str, "%Y-%m-%d")
            year_str = str(date.year)
            logger.debug(f"日期 {date_str} 对应年份: {year_str}")
            # 返回年份作为字符串
            return year_str
        except ValueError as e:
            error_msg = f"无效的日期格式: {date_str}，请确保格式为 YYYY-MM-DD"
            logger.error(error_msg)
            raise ValueError(error_msg) from e

    async def fetch_assignee_leave_data(
        self, assignee: str, start_date: str, end_date: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取多个用户在指定日期范围内的请假记录（按用户分组返回）

        参数:
            assignee: 用户邮箱地址，多个用逗号分隔（例如：a@b.com,c@d.com）
            start_date: 开始日期 (格式: YYYY-MM-DD)
            end_date: 结束日期 (格式: YYYY-MM-DD)

        返回:
            Dict[str, List[Dict]]: key 是 email，value 是该用户的请假记录列表
        """
        logger.info(
            f"获取用户请假数据: assignees={assignee}, start_date={start_date}, end_date={end_date}"
        )

        try:
            # 1. 解析 assignee 列表
            assignee_list = [
                email.strip() for email in assignee.split(",") if email.strip()
            ]
            if not assignee_list:
                logger.warning("没有提供有效的 assignee")
                return {}

            _type = "userLeaveInfo"
            result_map: Dict[str, List[Dict[str, Any]]] = {}
            missing_emails = []

            # 2. 先从 Redis 获取每个用户的数据
            for email in assignee_list:
                leave_data_values = RedisUtils.get_instance().get_ranged_data(
                    _type, email, start_date, end_date
                )
                if leave_data_values is None:
                    missing_emails.append(email)
                    result_map[email] = []  # 初始化为空列表
                else:
                    logger.info(
                        f"从Redis中获取到请假数据: assignee={email}, 记录数={len(leave_data_values)}"
                    )
                    result_map[email] = leave_data_values

            # 3. 如果所有用户都有缓存，直接返回
            if not missing_emails:
                logger.info("所有用户请假数据均来自 Redis 缓存")
                return result_map

            # 4. 批量调用 API 获取缺失用户的数据
            logger.info(f"Redis 缺失，从 API 批量获取请假数据: assignees={assignee}")
            year = self.get_year_str_from_date(start_date)
            params = {
                "startDate": start_date,
                "endDate": end_date,
                "year": year,
                "userName": assignee,  # 传入多个用户，后端应支持批量查询
                "maxResults": 150,
            }

            leave_data = call_restful_api(
                "jira-timesheet",
                api_endpoint="jira-timesheet-leave",
                request_params=params,
            )

            if leave_data and isinstance(leave_data, dict):
                api_leave_records = leave_data.get("values", [])
                logger.info(f"从API获取到 {len(api_leave_records)} 条请假记录（批量）")

                # 5. 按 email 分组
                leaves_by_email: Dict[str, List[Dict[str, Any]]] = {}
                for entry in api_leave_records:
                    # 根据实际字段提取邮箱，示例使用 entry.get("user", {}).get("userName")
                    user_email = entry.get("user", {}).get("userName", "")
                    user_email = user_email.strip()

                    # 只处理目标用户
                    if user_email in assignee_list:
                        if user_email not in leaves_by_email:
                            leaves_by_email[user_email] = []
                        leaves_by_email[user_email].append(entry)

                # 6. 更新 result_map 并缓存到 Redis
                for email in assignee_list:
                    _key = f"{_type}:{email}"
                    user_leaves = leaves_by_email.get(email, [])

                    # ✅ 只更新缺失用户的数据
                    if email in missing_emails:
                        result_map[email] = user_leaves

                    # 缓存每条记录（按 leaveTime）
                    for entry in user_leaves:
                        leave_time = entry.get("leaveTime", "")
                        if leave_time:
                            RedisUtils.get_instance().set_data_with_date(
                                _key, leave_time, entry
                            )
                            logger.debug(
                                f"将请假数据存入Redis: email={email}, date={leave_time}"
                            )

                    # 防缓存穿透：补全起止日期空值
                    start_key = f"{_key}:{start_date}"
                    end_key = f"{_key}:{end_date}"
                    if RedisUtils.get_instance().is_key_exist(start_key) == 0:
                        RedisUtils.get_instance().set_data_with_date(
                            _key, start_date, {}
                        )
                    if RedisUtils.get_instance().is_key_exist(end_key) == 0:
                        RedisUtils.get_instance().set_data_with_date(_key, end_date, {})

            else:
                logger.warning("API 返回空或无效数据，仅返回 Redis 中的数据")

            return result_map

        except Exception as e:
            logger.error(f"获取请假记录失败: {e}", exc_info=True)
            # 出错时也返回字典结构，避免上游解析错误
            return {email.strip(): [] for email in assignee.split(",") if email.strip()}

    async def fetch_assignee_leave_data_mock(
        self, assignee: str, start_date: str, end_date: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Mock 实现：根据 assignee（邮箱）、start_date、end_date 返回模拟的请假记录
        """
        # 解析日期
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format: {e}")

        # 支持多个邮箱
        emails = [email.strip() for email in assignee.split(",") if email.strip()]

        # 请假类型映射
        leave_types = [
            {"typeId": 1, "typeName": "休假", "isPaid": 0},
            {"typeId": 2, "typeName": "病假", "isPaid": 1},
            {"typeId": 3, "typeName": "年假", "isPaid": 0},
            {"typeId": 4, "typeName": "调休", "isPaid": 0},
        ]

        # 构建用户信息模板
        def make_user_info(email: str) -> Dict[str, Any]:
            name_part = email.split("@")[0]
            display_name = "".join([f"{c.upper()}" for c in name_part if c.islower()])[
                :2
            ]
            display_name = f"测试{display_name}"
            user_key = f"JIRAUSER{random.randint(10000, 99999)}"
            return {
                "userKey": user_key,
                "avatar": f"https://jira.bstai.top/secure/useravatar?size=xsmall&avatarId={random.randint(10300, 10400)}",
                "userName": email,
                "displayName": display_name,
                "emailAddress": email,
                "isActive": True,
                "isDel": False,
            }

        # 生成模拟数据
        result = []
        current = start
        day_offset = 0

        while current <= end:
            for email in emails:
                # 随机决定当天是否请假（约 30% 概率）
                if random.random() < 0.3:
                    leave_type = random.choice(leave_types)
                    seconds = random.choice([10800, 18000, 28800])  # 3h, 5h, 8h
                    daily_time = (
                        "8h"
                        if seconds == 28800
                        else ("5h" if seconds == 18000 else "3h")
                    )

                    record = {
                        "id": 1000 + len(result),
                        "user": make_user_info(email),
                        "typeId": leave_type["typeId"],
                        "typeName": leave_type["typeName"],
                        "isPaid": leave_type["isPaid"],
                        "leaveTime": current.strftime("%Y-%m-%d"),
                        "leaveSeconds": seconds,
                        "dailyLeaveTime": daily_time,
                    }
                    result.append(record)
            current = start + timedelta(days=day_offset)
            day_offset += 1

        # 按 leaveTime 排序
        result.sort(key=lambda x: x["leaveTime"])

        await asyncio.sleep(0.1)  # 模拟网络延迟
        return result

    async def fetch_assignee_datas(self, assignee: str, start_date: str, end_date: str):
        logger.info(
            f"并发获取用户所有数据: assignee={assignee}, start_date={start_date}, end_date={end_date}"
        )
        tasks = [
            self.fetch_assignee_leave_data(assignee, start_date, end_date),
            self.fetch_assignee_attendance_data(assignee, start_date, end_date),
            self.fetch_assignee_work_logs(assignee, start_date, end_date),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task_names = ["请假数据", "考勤数据", "任务工时数据"]
                logger.error(f"获取{task_names[i]}时发生异常: {result}")

        logger.info(f"用户所有数据获取完成: assignee={assignee}")
        return {
            "leave_data": results[0] if not isinstance(results[0], Exception) else [],
            "attendance_data": (
                results[1] if not isinstance(results[1], Exception) else {}
            ),
            "work_log_data": (
                results[2] if not isinstance(results[2], Exception) else []
            ),
        }

    def calculate_task_efficiency(self, task: Dict[str, Any]) -> Dict[str, float]:
        """
        计算单个任务的效率指标

        参数:
            task: 包含任务详细信息的字典

        返回:
            包含实际工时、预估工时和效率比的字典
        """
        logger.debug(f"计算任务效率: task={task.get('key', 'unknown')}")
        try:
            actual_hours = task.get("actual_hours", 0)
            estimated_hours = task.get("estimated_hours", 0)

            efficiency_ratio = 0
            if estimated_hours > 0:
                efficiency_ratio = actual_hours / estimated_hours

            # 计算效率修正系数
            efficiency_correction = 1.0
            if efficiency_ratio > 1:
                efficiency_correction = 1 - (efficiency_ratio - 1) * 0.5

            result = {
                "actual_hours": actual_hours,
                "estimated_hours": estimated_hours,
                "efficiency_ratio": efficiency_ratio,
                "efficiency_correction": efficiency_correction,
            }
            logger.debug(f"任务效率计算结果: {result}")
            return result

        except Exception as e:
            logger.error(f"计算任务效率失败: {e}", exc_info=True)
            return {
                "actual_hours": 0,
                "estimated_hours": 0,
                "efficiency_ratio": 0,
                "efficiency_correction": 1.0,
            }

    def sum_assignee_times(self, _data: List, _type: str):
        logger.debug(f"汇总用户工时: type={_type}")
        total_hours = 0
        total_seconds = 0
        if _data and isinstance(_data, List):
            for entry in _data:
                total_seconds += entry.get(_type, 0)
        if total_seconds > 0:
            total_hours = total_seconds / 3600
        logger.info(f"总 {_type} 工时: {total_hours} 小时")
        return total_hours

    def sum_assignee_attendance_hours(self, attendance_data):
        logger.debug("汇总用户考勤工时")
        attendance_worktime = 0
        attendance_actual_worktime = 0
        if attendance_data:
            for day in attendance_data.values():
                attendance_worktime += day["worktime"]
            for day in attendance_data.values():
                attendance_actual_worktime += day["actual_worktime"]

        logger.debug(
            f"考勤工时汇总结果: worktime={attendance_worktime}, actual_worktime={attendance_actual_worktime}"
        )
        return attendance_worktime, attendance_actual_worktime

    async def _collect_metrics(
        self, assignee: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        logger.info(
            f"收集用户指标数据: assignee={assignee}, start_date={start_date}, end_date={end_date}"
        )
        # 总工时
        total_seconds = 0
        # 优先级总工时
        priority_total_seconds = 0

        keytask_total_seconds = 0
        # 已完成任务
        done_task_num = 0
        # 关键任务
        key_task_num = 0
        keytask_total_seconds = 0
        metric_results = {}

        result = await self.fetch_assignee_datas(assignee, start_date, end_date)

        attendance_data = result.get("attendance_data")
        leave_data = result.get("leave_data")
        work_log_data = result.get("work_log_data")
        done_tasks = {}
        key_tasks = {}

        logger.info(
            f"处理任务工时数据，共 {len(work_log_data) if work_log_data else 0} 条记录"
        )
        for entry in work_log_data:
            projectKey = entry.get("projectKey")
            issueId = entry.get("issueId")
            timeworked = entry.get("timeWorked", 0)
            # if projectKey and issueId:
            #     issueInstance = ProjectIssueCache.get_project_issue(projectKey,issueId)
            #     if issueInstance:
            #         issue_priority=issueInstance.get("priority")
            #         issue_status=issueInstance.get("status")
            #         issue_keytask=issueInstance.get("keytask")
            #         done_tasks[issueId]="false"
            #         if issue_status == "完成":
            #             done_tasks[issueId]="true"

            #         if issue_priority in self.PRIORITY_FACTORS:
            #             priority_total_seconds += timeworked * self.PRIORITY_FACTORS[issue_priority]
            #         else:
            #             priority_total_seconds += timeworked

            #         if issue_keytask == "true":
            #             key_tasks[issueId]="true"
            #             keytask_total_seconds += timeworked

            issue_priority = "P2"
            issue_status = "完成"
            issue_keytask = "true"
            done_tasks[issueId] = "false"
            if issue_status == "完成":
                done_tasks[issueId] = "true"

            if issue_priority in self.PRIORITY_FACTORS:
                priority_total_seconds += (
                    timeworked * self.PRIORITY_FACTORS[issue_priority]
                )
            else:
                priority_total_seconds += timeworked

            if issue_keytask == "true":
                key_tasks[issueId] = "true"
                keytask_total_seconds += timeworked

            total_seconds += timeworked

        attendance_worktimeHours, attendance_actual_worktimeHours = (
            self.sum_assignee_attendance_hours(attendance_data)
        )
        leave_hours = self.sum_assignee_times(leave_data, "leaveSeconds")

        done_task_num = 0
        key_task_num = len(key_tasks)
        total_task_num = len(done_tasks)
        for key, value in done_tasks.items():
            if value == "true":
                done_task_num += 1

        metric_results[assignee] = {
            "worktime_total_hours": total_seconds / 3600,
            "worktime_priority_total_hours": priority_total_seconds / 3600,
            "worktime_keytask_total_hours": keytask_total_seconds / 3600,
            "done_task_num": done_task_num,
            "total_task_num": total_task_num,
            "key_task_num": key_task_num,
            "attendance_worktimeHours": attendance_worktimeHours,
            "attendance_actual_worktimeHours": attendance_actual_worktimeHours,
            "leave_hours": leave_hours,
        }
        logger.info(f"用户指标数据收集完成: assignee={assignee}")
        return metric_results

    async def calculate_base_saturation_assignee(
        self, assignee: str, start_date: str, end_date: str
    ) -> Dict[str, Any]:
        logger.info(
            f"计算用户基础饱和度: assignee={assignee}, start_date={start_date}, end_date={end_date}"
        )
        try:
            saturation_results = {}
            metric_results = {}
            logger.info(f"正在分析 {assignee} 的工作饱和度...")
            metrics_result = await self._collect_metrics(assignee, start_date, end_date)
            metric_results[assignee] = metrics_result.get(assignee)

            calculator = SaturationCalculator()

            # 计算每个员工的饱和度
            calculator.load_assignee_metrics(assignee, metric_results)
            result = calculator.get_saturation_results(assignee)

            # 存储结果
            saturation_results[assignee] = result

            logger.info(
                f"饱和度计算结果: " + json.dumps(result, ensure_ascii=False, indent=2)
            )
            logger.info(
                f"加权饱和度: {result['加权工作饱和度']:.2%} 基础工作饱和度: {result['基础工作饱和度']:.2%}"
            )
            return saturation_results
        except Exception as e:
            logger.error(f"工作饱和度分析失败: {e}", exc_info=True)
            return {"error": str(e)}

    async def calculate_base_saturation(
        self,
        project_key: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        分析项目关键任务承接人的工作饱和度

        参数:
            project_key: 项目标识符（如"WORK"）
            start_date: 分析开始日期 (格式: YYYY-MM-DD)
            end_date: 分析结束日期 (格式: YYYY-MM-DD)

        返回:
            包含各承接人工作饱和度的分析结果
        """
        logger.info(
            f"计算项目基础饱和度: project_key={project_key}, start_date={start_date}, end_date={end_date}"
        )
        try:
            saturation_results = {}
            project_results = {}

            project_results = CriticalTaskProject.find_critical_path(project_key)
            critical_tasks = project_results.get(
                f"项目{project_key}关键路径任务列表", []
            )
            if not critical_tasks:
                logger.warning(f"项目 {project_key} 没有关键任务")
                return saturation_results

            # 按承运人分组任务
            tasks_by_assignee = defaultdict(list)
            for task in critical_tasks:
                assignee = task["assignee"]
                if assignee:
                    tasks_by_assignee[assignee].append(task)

            logger.info(f"项目 {project_key} 有 {len(tasks_by_assignee)} 个任务承接人")
            # 遍历每个承运人

            tasks = [
                self.calculate_base_saturation_assignee(assignee, start_date, end_date)
                for assignee in tasks_by_assignee
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"计算用户饱和度时发生异常: {result}")
                    continue

                for assignee, value in result.items():
                    saturation_results[assignee] = value

            logger.info(f"项目 {project_key} 的工作饱和度分析完成")
            total_results = {
                "saturation_results": saturation_results,
                "project_results": project_results,
            }
            return total_results
        except Exception as e:
            logger.error(f"工作饱和度分析失败: {e}", exc_info=True)
            return {"error": str(e)}

    def _get_saturation_level(self, saturation: float) -> str:
        """
        根据饱和度获取等级描述

        饱和度区间 | 等级 | 状态描述
        <60%      | 不饱和 | 可分配新任务
        60%-80%  | 合理   | 工作负荷均衡
        80%-95%  | 饱和   | 需关注任务排期合理性
        >95%      | 过载   | 存在延期风险，需调配资源

        参数:
            saturation: 饱和度百分比

        返回:
            饱和度等级描述
        """
        logger.debug(f"获取饱和度等级: {saturation}")
        if saturation < 60:
            level = "不饱和"
        elif 60 <= saturation < 80:
            level = "合理"
        elif 80 <= saturation < 95:
            level = "饱和"
        else:
            level = "过载"

        logger.info(f"饱和度等级: {level} ({saturation:.1f}%)")
        return level


# def test(start_date: str, end_date: str, assignee: str) :
#     # 示例使用
#     # 假设我们已经实现了以下函数
#     from critical_path_analyzer.http_utils import call_restful_api
#     from critical_path_analyzer.config_util import load_config, load_field_mapping
#     from critical_path_analyzer.data_processor import extract_task_info
#     from critical_path_analyzer.aoe_graph import AOEGraph

#     # 创建分析器实例
#     analyzer = HumanEfficiencyAnalyzer(jira=None, oa=BstOA.get_instance())

#     # 设置分析参数
#     project_key = "WORK"
#     start_date = "2025-04-01"
#     end_date = "2025-04-30"

#     # 执行分析
#     results = analyzer.calculate_saturation(project_key, start_date, end_date)

#     # 输出结果
#     print("\n=== 工作饱和度分析报告 ===\n")
#     for assignee, data in results.items():
#         if "error" in data:
#             print(f"错误: {data['error']}")
#             continue

#         print(f"承运人: {assignee}")
#         print(f"基础饱和度: {data['base_saturation']}%")
#         print(f"加权饱和度: {data['weighted_saturation']}%")
#         print(f"饱和度等级: {data['saturation_level']}")
#         print(f"可用工时: {data['available_hours']}小时")
#         print(f"关键任务工时: {data['critical_hours']}小时")
#         print(f"非关键任务工时: {data['non_critical_hours']}小时")
#         print(f"处理任务数: {data['task_count']}个")
#         print("-" * 30)


# async def get_attendance_records() -> Optional[Dict[str, Any]]:
#     logger.info("获取考勤记录")
#     project_key = "WORK"
#     start_date = "2025-04-01"
#     end_date = "2025-04-30"
#     assignee = "zishu.lv@bst.ai"
#     # 直接 await 异步方法，不要包裹在 run_in_executor 中
#     result = await BstOA.get_instance().get_kq_data(
#         startDate=start_date, endDate=end_date, assignee=assignee
#     )
#     logger.info("考勤记录获取完成")
#     logger.debug(json.dumps(result, ensure_ascii=False, indent=2))
#     return result


if __name__ == "__main__":
    # 配置日志
    log_dir = "log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "human_efficiency_main.log")),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)
    # 创建分析器实例
    analyzer = HumanEfficiencyAnalyzer.get_instance()

    # 设置分析参数
    project_key = "ISPCV20S"
    start_date = "2025-01-01"
    end_date = "2025-04-30"
    assignee = "guobin.li@bst.ai"
    # RedisUtils.get_instance()
    # 执行分析
    # analyzer.calculate_base_saturation (project_key,start_date, end_date)
    # analyzer.fetch_assignee_leave_data (assignee,start_date, end_date)

    # loop = asyncio.new_event_loop()
    # try:
    #     # result = loop.run_until_complete(
    #     #     analyzer.calculate_base_saturation("WORK", start_date, end_date)
    #     # )
    #     result = loop.run_until_complete(
    #         HumanEfficiencyAnalyzer.get_instance().fetch_assignee_work_logs(
    #             assignee=assignee,
    #             start_date=start_date,
    #             end_date=end_date,
    #         )
    #     )
    #     logger.info("获取结果:", result)
    # except Exception as e:
    #     logger.error(f"执行过程中发生错误: {e}", exc_info=True)
    # finally:
    #     loop.close()
