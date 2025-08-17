import asyncio
import logging
import os
from mcp.server.fastmcp import FastMCP

from bst_mcp_server.aoe_graph import find_critical_path
from bst_mcp_server.bst_oa import BstOA
from bst_mcp_server.config_util import load_config, load_field_mapping
from bst_mcp_server.critical_task_project import CriticalTaskProject
from bst_mcp_server.http_utils import call_restful_api
from bst_mcp_server.human_efficiency import HumanEfficiencyAnalyzer
from typing import List, Optional, Dict, Any
import mcp.server.fastmcp.prompts.base as mcp_prompts
from pydantic import Field
from mcp.server.fastmcp import FastMCP

from flask import json

from bst_mcp_server.project_issue_cache import ProjectIssueCache


# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_pm_info_mcp_server.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


jira_config_root = "jira"
jira_timesheet_leave_endpoint = "jira-timesheet-leave"
jira_timesheet_worklog_endpoint = "jira-timesheet-worklog"
jira_timesheet_calworkday_endpoint = "jira-timesheet-calworkday"

server_config = load_config().get("server_config", {})
bst_pm_info_mcp_server_config = server_config.get("bst_pm_info_mcp_server", {})


# --- MCP Server Initialization ---
bst_pm_info_mcp_server = FastMCP(
    "bst_pm_info_mcp_server",
    description="提供业务系统的原始信息查询，不做深度加工，目的是提供给LLM,便于进行2次编排",
    dependencies=["sqlite3"],
    host=bst_pm_info_mcp_server_config.get("host", "0.0.0.0"),
    port=bst_pm_info_mcp_server_config.get("port", 8001),
)


