# src/critical_path_analyzer/calworkday_cache.py

import logging
import os
from typing import Dict, List, Optional


from bst_mcp_server.config_util import load_field_mapping
from bst_mcp_server.data_processor import extract_task_info
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
        logging.FileHandler(os.path.join(log_dir, "project_issue_cache.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ProjectIssueCache:
    @classmethod
    def get_project_issues(cls, project_key: str) -> List:
        """获取当前缓存的数据"""
        logger.info(f"获取项目 {project_key} 的任务列表")
        issues = cls.build_cache(project_key)
        return issues

    @classmethod
    def get_project_issues_by_jql(cls, project_key: str, jql: str, type: str) -> List:
        """获取当前缓存的数据"""
        logger.info(f"获取项目 {project_key} 的任务列表")
        issues = cls.build_cache_by_jql(project_key, jql, type)
        return issues

    @classmethod
    def get_project_issue(cls, project_key: str, issue_id: str):
        """获取当前缓存的数据"""
        logger.info(f"获取项目 {project_key} 中的任务 {issue_id}")
        issues = cls.build_cache(project_key)
        for issue in issues:
            if issue["id"] == issue_id:
                logger.info(f"找到任务 {issue_id}")
                return issue
        logger.warning(f"未找到任务 {issue_id}")
        return None

    @classmethod
    def build_cache(cls, project_key: str) -> List:
        logger.info(f"开始构建项目 {project_key} 的任务缓存")
        jql = f"project = '{project_key}'"
        logger.debug(f"查询JQL: {jql}")
        cache_prefix = "jira_project_tasks"
        return ProjectIssueCache.build_cache_by_jql(project_key, jql, cache_prefix)

    @classmethod
    def build_cache_by_jql(
        cls,
        project_key: str,
        jql: Optional[str] = None,
        cache_prefix: Optional[str] = None,
    ) -> List:
        logger.info(f"开始构建项目 {project_key} 的任务缓存")
        try:
            project_name = f"{project_key}项目"

            logger.debug(f"查询JQL: {jql}")

            tasks = RedisUtils.get_instance().get_data(f"{cache_prefix}:{project_key}")

            if tasks is None:
                logger.info(
                    f"Redis中未找到项目 {project_key} 的任务数据，从Jira API获取"
                )
                params = {
                    "expand": ["names"],
                    "jql": jql,
                    "maxResults": 1000,
                    "startAt": 0,
                }
                raw_data = call_restful_api(
                    "jira", api_endpoint="jira_project_tasks", request_params=params
                )
                if raw_data:
                    logger.debug("获取到原始数据，开始处理")
                    field_mapping = load_field_mapping()
                    tasks = extract_task_info(raw_data, field_mapping)
                    key = f"{cache_prefix}:{project_key}"
                    RedisUtils.get_instance().set_data(key=key, data=tasks)
                    logger.info(f"已将项目 {project_key} 的任务数据存入Redis")
                else:
                    logger.warning(f"从Jira API获取项目 {project_key} 的任务数据失败")
                    tasks = []
            else:
                logger.info(f"从Redis中获取到项目 {project_key} 的任务数据")
            return tasks
        except Exception as e:
            logger.error(f"构建jira项目任务缓存失败: {e}", exc_info=True)

    @classmethod
    def clear_cache(cls) -> None:
        """清除缓存"""
        logger.info("清除所有项目任务缓存")

    @classmethod
    def clear_cache_by_project(cls, project_key: str) -> None:
        """清除指定项目的缓存"""
        logger.info(f"清除项目 {project_key} 的任务缓存")
