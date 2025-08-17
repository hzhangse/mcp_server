import json
import logging
import os
from typing import List, Dict, Any

from bst_mcp_server.aoe_graph import find_critical_path
from bst_mcp_server.config_util import load_config
from bst_mcp_server.project_issue_cache import ProjectIssueCache

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "critical_task_project.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class CriticalTaskProject:

    @staticmethod
    def find_critical_path(project_key: str) -> Dict[str, Any]:
        """
        根据项目优先级策略查找关键任务
        :param project_key: 项目key
        :return: 关键任务信息
        """
        config = load_config()
        project_results = {}
        aoe_projects = config.get("critical_task_config", {}).get("aoe", [])

        # 判断当前项目是否在aoe列表中
        is_aoe_project = any(
            (
                project.get("projectKey") == project_key
                if isinstance(project, dict)
                else project == project_key
            )
            for project in aoe_projects
        )

        if is_aoe_project:
            project_results = find_critical_path(project_key)

        else:
            # 如果不在aoe列表中，检查是否使用project策略
            default_rule = (
                config.get("critical_task_config", {})
                .get("rule", {})
                .get("default", "")
            )
            if default_rule == "project":
                project_results = CriticalTaskProject.find_critical_path_by_priority(
                    project_key
                )

        return project_results

    @staticmethod
    def find_critical_path_by_priority(project_key: str) -> Dict[str, Any]:
        """
        根据项目优先级策略查找关键任务
        :param project_key: 项目key
        :return: 关键任务信息
        """
        logger.info(f"[DEBUG] find_critical_path called with: {project_key}")
        try:
            # 获取默认优先级配置
            config = load_config()
            priority = (
                config.get("critical_task_config", {})
                .get("project", {})
                .get("priority", "P0")
            )
            config_issue_types = (
                config.get("critical_task_config", {})
                .get("project", {})
                .get("issuetype", [])
            )
            # 获取项目任务
            # tasks = ProjectIssueCache.get_project_issues(project_key)
            # logger.info(f"获取到 {len(tasks)} 个任务")

            # 根据优先级筛选关键任务
            critical_tasks = []
            jql = f"project = '{project_key}' and priority = '{priority}' and issuetype in ({','.join(config_issue_types)})"
            logger.debug(f"查询JQL: {jql}")
            type = "jira_project_critical_tasks"
            critical_tasks = ProjectIssueCache.get_project_issues_by_jql(
                project_key, jql, type
            )

            logger.info(f"项目 {project_key} 的关键任务数量: {len(critical_tasks)}")
            logger.info(json.dumps(critical_tasks, ensure_ascii=False, indent=2))
            return {
                # f"项目{project_key}任务列表": tasks,
                f"项目{project_key}关键路径任务列表": critical_tasks,
            }

        except Exception as e:
            logger.error(f"查找关键任务失败: {e}")
            return {}


if __name__ == "__main__":
    CriticalTaskProject.find_critical_path("ISPCV20S")