@bst_pm_info_mcp_server.tool()
async def find_project_critical_path_tool(
    project_key: str = Field(description="项目的唯一标识符，通常为用户提及的项目编号"),
) -> Optional[Dict[str, Any]]:
    """
    【工具名称】find_project_critical_path_tool
    【功能描述】
    根据用户输入的项目key（project_key），查询并返回：
    1. 项目的关键路径任务列表（即决定项目总工期的关键任务）；
    ⚠️ 本工具不涉及对任务执行人的绩效评估，仅用于识别关键任务与负责人。
    【返回值结构说明】
    返回一个字典，包含以下部分：
    1. 项目{project_key}关键路径任务列表 (list of dict)
       - 仅包含构成项目关键路径的任务。
       - 每个任务都包含 'assignee' 字段，标识负责人。
       - 建议以表格形式展示，使用中文表头。

    【字段说明（关键任务/任务通用）】
    - key (str): Jira 任务编号，如 WORK-53
    - issueId (str): 任务内部 ID
    - summary (str): 任务标题
    - reporter (str): 创建人
    - task_owner (str):  负责人
    - assignee (str): 执行人（可能为空）
    - priority (str): 优先级（如 P0, P1）
    - status (str): 当前状态（如 "待办", "进行中", "已完成"）
    - isSubtask (bool): 是否为子任务
    - parent (str): 父任务编号（如果是子任务）
    - predecessors (list): 前置任务编号列表
    - prelinks (dict): 前置依赖关系分类：
        - "has to be done after": 必须在其之后执行的任务
        - "is blocked by": 被哪些任务阻塞
        - "is child of": 属于哪个父任务
    - keytask (str): 是否为关键任务（"true" / "false"）
    - aggregatetimeoriginalestimate (int): 预估工时（单位：秒）
    - plan_start (str): 计划开始日期（YYYY-MM-DD，可选）
    - plan_end (str): 计划结束日期（YYYY-MM-DD，可选）

    【示例输入】
    用户输入："请帮我查一下项目 WORK 的关键路径和关键任务负责人"
    解析后参数：
    project_key = "WORK"
    【示例返回】
    {
      "项目WORK关键路径任务列表": [
        {
          "key": "WORK-41",
          "issueId": "43774",
          "summary": "收集用户需求(Subtask)",
          "reporter": "hong.zhang@bst.ai",
          "task_owner": "zishu.lv@bst.ai",
          "assignee": "zishu.lv@bst.ai",
          "priority": "P0",
          "aggregatetimeoriginalestimate": 144000,
          "isSubtask": true,
          "parent": "WORK-40",
          "status": "待办",
          "predecessors": [],
          "prelinks": {
            "has to be done after": [],
            "is blocked by": [],
            "is child of": []
          },
          "keytask": "true"
        },
        ...
      ]
    }
    """
    logger.info(f"查找项目关键路径: project_key={project_key}")
    try:
        result = CriticalTaskProject.find_critical_path(project_key)
        logger.info(f"项目 {project_key} 关键路径查找完成")
        logger.debug(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except Exception as e:
        logger.error(f"查找项目 {project_key} 关键路径时发生错误: {e}", exc_info=True)
        return {"error": str(e)}


@bst_pm_info_mcp_server.tool()
async def get_project_info(
    project_key: str = Field(description="项目的唯一标识符，通常为用户提及的项目编号"),
) -> Optional[Dict[str, Any]]:
    """
    【工具名称】get_project_info
    【功能描述】
    根据用户输入的项目key（project_key），查询并返回：
    1. 项目的完整任务列表；
    ⚠️ 本工具不涉及对任务执行人的绩效评估，仅用于返回项目的任务列表。
    【返回值结构说明】
    返回一个字典，包含以下部分：
    1. 项目{project_key}任务列表 (list of dict)
       - 包含该项目所有任务的详细信息。
       - 建议以表格形式展示，使用中文表头。

    【字段说明（关键任务/任务通用）】
    - key (str): Jira 任务编号，如 WORK-53
    - issueId (str): 任务内部 ID
    - summary (str): 任务标题
    - reporter (str): 创建人
    - task_owner (str):  负责人
    - assignee (str): 执行人（可能为空）
    - priority (str): 优先级（如 P0, P1）
    - status (str): 当前状态（如 "待办", "进行中", "已完成"）
    - isSubtask (bool): 是否为子任务
    - parent (str): 父任务编号（如果是子任务）
    - predecessors (list): 前置任务编号列表
    - prelinks (dict): 前置依赖关系分类：
        - "has to be done after": 必须在其之后执行的任务
        - "is blocked by": 被哪些任务阻塞
        - "is child of": 属于哪个父任务
    - keytask (str): 是否为关键任务（"true" / "false"）
    - aggregatetimeoriginalestimate (int): 预估工时（单位：秒）
    - plan_start (str): 计划开始日期（YYYY-MM-DD，可选）
    - plan_end (str): 计划结束日期（YYYY-MM-DD，可选）

    【示例输入】
    用户输入："请帮我查一下项目 WORK 的关键路径和关键任务负责人"
    解析后参数：
    project_key = "WORK"
    【示例返回】
    {
      "项目WORK任务列表": [
        {
          "key": "WORK-53",
          "issueId": "43786",
          "summary": "前后端联调(Subtask)",
          "reporter": "hong.zhang@bst.ai",
          "task_owner": "zishu.lv@bst.ai",
          "priority": "P0",
          "aggregatetimeoriginalestimate": 144000,
          "isSubtask": true,
          "parent": "WORK-46",
          "status": "待办",
          "assignee": "zishu.lv@bst.ai",
          "predecessors": ["WORK-47", "WORK-48"],
          "prelinks": {
            "has to be done after": ["WORK-47", "WORK-48"],
            "is blocked by": [],
            "is child of": []
          },
          "keytask": "true"
        },
        ...
      ],
    }
    """
    logger.info(f"查询项目任务列表: project_key={project_key}")
    try:
        tasks = ProjectIssueCache.get_project_issues(project_key)
        logger.info(f"获取到 {len(tasks)} 个任务")
        logger.info(json.dumps(tasks, ensure_ascii=False, indent=2))
        return {
            f"项目{project_key}任务列表": tasks,
        }

    except Exception as e:
        logger.error(f"查找项目 {project_key} 任务列表发生错误: {e}", exc_info=True)
        return {"error": str(e)}


# @bst_pm_info_mcp_server.tool()
# async def jira_timesheet_leave_tool(
#     userName: str = Field(
#         description="员工邮箱，必须以 @bst.ai 结尾，支持多个邮箱，逗号分隔"
#     ),
#     startDate: str = Field(
#         description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
#     ),
#     endDate: str = Field(
#         description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
#     ),
# ) -> Optional[List[Dict[str, Any]]]:
#     """
#     【工具名称】jira_timesheet_leave_tool
#     【功能描述】根据用户输入，查询指定员工在指定时间范围内的请假记录。
#     【返回值结构说明】
#     :return: 返回值是一个包含请假记录的列表，格式为 List[Dict], 每条记录包含以下字段：
#     - id (int): 请假记录的唯一标识符
#     - user (dict): 员工信息，包括：
#         - userKey (str): Jira 用户唯一标识
#         - avatar (str): 头像链接
#         - userName (str): 用户名（邮箱格式）
#         - displayName (str): 显示名（中文名）
#         - emailAddress (str): 邮箱地址
#         - isActive (bool): 是否为活跃用户
#         - isDel (bool): 是否已删除
#     - typeId (int): 请假类型 ID
#     - typeName (str): 请假类型名称（如 "休假"）
#     - isPaid (int): 是否带薪（0 表示带薪）
#     - leaveTime (str): 请假日期（格式：YYYY-MM-DD）
#     - leaveSeconds (int): 请假时长（单位：秒）
#     - dailyLeaveTime (str): 请假时长的可读格式（如 "3h", "1d"）
#     【示例返回】
#     [
#       {
#         "id": 212,
#         "user": {
#           "userKey": "JIRAUSER11849",
#           "avatar": "https://jira.bstai.top/secure/useravatar?size=xsmall&avatarId=10349",
#           "userName": "zishu.lv@bst.ai",
#           "displayName": "吕自书",
#           "emailAddress": "zishu.lv@bst.ai",
#           "isActive": true,
#           "isDel": false
#         },
#         "typeId": 1,
#         "typeName": "休假",
#         "isPaid": 0,
#         "leaveTime": "2025-04-22",
#         "leaveSeconds": 10800,
#         "dailyLeaveTime": "3h"
#       }
#     ]
#     """
#     logger.info(
#         f"查询请假记录: userName={userName}, startDate={startDate}, endDate={endDate}"
#     )
#     try:
#         result = await HumanEfficiencyAnalyzer.get_instance().fetch_assignee_leave_data(
#             assignee=userName,
#             start_date=startDate,
#             end_date=endDate,
#         )
#         logger.info(
#             f"请假记录查询完成: userName={userName}, 记录数={len(result) if result else 0}"
#         )
#         logger.info(json.dumps(result, ensure_ascii=False, indent=2))
#         return result
#     except Exception as e:
#         logger.error(f"查询请假记录时发生错误: {e}", exc_info=True)
#         return {"error": str(e)}


# @bst_pm_info_mcp_server.tool()
# async def jira_timesheet_calworkday_tool(
#     startDate: str, endDate: str
# ) -> Optional[Dict[str, Any]]:
#     """
#     MCP 工具函数：根据给定日期范围计算工作日与非工作日列表。
#     请根据用户的请求，提取出以下结构化信息
#       - startDate: 开始时间（格式为 YYYY-MM-DD)
#       - endDate:   结束时间（格式为 YYYY-MM-DD)
#     最终构造出来的参数格式：
#     params= {"startDate": "2025-04-01", "endDate": "2025-11-30"}
#     :param params: 请求参数
#     :return: 获取一段日期内的工作日、非工作日列表
#     """
#     params = {
#         "startDate": startDate,
#         "endDate": endDate,
#     }
#     return await asyncio.get_event_loop().run_in_executor(
#         None,
#         lambda: call_restful_api(
#             "jira-timesheet", jira_timesheet_calworkday_endpoint, request_params=params
#         ),
#     )


from typing import Dict, List, Any, Optional


@bst_pm_info_mcp_server.tool()
async def jira_timesheet_worklog_tool(
    userName: str = Field(
        description="员工邮箱，必须以 @bst.ai 结尾，支持多个邮箱，逗号分隔"
    ),
    startDate: str = Field(
        description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
    endDate: str = Field(
        description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
    ),
) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """
    【工具名称】jira_timesheet_worklog_tool
    【功能描述】根据用户输入，查询指定员工在指定时间范围内的 Jira 工作日志记录，按用户邮箱分组返回。

    【返回值结构说明】
    :return: 返回按用户分组的工作日志数据，格式为 Dict[str, List[Dict]]
             key: 用户邮箱（如 zishu.lv@bst.ai）
             value: 该用户在此时间段内的所有工作日志列表，每条记录包含以下字段:
    - timeWorkedStr (str): 实际工作时间（可读格式，如 "1d", "3h"）
    - overTimeStr (str): 加班时间（可读格式，如 "0h"）
    - issueId (int): Jira 问题 ID
    - author (dict): 工作日志作者信息，包括：
        - userKey (str): Jira 用户唯一标识
        - avatar (str): 头像链接
        - userName (str): 用户名（邮箱格式）
        - displayName (str): 显示名（中文名）
        - emailAddress (str): 邮箱地址
        - isActive (bool): 是否为活跃用户
        - isDel (bool): 是否已删除
    - timeWorked (int): 实际工作时间（单位：秒）
    - overTime (int or None): 加班时间（单位：秒，可能为空）
    - memo (str): 工作内容描述
    - projectKey (str): 所属项目编号（如 "NBO2501"）
    - createTime (str): 日志创建时间（格式：YYYY-MM-DD HH:mm:ss）
    - auditTime (str): 审核时间（可能为空）
    - approve (dict): 审核人信息，结构同 author
    - workLogTypeName (str): 工作日志类型名称（如 "开发工作"）
    - workLogType (str): 工作日志类型编码（如 "10002"）
    - create (dict): 创建人信息，结构同 author
    - id (int): 工作日志唯一标识
    - projectId (int): 项目 ID
    - unitSample (str): 工作时间单位示例（如 "2d 2h 20m"）
    - startDate (str): 工作日志对应的日期（格式：YYYY-MM-DD）
    - status (int): 日志状态（如 1 表示已提交）
    - isAppendLog (bool): 是否为补录日志

    【示例返回】
    {
      "zishu.lv@bst.ai": [
        {
          "timeWorkedStr": "1d",
          "overTimeStr": "0h",
          "issueId": 81745,
          "author": {
            "userKey": "JIRAUSER11849",
            "avatar": "https://jira.bstai.top/secure/useravatar?size=xsmall&avatarId=10349",
            "userName": "zishu.lv@bst.ai",
            "displayName": "吕自书",
            "emailAddress": "zishu.lv@bst.ai",
            "isActive": true,
            "isDel": false
          },
          "timeWorked": 28800,
          "overTime": null,
          "memo": "对齐并开发新增事件。",
          "projectKey": "NBO2501",
          "createTime": "2025-04-14 10:23:20.0",
          "auditTime": "",
          "approve": {
            "userKey": "JIRAUSER11854",
            "avatar": "https://jira.bstai.top/secure/useravatar?size=xsmall&avatarId=10341",
            "userName": "kris.yang@bst.ai",
            "displayName": "杨洋",
            "emailAddress": "kris.yang@bst.ai",
            "isActive": true,
            "isDel": false
          },
          "workLogTypeName": "开发工作",
          "workLogType": "10002",
          "create": {
            "userKey": "JIRAUSER11849",
            "avatar": "https://jira.bstai.top/secure/useravatar?size=xsmall&avatarId=10349",
            "userName": "zishu.lv@bst.ai",
            "displayName": "吕自书",
            "emailAddress": "zishu.lv@bst.ai",
            "isActive": true,
            "isDel": false
          },
          "id": 18804,
          "projectId": 11116,
          "unitSample": "2d 2h 20m",
          "startDate": "2025-04-07",
          "status": 1,
          "isAppendLog": false
        }
      ],
      "fugui.li@bst.ai": []
    }
    """
    logger.info(
        f"查询工作日志: userName={userName}, startDate={startDate}, endDate={endDate}"
    )
    try:
        # 调用已修改的 fetch_assignee_work_logs，返回 Dict[str, List[Dict]]
        result_map: Dict[
            str, List[Dict[str, Any]]
        ] = await HumanEfficiencyAnalyzer.get_instance().fetch_assignee_work_logs(
            assignee=userName,
            start_date=startDate,
            end_date=endDate,
        )

        logger.info(
            f"工作日志查询完成: userName={userName}, 涉及用户数={len(result_map)}, "
            f"总记录数={sum(len(logs) for logs in result_map.values())}"
        )

        # 可选：打印部分数据用于调试
        if result_map:
            logger.debug(json.dumps(result_map, ensure_ascii=False, indent=2))

        return result_map

    except Exception as e:
        logger.error(f"查询工作日志时发生错误: {e}", exc_info=True)
        # ✅ 错误时也返回字典结构，保持接口一致性
        assignee_list = [
            email.strip() for email in userName.split(",") if email.strip()
        ]
        return {email: [] for email in assignee_list}


# @bst_pm_info_mcp_server.tool()
# async def get_user_info_tool(username: str) -> Optional[Dict[str, Any]]:
#     """
#     【工具名称】get_user_info_tool

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


# @bst_pm_info_mcp_server.tool()
# async def get_attendance_records(
#     userName: str = Field(
#         description="员工邮箱，必须以 @bst.ai 结尾，支持多个邮箱，逗号分隔"
#     ),
#     startDate: str = Field(
#         description="查询的起始日期（格式：YYYY-MM-DD），支持中文时间表达"
#     ),
#     endDate: str = Field(
#         description="查询的结束日期（格式：YYYY-MM-DD），支持中文时间表达"
#     ),
# ) -> Optional[Dict[str, Any]]:
#     """
#     【工具名称】get_attendance_records
#     【功能描述】根据用户输入，查询指定员工在指定时间范围内的考勤记录。
#     【返回值结构说明】
#     返回值是一个字典，键为日期（格式：YYYY-MM-DD），值为当天的考勤记录列表。
#     每条记录包含以下字段：
#     - signfrom (str): 打卡来源（如 "外部考勤数据同步"）
#     - signTime (str): 打卡时间（格式：HH:mm:ss）
#     - signStatus (str): 打卡状态（如 "正常", "迟到", "早退"）
#     - addr (str): 打卡地点（如 "武汉32楼电梯左"）
#     - workTime (str): 应打卡时间（格式：HH:mm）

#     【示例返回】
#     {
#       "2025-04-01": [
#         {
#           "signfrom": "外部考勤数据同步",
#           "signTime": "09:06:24",
#           "signStatus": "正常",
#           "addr": "武汉32楼电梯左",
#           "workTime": "09:00"
#         },
#         {
#           "signfrom": "外部考勤数据同步",
#           "signTime": "18:20:22",
#           "signStatus": "正常",
#           "addr": "武汉32楼电梯左",
#           "workTime": "18:00"
#         }
#       ]
#     }

#     :param params: 请求参数字典，包含 userName, startDate, endDate 等信息
#     :return: 返回结构化考勤记录，格式为 Dict[str, List[Dict]]
#     """

#     result = await BstOA.get_instance().get_kq_data(
#         startDate=startDate,
#         endDate=endDate,
#         assignee=userName,
#     )

#     logger.info(json.dumps(result, ensure_ascii=False, indent=2))
#     return result


@bst_pm_info_mcp_server.prompt()
async def bst_pm_mcp_prompt() -> list[mcp_prompts.Message]:
    """
    创建一个提示词用来按照用户的提问做项目管理工作
    Returns:
        为LLM返回提示词.
    """
    logger.info("生成MCP提示词")
    return [
        mcp_prompts.UserMessage(
            "你好,我是BST项目管理智能机器人,我能告诉你跟项目相关的资料，包括: \n"
            "1.帮你迅速找到项目的关键任务和关键路径 \n"
            "2.查找项目的任务列表 \n"
            "3.查找项目对应人员的工时填报记录 \n"
            "4.查找项目对应人员的请假记录 \n"
            "5.查找项目对应人员的考勤情况 \n"
            "6.根据上述信息统计项目中任务执行人的工作饱和度 \n"
        ),
        mcp_prompts.AssistantMessage(
            "你是BST项目管理智能机器人,我能告诉你跟项目相关的资料，包括: \n"
            "1.帮你迅速找到项目的关键任务和关键路径 \n"
            "2.查找项目的任务列表 \n"
            "3.查找项目对应人员的工时填报记录 \n"
            "4.查找项目对应人员的请假记录 \n"
            "5.查找项目对应人员的考勤情况 \n"
            "6.根据上述信息统计项目中任务执行人的工作饱和度 \n"
        ),
    ]


@bst_pm_info_mcp_server.resource("resource://task_field_description")
async def task_fields_description() -> str:
    """
    项目会拆分成很多个任务，任务由多个字段组成，本资源中是一个json字典
    该字典每个部分的key对应任务json信息中的key, display对应这个key的中文说明，比如assignee字段对应的中文注释说明就是任务执行人
    """
    logger.info("加载任务字段描述")
    try:
        field_mapping = load_field_mapping()
        logger.info("任务字段描述加载完成")
        return field_mapping
    except Exception as e:
        logger.error(f"加载任务字段描述时发生错误: {e}", exc_info=True)
        return "{}"


@bst_pm_info_mcp_server.resource("resource://workload_saturation_rules_description")
async def workload_saturation_rules_description() -> str:
    """
    工作负荷指标计算的相关参数配置信息及参数配置项对应中文说明
    请阅读metrics_description,workload_rules_description,weight_ratio_description,这三个以'_description'结尾的配置项及下属子项，
    他们子项目提供的中文描述分别对应metrics，workload_rules，weight_ratio各个field属性的中文说明或注释;
    metrics，workload_rules，weight_ratio,涉及的配置参数对于理解各项负荷指标（实际工作饱和度，加权工作饱和度，可用工时等）提供计算依据，
    甚至你可以基于这些metrics,rules及ratio，进一步扩展让关于工作负荷指标的分析更合理和科学
    """
    logger.info("加载工作负荷饱和度规则描述")
    try:
        saturation_config = load_config().get("saturation", {})
        logger.info("工作负荷饱和度规则描述加载完成")
        return saturation_config
    except Exception as e:
        logger.error(f"加载工作负荷饱和度规则描述时发生错误: {e}", exc_info=True)
        return "{}"


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
    loop = asyncio.new_event_loop()
    try:
        # result = loop.run_until_complete(
        #     analyzer.calculate_base_saturation("WORK", start_date, end_date)
        # )
        result = loop.run_until_complete(
            jira_timesheet_calworkday_tool("2025-01-01", "2025-04-01")
        )
        logger.info("获取结果:", result)
    except Exception as e:
        logger.error(f"执行过程中发生错误: {e}", exc_info=True)
    finally:
        loop.close()
