import logging
import os

from mcp.server.fastmcp import FastMCP

from bst_mcp_server.config_util import load_config
from bst_mcp_server.human_efficiency import HumanEfficiencyAnalyzer

from mcp.server.fastmcp import FastMCP


# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_pm_workload_mcp_server.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

server_config = load_config().get("server_config", {})
bst_pm_workload_mcp_server_config = server_config.get("bst_pm_workload_mcp_server", {})
# --- MCP Server Initialization ---
bst_pm_workload_mcp_server = FastMCP(
    "bst_pm_workload_mcp_server",
    description="MCP Server for 提供做过业务编排过的工具，提供一步到位的标准化工具，如工作饱和度计算",
    dependencies=["sqlite3"],
    host=bst_pm_workload_mcp_server_config.get("host", "0.0.0.0"),
    port=bst_pm_workload_mcp_server_config.get("port", 8002),
)


# 【工具功能说明】：
# 1. 内部集成并覆盖了 `find_critical_path_tool` 的逻辑，可自动识别项目中的关键路径及对应的关键任务执行人；
# 2. 对每位关键任务执行人，在指定时间段 [startDate, endDate] 内，提取其工时填报记录、请假信息、考勤数据等统计信息；
# 3. 基于 resource://workload_saturation_rules_description 中定义的工作负荷计算规则（Workload Rules），对上述指标进行加工处理，
#    计算出各项具体的工作负荷（Workload Metrics）；
# 4. 最终通过 weight_ratio 加权方式，综合得出每位执行人的加权工作饱和度（Weighted Saturation）；
@bst_pm_workload_mcp_server.tool()
async def calculate_saturation_project(project, startDate, endDate: str):
    """
    MCP 工具函数：从项目维度出发，基于用户提供的项目标识符（project）、统计起始时间（startDate）与结束时间（endDate），
    统计该项目中所有关键任务执行人的基础工作饱和度（Base Saturation）与加权工作饱和度（Weighted Saturation），
    以及围绕这些任务所衍生的各项指标与工作负荷分析结果。

    【参数要求】：
    - project (str): 用户请求中提及的项目名称或唯一标识符（Project Key）；
    - startDate (str): 统计周期的起始日期，格式必须为 'YYYY-MM-DD'；
    - endDate (str): 统计周期的结束日期，格式必须为 'YYYY-MM-DD'；

    【返回值说明】：
    返回一个字典对象，包含如下结构化内容：
        - "统计开始时间": 字符串格式的统计起始日期；
        - "统计结束时间": 字符串格式的统计结束日期；
        - "{project}": 以项目名作为键，其值为该项目的详细工作饱和度分析结果，包括但不限于：
            - 关键任务执行人列表及其基本信息；
            - 每位执行人的基础工作饱和度；
            - 每位执行人的加权工作饱和度；
            - 各项原始指标（如总工时、实际出勤天数、请假天数等）；
            - 根据 workload rules 推导出的具体工作负荷指标。

    【使用建议】：
    调用前请确保理解 resource://workload_saturation_rules_description 中的规则描述，以便正确解读输出数据。
    """
    logger.info(
        f"计算项目工作饱和度: project={project}, startDate={startDate}, endDate={endDate}"
    )
    try:
        analyzer = HumanEfficiencyAnalyzer.get_instance()
        # 执行分析
        saturation_results = {}
        saturation_results["统计开始时间"] = startDate
        saturation_results["统计结束时间"] = endDate
        saturation_results[project] = await analyzer.calculate_base_saturation(
            project, startDate, endDate
        )
        logger.info(f"项目 {project} 工作饱和度计算完成")
        return saturation_results
    except Exception as e:
        logger.error(f"计算项目 {project} 工作饱和度时发生错误: {e}", exc_info=True)
        return {"error": str(e)}


@bst_pm_workload_mcp_server.tool()
async def calculate_saturation_assignee(assignee, startDate, endDate: str):
    """
    MCP 工具函数：从人员维度出发，基于用户提供的任务执行人（assignee）、统计起始时间（startDate）与结束时间（endDate），
    统计该执行人的基础工作饱和度（Base Saturation）与加权工作饱和度（Weighted Saturation），
    以及围绕其任务所衍生的各项指标与工作负荷分析结果。
    他和calculate_saturation_project的区别是，它不去获取项目xxx的关键任务执行人，而是直接传递任务执行人作为参数去统计
    【功能说明】：
    - 获取指定时间段 [startDate, endDate] 内，该任务执行人的工时填报、请假记录、考勤数据等基础信息；
    - 基于 resource://workload_saturation_rules_description 中定义的工作负荷计算规则（Workload Rules），对上述指标进行加工处理，
      计算出各项具体的工作负荷（Workload Metrics）；
    - 最终通过 weight_ratio 加权方式，综合得出该执行人的加权工作饱和度（Weighted Saturation）；
    - 可支持多个任务执行人并行查询，各执行人邮箱需以逗号分隔，并且必须以 @bst.ai 结尾。

    【参数要求】：
    - assignee (str): 任务执行人的邮箱地址，格式如：user@bst.ai；多个用户请用英文逗号分隔，如：user1@bst.ai,user2@bst.ai；
    - startDate (str): 统计周期的起始日期，格式必须为 'YYYY-MM-DD'；
    - endDate (str): 统计周期的结束日期，格式必须为 'YYYY-MM-DD'；

    【返回值说明】：
    返回一个字典对象，包含如下结构化内容：
        - "统计开始时间": 字符串格式的统计起始日期；
        - "统计结束时间": 字符串格式的统计结束日期；
        - "{assignee}": 以执行人邮箱作为键，其值为该执行人的详细工作饱和度分析结果，包括但不限于：
            - 基础工作饱和度；
            - 加权工作饱和度；
            - 各项原始指标（如总工时、实际出勤天数、请假天数等）；
            - 根据 workload rules 推导出的具体工作负荷指标；

    【使用建议】：
    调用前请确保理解 resource://workload_saturation_rules_description 中的规则描述，以便正确解读输出数据。
    """
    logger.info(
        f"计算执行人工作饱和度: assignee={assignee}, startDate={startDate}, endDate={endDate}"
    )
    try:
        analyzer = HumanEfficiencyAnalyzer.get_instance()
        # 执行分析
        saturation_results = {}
        saturation_results["统计开始时间"] = startDate
        saturation_results["统计结束时间"] = endDate
        saturation_results[assignee] = (
            await analyzer.calculate_base_saturation_assignee(
                assignee, startDate, endDate
            )
        )
        logger.info(f"执行人 {assignee} 工作饱和度计算完成")
        return saturation_results
    except Exception as e:
        logger.error(f"计算执行人 {assignee} 工作饱和度时发生错误: {e}", exc_info=True)
        return {"error": str(e)}
