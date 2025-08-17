import asyncio
from datetime import datetime, timedelta
import logging
import os
import random
from mcp.server.fastmcp import FastMCP

from bst_mcp_server.bst_oa import BstOA
from bst_mcp_server.config_util import load_config
from bst_mcp_server.http_utils import call_restful_api
from bst_mcp_server.human_efficiency import HumanEfficiencyAnalyzer
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

from flask import json


# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_hr_mcp_server.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


jira_timesheet_config_root = "jira-timesheet"
jira_timesheet_leave_endpoint = "jira-timesheet-leave"
jira_timesheet_calworkday_endpoint = "jira-timesheet-calworkday"

server_config = load_config().get("server_config", {})
bst_hr_mcp_server_config = server_config.get("bst_hr_mcp_server", {})


# --- MCP Server Initialization ---
bst_hr_mcp_server = FastMCP(
    "bst_hr_mcp_server",
    description="提供HR系统的原始信息查询",
    dependencies=["sqlite3"],
    host=bst_hr_mcp_server_config.get("host", "0.0.0.0"),
    port=bst_hr_mcp_server_config.get("port", 8003),
)


@bst_hr_mcp_server.tool()
async def get_leave_record(
    userName: str = Field(
        description="员工邮箱，必须以 @bst.ai 结尾，支持多个邮箱，逗号分隔"
    ),
    startDate: str = Field(
        description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
    endDate: str = Field(
        description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
) -> Optional[Dict[str, List[Dict[str, Any]]]]:  # ✅ 改为 Dict 类型
    """
    【工具名称】get_leave_record
    【功能描述】根据用户输入，查询指定员工在指定时间范围内的请假记录。

    【返回值结构说明】
    :return: 返回值是一个字典，key 是员工邮箱（str），value 是该员工的请假记录列表（List[Dict]）。
             每条记录包含以下字段：
    - id (int): 请假记录的唯一标识符
    - user (dict): 员工信息
    - typeId (int): 请假类型 ID
    - typeName (str): 请假类型名称（如 "休假"）
    - isPaid (int): 是否带薪（0 表示带薪）
    - leaveTime (str): 请假日期（格式：YYYY-MM-DD）
    - leaveSeconds (int): 请假时长（单位：秒）
    - dailyLeaveTime (str): 请假时长的可读格式（如 "3h", "1d"）

    【示例返回】
    {
      "shoudong.chen@bst.ai": [
        {
          "id": 7,
          "user": {
            "userKey": "JIRAUSER10459",
            "avatar": "https://bst-agent.com:8081/secure/useravatar?size=xsmall&avatarId=10341",
            "userName": "shoudong.chen@bst.ai",
            "displayName": "陈寿东",
            "emailAddress": "shoudong.chen@bst.ai",
            "isActive": true,
            "isDel": false
          },
          "typeId": 1,
          "typeName": "休假",
          "isPaid": 0,
          "leaveTime": "2025-02-27",
          "leaveSeconds": 3600,
          "dailyLeaveTime": "1h"
        }
      ],
      "zishu.lv@bst.ai": []
    }
    """
    logger.info(
        f"查询请假记录: userName={userName}, startDate={startDate}, endDate={endDate}"
    )

    try:
        # ✅ 直接返回 fetch_assignee_leave_data 的原生结构
        result = await HumanEfficiencyAnalyzer.get_instance().fetch_assignee_leave_data(
            assignee=userName,
            start_date=startDate,
            end_date=endDate,
        )

        logger.info(
            f"请假记录查询完成: userName={userName}, 用户数={len(result)}, 总记录数={sum(len(recs) for recs in result.values())}"
        )
        logger.info(json.dumps(result, ensure_ascii=False, indent=2))

        return result  # ✅ 原样返回 Dict[str, List[Dict]]

    except Exception as e:
        logger.error(f"查询请假记录时发生错误: {e}", exc_info=True)
        # ✅ 错误时也返回 Dict 结构，而不是 {"error": ...}
        email_list = [email.strip() for email in userName.split(",") if email.strip()]
        return {email: [] for email in email_list}


class GetCalWorkdayToolOutput(BaseModel):
    workdays: List[str] = Field(description="工作日列表，格式：YYYY-MM-DD")
    holidays: List[str] = Field(
        description="非工作日列表（周末、节假日），格式：YYYY-MM-DD"
    )


@bst_hr_mcp_server.tool()
async def get_calworkday_tool(
    startDate: str = Field(
        description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
    endDate: str = Field(
        description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
) -> GetCalWorkdayToolOutput:
    """
    【工具名称】get_calworkday_tool
    【功能描述】根据给定日期范围计算工作日与非工作日列表的工作日、非工作日(周末，节假日)的列表。
    :return: 获取一段日期内的工作日、非工作日列表
    """
    params = {
        "startDate": startDate,
        "endDate": endDate,
        "maxResults": 1000,
    }
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: call_restful_api(
            jira_timesheet_config_root,
            jira_timesheet_calworkday_endpoint,
            request_params=params,
        ),
    )

    if not isinstance(result, dict):
        raise ValueError("API 返回数据格式错误：期望 dict")

    workdays = result.get("workdays", [])
    holidays = result.get("holidays", [])

    # ✅ 返回 Pydantic 模型实例（会自动验证类型）
    return GetCalWorkdayToolOutput(workdays=workdays, holidays=holidays)


# @bst_hr_mcp_server.tool()
# async def get_user_info(username: str) -> Optional[Dict[str, Any]]:
#     """
#     【工具名称】get_user_info

#     【功能描述】根据提供的员工邮箱，查询该员工的详细信息。

#     【返回值结构说明】
#     返回值是一个字典，包含员工的详细信息字段，主要字段如下：

#     - companystartdate (str): 入职公司日期（格式：YYYY-MM-DD）
#     - createdate (str): 创建日期（格式：YYYY-MM-DD）
#     - workstartdate (str): 实际工作起始日期（格式：YYYY-MM-DD）
#     - subcompanyid1 (str): 子公司ID
#     - subcompanyname (str): 所属子公司名称（如 "武汉"）
#     - joblevel (str): 职级
#     - startdate (str): 开始日期（格式：YYYY-MM-DD）
#     - jobgroupname (str): 工作组名称
#     - subcompanycode (str): 子公司代码
#     - id (str): 员工唯一标识符
#     - nativeplace (str): 籍贯
#     - loginid (str): 登录ID
#     - jobtitlecode (str): 职位代码
#     - degree (str): 学历（如 "硕士"）
#     - classification (str): 分类
#     - residentplace (str): 居住地址
#     - enddate (str): 结束日期（格式：YYYY-MM-DD）
#     - maritalstatus (str): 婚姻状况（如 "未婚"）
#     - departmentname (str): 所属部门名称（如 "CVIS"）
#     - folk (str): 民族
#     - status (str): 员工状态（如 "1" 表示在职）
#     - birthday (str): 出生日期（格式：YYYY-MM-DD）
#     - jobtitlename (str): 职位名称（如 "嵌入式软件开发工程师"）
#     - departmentcode (str): 部门代码
#     - seclevel (str): 安全级别
#     - workcode (str): 工号（如 "CN-WH-0185"）
#     - sex (str): 性别（如 "男", "女"）
#     - mobile (str): 移动电话
#     【示例返回】
#     {
#       "companystartdate": "2022-08-10",
#       "createdate": "2022-08-10",
#       "workstartdate": "2020-07-22",
#       "subcompanyid1": "4",
#       "subcompanyname": "武汉",
#       "startdate": "2022-08-10",
#       "jobgroupname": "Default",
#       "subcompanycode": "WH",
#       "id": "1224",
#       "nativeplace": "湖北省",
#       "certificatenum": "",
#       "height": "0",
#       "loginid": "marid.lv",
#       "jobtitlecode": "JOB05080300-20",
#       "degree": "硕士",
#       "classification": "3",
#       "residentplace": "湖北省武汉市青山区龙湖冠寓",
#       "lastname": "吕自书",
#       "healthinfo": "",
#       "enddate": "2025-08-09",
#       "maritalstatus": "未婚",
#       "departmentname": "CVIS",
#       "folk": "汉族",
#       "birthday": "",
#       "jobtitlename": "嵌入式软件开发工程师",
#       "departmentcode": "WH-BST-05-08-03-00",
#       "seclevel": "0",
#       "workcode": "CN-WH-0185",
#       "sex": "男",
#       "mobile": ""
#     }

#     :param username: 员工邮箱地址（必须以 @bst.ai 结尾）
#     :return: 返回结构化的员工信息，格式为 Dict[str, Any]
#     """
#     print(f"[DEBUG] get_user_info_tool called with: {username}")

#     result = BstOA.get_instance().get_userInfo(username)

#     logger.info(json.dumps(result, ensure_ascii=False, indent=2))
#     return result


@bst_hr_mcp_server.tool()
async def get_attendance_records(
    userName: str = Field(
        description="员工邮箱，必须以 @bst.ai 结尾，支持多个邮箱，逗号分隔"
    ),
    startDate: str = Field(
        description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
    endDate: str = Field(
        description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
) -> Optional[Dict[str, Any]]:
    """
    【工具名称】get_attendance_records
    【功能描述】根据用户输入，查询指定员工在指定时间范围内的考勤记录。
    【返回值结构说明】
    返回值是一个字典，键为日期（格式：YYYY-MM-DD），值为当天的考勤记录列表。
    每条记录包含以下字段：
    - signfrom (str): 打卡来源（如 "外部考勤数据同步"）
    - signTime (str): 打卡时间（格式：HH:mm:ss）
    - signStatus (str): 打卡状态（如 "正常", "迟到", "早退"）
    - addr (str): 打卡地点（如 "武汉32楼电梯左"）
    - workTime (str): 应打卡时间（格式：HH:mm）

    【示例返回】
    {
      "2025-04-01": [
        {
          "signfrom": "外部考勤数据同步",
          "signTime": "09:06:24",
          "signStatus": "正常",
          "addr": "武汉32楼电梯左",
          "workTime": "09:00"
        },
        {
          "signfrom": "外部考勤数据同步",
          "signTime": "18:20:22",
          "signStatus": "正常",
          "addr": "武汉32楼电梯左",
          "workTime": "18:00"
        }
      ]
    }

    :param params: 请求参数字典，包含 userName, startDate, endDate 等信息
    :return: 返回结构化考勤记录，格式为 Dict[str, List[Dict]]
    """

    # result = await BstOA.get_instance().get_kq_data_mock(
    #     startDate=startDate,
    #     endDate=endDate,
    #     assignee=userName,
    # )
    result = await get_kq_data_mock(
        startDate=startDate,
        endDate=endDate,
        assignee=userName,
    )
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def get_kq_data_mock(
    assignee: str, startDate: str, endDate: str
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    Mock 实现：符合「弹性上班（9:30前正常），午休1小时，下班顺延满足8小时工作」的规则
    """
    try:
        start = datetime.strptime(startDate, "%Y-%m-%d")
        end = datetime.strptime(endDate, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Invalid date format: {e}")

    if start > end:
        return {}

    emails = [email.strip() for email in assignee.split(",") if email.strip()]
    if not emails:
        return {}

    # 固定配置
    SIGN_FROM = "外部考勤数据同步"
    CUTOFF_TIME = datetime.min + timedelta(
        hours=9, minutes=30
    )  # 9:30 作为是否迟到的判断点
    LUNCH_BREAK = timedelta(hours=1)  # 午休1小时，不计入工时

    ADDRESSES = [
        "武汉32楼电梯左",
        "武汉32楼前台",
        "武汉31楼茶水间",
        "远程打卡",
        "北京总部A区",
        "上海分公司2楼",
    ]

    result: Dict[str, List[Dict[str, Any]]] = {}
    current = start

    while current <= end:
        current_date = current.strftime("%Y-%m-%d")
        result[current_date] = []

        for email in emails:
            # 10% 概率当天无打卡（缺勤）
            if random.random() < 0.1:
                continue

            # === 上班打卡 ===
            # 模拟打卡时间：8:30 - 10:30
            base_arrival = datetime.combine(
                current.date(), datetime.min.time()
            ) + timedelta(hours=8, minutes=30)
            minutes_offset = random.randint(-30, 90)  # 8:00 - 10:00
            actual_arrival = base_arrival + timedelta(minutes=minutes_offset)

            sign_time_morning = actual_arrival.strftime("%H:%M:%S")
            work_time_morning = "09:00"

            # 判断是否迟到：9:30 前为正常
            cutoff = datetime.combine(current.date(), CUTOFF_TIME.time())
            if actual_arrival <= cutoff:
                sign_status_morning = "正常"
            else:
                sign_status_morning = "迟到"

            result[current_date].append(
                {
                    "signfrom": SIGN_FROM,
                    "signTime": sign_time_morning,
                    "signStatus": sign_status_morning,
                    "addr": random.choice(ADDRESSES),
                    "workTime": work_time_morning,
                }
            )

            # === 下班打卡 ===
            # 应下班时间 = 到岗时间 + 8小时工作 + 1小时午休 = +9小时
            expected_leave_time = actual_arrival + timedelta(hours=9)
            # 实际下班时间：在 expected_leave_time 前后浮动
            leave_offset = random.randint(-15, 60)  # 可早退15分钟，可晚走60分钟
            actual_leave = expected_leave_time + timedelta(minutes=leave_offset)

            sign_time_evening = actual_leave.strftime("%H:%M:%S")
            work_time_evening = expected_leave_time.strftime("%H:%M")  # 应打卡时间

            # 判断下班状态
            if actual_leave >= expected_leave_time:
                sign_status_evening = "正常"
            elif actual_leave >= (expected_leave_time - timedelta(minutes=15)):
                sign_status_evening = "早退"
            else:
                sign_status_evening = "严重早退"

            result[current_date].append(
                {
                    "signfrom": SIGN_FROM,
                    "signTime": sign_time_evening,
                    "signStatus": sign_status_evening,
                    "addr": random.choice(ADDRESSES),
                    "workTime": work_time_evening,
                }
            )

        current += timedelta(days=1)

    await asyncio.sleep(0.1)  # 模拟延迟
    return result
