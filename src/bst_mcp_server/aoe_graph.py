from collections import defaultdict, deque
from datetime import datetime, timedelta
import logging
import os
from typing import Any, Dict, List

from graphviz import Digraph
from bst_mcp_server.holiday_util import HolidayUtil
from bst_mcp_server.project_issue_cache import ProjectIssueCache


# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "aoe_graph.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def remove_suffix(s: str, suffix: str) -> str:
    if s.endswith(suffix):
        return s[: -len(suffix)]
    return s


class AOEGraph:
    def __init__(self, key=None, name=None):
        self.key = key  # 图的唯一标识（如项目Key）
        self.name = name  # 图的显示名称（如项目名称）
        # 存储节点信息
        self.nodes = {}  # 节点ID -> 节点名称
        # 存储图结构
        self.adj = defaultdict(list)  # 邻接表：节点ID -> [(后继节点ID, 任务持续时间)]
        self.in_degree = defaultdict(int)  # 入度：节点ID -> 入度值
        # 存储计算结果
        self.ve = {}  # 事件最早发生时间
        self.vl = {}  # 事件最晚发生时间
        self.critical_path = []  # 关键路径
        logger.info(f"AOEGraph实例初始化: key={key}, name={name}")

    def add_node(self, node_id, node_name):
        """添加节点"""
        self.nodes[node_id] = node_name
        if node_id not in self.in_degree:
            self.in_degree[node_id] = 0
        logger.debug(f"添加节点: {node_id} -> {node_name}")

    def add_edge(self, start_node, end_node, duration):
        """添加任务边，如果边已存在，则更新其 duration"""
        found = False
        # 遍历当前 start_node 的所有出边
        for i, (target, _) in enumerate(self.adj[start_node]):
            if target == end_node:
                # 边已存在，更新 duration
                self.adj[start_node][i] = (end_node, duration)
                found = True
                logger.debug(f"更新边: {start_node} -> {end_node}, duration={duration}")
                break

        if not found:
            # 边不存在，按原逻辑添加
            self.adj[start_node].append((end_node, duration))
            self.in_degree[end_node] += 1  # 只有新增时才更新入度
            logger.debug(f"添加边: {start_node} -> {end_node}, duration={duration}")

    def topological_sort(self):
        """拓扑排序，计算事件最早发生时间ve"""
        logger.info("开始拓扑排序")
        # 创建入度副本，避免修改原始数据
        in_degree_copy = self.in_degree.copy()
        queue = deque([node for node in self.nodes if in_degree_copy[node] == 0])
        topo_order = []

        # 初始化最早发生时间为0
        for node in self.nodes:
            self.ve[node] = 0

        while queue:
            u = queue.popleft()
            topo_order.append(u)
            logger.debug(f"处理节点: {u}")

            for v, w in self.adj[u]:
                # 更新ve[v] = max(ve[v], ve[u] + w)
                self.ve[v] = max(self.ve[v], self.ve[u] + w)
                in_degree_copy[v] -= 1
                if in_degree_copy[v] == 0:
                    queue.append(v)

        logger.info(f"拓扑排序完成，共处理 {len(topo_order)} 个节点")
        return topo_order

    def calculate_critical_path(self):
        """计算关键路径"""
        logger.info("开始计算关键路径")
        # 步骤1：拓扑排序，计算ve
        topo_order = self.topological_sort()
        if len(topo_order) != len(self.nodes):
            # raise ValueError("图中存在环，无法计算关键路径")
            logger.error("图中存在环，无法计算关键路径")
            return None

        # 步骤2：计算事件最晚发生时间vl，初始化为项目总工期
        max_time = max(self.ve.values())
        for node in self.nodes:
            self.vl[node] = max_time

        # 逆拓扑排序计算vl
        for u in reversed(topo_order):
            for v, w in self.adj[u]:
                # 更新vl[u] = min(vl[u], vl[v] - w)
                self.vl[u] = min(self.vl[u], self.vl[v] - w)

        # 步骤3：计算关键路径
        critical_edges = []
        for u in self.nodes:
            for v, w in self.adj[u]:
                # 计算活动最早开始时间e和最晚开始时间l
                e = self.ve[u]
                l = self.vl[v] - w
                # 如果e == l，则为关键活动
                if e == l:
                    critical_edges.append((u, v, w))

        self.critical_path = critical_edges
        logger.info(
            f"关键路径计算完成，共找到 {len(critical_edges)} 条关键边，总工期: {max_time}"
        )
        return critical_edges, max_time

    def find_all_critical_paths(self):
        """找出所有关键路径（处理存在多条关键路径的情况）"""
        logger.info("查找所有关键路径")
        if not self.critical_path:
            self.calculate_critical_path()

        # 构建关键路径图
        critical_graph = defaultdict(list)
        for u, v, w in self.critical_path:
            critical_graph[u].append(v)

        # 找出所有入度为0的起点和出度为0的终点
        start_nodes = [node for node in self.nodes if self.in_degree[node] == 0]
        end_nodes = [node for node in self.nodes if not self.adj[node]]

        all_paths = []

        # 对每个起点寻找通往终点的所有路径
        for start in start_nodes:
            stack = [(start, [start])]
            while stack:
                node, path = stack.pop()
                if node in end_nodes:
                    all_paths.append(path)
                    continue

                for next_node in critical_graph[node]:
                    if next_node not in path:  # 避免环路
                        stack.append((next_node, path + [next_node]))

        logger.info(f"找到 {len(all_paths)} 条关键路径")
        return all_paths

    def print_graph(self):
        """打印图结构"""
        logger.info("打印AOE网络图结构")
        logger.info("节点:")
        for node_id, node_name in self.nodes.items():
            logger.info(f"  {node_id}: {node_name}")

        logger.info("任务:")
        for u in self.nodes:
            for v, w in self.adj[u]:
                logger.info(f"  {u} -> {v}: 持续时间 {w}")

        logger.info("事件最早发生时间ve:")
        for node in self.nodes:
            logger.info(f"  {node}: {self.ve[node]}")

        logger.info("事件最晚发生时间vl:")
        for node in self.nodes:
            logger.info(f"  {node}: {self.vl[node]}")

    def print_critical_path(self):
        """打印关键路径"""
        logger.info("打印关键路径")
        if not self.critical_path:
            self.calculate_critical_path()

        logger.info(f"总工期: {max(self.ve.values())}")
        logger.info("关键任务:")
        for u, v, w in self.critical_path:
            logger.info(f"  {u} -> {v}: 持续时间 {w}")

        # 打印所有关键路径
        all_paths = self.find_all_critical_paths()
        logger.info("所有关键路径:")
        for i, path in enumerate(all_paths, 1):
            path_str = " -> ".join([f"{node}({self.nodes[node]})" for node in path])
            logger.info(f"  {i}. {path_str}")

    def get_critical_tasks(self) -> Dict[str, List[Any]]:
        """打印关键路径"""
        logger.info("获取关键任务")
        if not self.critical_path:
            self.calculate_critical_path()

        logger.info("关键任务:")
        critical_tasks = {}
        critical_tasks[self.key] = []

        for u, v, w in self.critical_path:
            if w > 0:
                issueKey = remove_suffix(u, "_start")
                task = self.get_task_by_key(self.tasks, issueKey)
                if task:
                    task["keytask"] = "true"
                    critical_tasks[self.key].append(task)
                    logger.info(f"{issueKey}")
        return critical_tasks

    def calculate_task_duration(self, task):
        """
        计算任务持续时间（单位：小时）

        参数：
        - task: dict 类型，包含以下字段：
            - plan_start: str, "YYYY-MM-DD"
            - actual_start: str, "YYYY-MM-DD"
            - plan_end: str, "YYYY-MM-DD"
            - actual_end: str, "YYYY-MM-DD"
            - aggregatetimeoriginalestimate: int (seconds)

        返回：
        - duration_hours: float, 任务持续时间（小时）
        """

        def parse_date(date_str):
            if date_str:
                try:
                    # 只取日期部分，忽略时间
                    return datetime.strptime(date_str.split("T")[0], "%Y-%m-%d")
                except ValueError:
                    logger.warning(f"日期解析失败: {date_str}")
                    return None
            return None

        # Step 1: 确定任务开始时间
        plan_start_dt = parse_date(task.get("plan_start"))
        actual_start_dt = parse_date(task.get("actual_start"))

        if plan_start_dt and actual_start_dt:
            task_start = max(plan_start_dt, actual_start_dt)
        elif plan_start_dt:
            task_start = plan_start_dt
        elif actual_start_dt:
            task_start = actual_start_dt
        else:
            task_start = None

        # Step 2: 确定任务结束时间
        plan_end_dt = parse_date(task.get("plan_end"))
        actual_end_dt = parse_date(task.get("actual_end"))

        if task_start:
            if plan_end_dt and actual_end_dt:
                if actual_end_dt >= task_start:
                    task_end = actual_end_dt
                else:
                    task_end = plan_end_dt
            elif plan_end_dt:
                task_end = plan_end_dt
            elif actual_end_dt:
                task_end = actual_end_dt
            else:
                task_end = None
        else:
            task_end = None

        # Step 3: 如果有完整的时间信息，计算工作日天数
        if task_start and task_end:
            day_count = 0
            current = task_start
            holiday_util = HolidayUtil()  # ✅ 使用真实 HolidayUtil 类
            while current <= task_end:
                # 判断是否为工作日且不是节假日
                if current.weekday() < 5 and not holiday_util.is_holiday(
                    current.strftime("%Y-%m-%d")
                ):
                    day_count += 1
                current += timedelta(days=1)
            duration = day_count * 8  # 每天工作8小时
            logger.debug(f"任务 {task.get('key')} 计算得到持续时间: {duration} 小时")
            return duration

        # Step 4: 如果时间不足，尝试使用 aggregatetimeoriginalestimate
        estimate_seconds = task.get("aggregatetimeoriginalestimate")
        if (
            estimate_seconds is not None
            and isinstance(estimate_seconds, int)
            and estimate_seconds > 0
        ):
            duration = estimate_seconds / 3600  # 秒转小时
            logger.debug(f"任务 {task.get('key')} 使用预估时间: {duration} 小时")
            return duration

        # 如果都没有，返回 None
        logger.warning(f"任务 {task.get('key')} 无法计算持续时间")
        return None

    def build_graph_from_tasks(self, tasks, key=None, name=None):
        """基于任务列表构建图"""
        logger.info(f"基于任务列表构建图: key={key}, name={name}")
        self.tasks = tasks
        self.add_nodes(tasks, key, name)
        self.add_edges(tasks, key, name)
        logger.info("图构建完成")

    def add_nodes(self, tasks, key=None, name=None):
        """基于任务列表构建nodes"""
        logger.info("添加节点")
        if key is None:
            logger.error("key is required")
            return
        if name is None:
            logger.error("name is required")
            return

        # Step 1: Add start node
        project_start_node_id = f"{key}_start"
        project_start_node_name = f"项目{name}开始"
        project_end_node_id = f"{key}_end"
        project_end_node_name = f"项目{name}结束"
        self.add_node(project_start_node_id, project_start_node_name)

        # Step 2: Add task nodes
        for task in tasks:
            task_key = task.get("key")
            task_name = task.get("summary")
            start_node_id = f"{task_key}_start"
            start_node_name = f"{task_name}开始"
            self.add_node(start_node_id, start_node_name)
            end_node_id = f"{task_key}_end"
            end_node_name = f"{task_name}完成"
            self.add_node(end_node_id, end_node_name)

        # Step 3: Add project end node

        self.add_node(project_end_node_id, project_end_node_name)
        logger.info(f"节点添加完成，共添加 {len(self.nodes)} 个节点")

    def add_edges(self, tasks, key=None, name=None):
        """基于任务列表构建edges"""
        logger.info("添加边")
        project_start_node_id = f"{key}_start"
        project_start_node_name = f"项目{key}开始"
        project_end_node_id = f"{key}_end"
        project_end_node_name = f"项目{key}结束"
        # Step 4: Add edges
        for task in tasks:
            task_key = task.get("key")
            if not task_key:
                logger.error(f"Task missing 'key': {task}")
                continue

            task_duration = self.calculate_task_duration(task)

            if task_duration is None:
                logger.error(f"Could not calculate duration for task {task_key}")
                continue

            end_node_id = f"{task_key}_end"
            end_node_name = f"任务{task_key}完成"
            start_node_id = f"{task_key}_start"
            start_node_name = f"任务{task_key}开始"
            # add 所有task with trually task_duration
            self.add_edge(start_node_id, end_node_id, task_duration)

            # Add start node if there are predecessors
            if task.get("predecessors"):
                # Add edges for predecessors, 补前置任务end to 当前任务的边，边长为0
                for predecessor_key in task.get("predecessors", []):
                    predecessor_end_node_id = f"{predecessor_key}_end"
                    self.add_edge(predecessor_end_node_id, start_node_id, 0)
            else:
                # 没有前置节点的task，默认和项目的start节点相连，边长为0
                if task.get("isSubtask") == False:
                    self.add_edge(project_start_node_id, start_node_id, 0)

        # 🔺 新增：收集所有出现在 predecessors 中的任务 key（即被其他任务依赖的任务）
        referenced_tasks = set()
        for task in tasks:
            task_key = task.get("key")
            predecessors = task.get("predecessors", [])
            for pred_key in predecessors:
                referenced_tasks.add(pred_key)

        for task in tasks:
            task_key = task.get("key")
            if not task_key:
                logger.error(f"Task missing 'key': {task}")
                continue

            end_node_id = f"{task_key}_end"
            start_node_id = f"{task_key}_start"
            # 删选有子任务的任务
            if task.get("subtasks"):
                subtask_keys = task.get("subtasks", [])
                task_duration = 0
                for subtask_key in subtask_keys:
                    subtask_start_node_id = f"{subtask_key}_start"
                    subtask_end_node_id = f"{subtask_key}_end"
                    subtask = self.get_task_by_key(tasks, subtask_key)
                    if subtask:
                        predecessors = subtask.get("predecessors", [])
                        # 处理task 对应子任务的形成子图的开始边
                        if predecessors.__len__() == 0:
                            self.add_edge(
                                start_node_id, subtask_start_node_id, 0
                            )  # task.start node -> subtask.start node

                        task_duration = task_duration + self.calculate_task_duration(
                            subtask
                        )

                # 处理task 对应子任务的形成子图的结束边
                for subtask_key in subtask_keys:
                    if subtask_key not in referenced_tasks:
                        subtask_end_node_id = f"{subtask_key}_end"
                        self.add_edge(
                            subtask_end_node_id, end_node_id, 0
                        )  # subtask.end node -> task.end node

                # 重建有子任务的任务task_duration,以子任务的累加为准（简单累加的目的是规避让这种任务成为关键路径），并重新添加边
                # self.add_edge(start_node_id, end_node_id, task_duration)
                self.add_edge(start_node_id, end_node_id, 0)

        # 🔺 找出未被引用的任务（即终点任务）
        end_tasks = [task for task in tasks if task.get("key") not in referenced_tasks]
        # 🔺将终点任务连接到项目结束节点
        for task in end_tasks:
            if task.get("isSubtask") == False:
                task_key = task.get("key")
                end_node_id = f"{task_key}_end"
                project_end_node_id = f"{key}_end"
                self.add_edge(end_node_id, project_end_node_id, 0)

        logger.info("边添加完成")

    def get_task_by_key(self, tasks, task_key):
        """根据任务key获取任务"""
        logger.debug(f"根据key获取任务: {task_key}")
        for task in tasks:
            if task.get("key") == task_key:
                logger.debug(f"找到任务: {task_key}")
                return task
        logger.warning(f"未找到任务: {task_key}")
        return None

    def generate_visualization_html(self, output_file="project_graph"):
        """
        使用 Graphviz 生成 SVG 格式的 AOE 图，并封装成 HTML 文件。
        支持自动适配屏幕宽度并缩小节点和边的比例。
        """
        logger.info(f"生成HTML可视化文件: {output_file}")
        dot = Digraph(format="svg")
        dot.attr(rankdir="TB")  # Top to Bottom 布局

        # 设置图的全局属性，限制宽度并调整节点/边间距
        dot.attr(
            size="8,10!",  # 宽度限制为 8 英寸（约 80vw），高度自适应
            nodesep="0.3",  # 减小节点之间水平间距
            ranksep="0.5",  # 减小层级之间垂直间距
        )

        # 获取关键路径上的所有边 (u -> v)
        critical_edges = set((u, v) for u, v, _ in self.critical_path)

        # 添加节点
        for node_id, node_name in self.nodes.items():
            is_critical_node = self.ve.get(node_id, 0) == self.vl.get(node_id, 0)
            label = (
                f"{node_name}\n({self.ve.get(node_id, '')}-{self.vl.get(node_id, '')})"
            )
            dot.node(
                node_id,
                label,
                color="red" if is_critical_node else "black",
                fontcolor="red" if is_critical_node else "black",
                fontsize="10",  # 缩小字体大小
                width="0.8",  # 缩小节点宽度
                height="0.4",  # 缩小节点高度
                margin="0.05",  # 减少内边距
                style="filled" if is_critical_node else "",
                fillcolor="lightcoral" if is_critical_node else "white",
            )

        # 添加边
        for u, edges in self.adj.items():
            for v, w in edges:
                edge_color = "red" if (u, v) in critical_edges else "black"
                dot.edge(
                    u,
                    v,
                    label=f"{w}天",
                    color=edge_color,
                    fontsize="9",  # 缩小边标签字体
                    arrowsize="0.5",  # 缩小箭头大小
                )

        # 渲染为 SVG 文件
        svg_data = dot.pipe().decode("utf-8")

        # 构建 HTML 包裹内容
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=0.7">
            <title>AOE 关键路径图 - {self.name}</title>
            <style>
                body {{
                    margin: 0;
                    padding: 10px;
                    background-color: #f9f9f9;
                    font-family: Arial, sans-serif;
                }}
                .graph-container {{
                    width: 100%;
                    max-width: 100vw;
                    overflow-x: auto;
                    border: 1px solid #ccc;
                    background: white;
                    background: white;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.1);
                }}
                svg {{
                    width: 100%;
                    height: auto;
                    transform: scale(0.6);     /* 整体缩小 20% */
                    transform-origin: top left;
                }}
                h2 {{
                    text-align: center;
                    font-size: 1.2em;
                    margin-bottom: 10px;
                }}
            </style>
        </head>
        <body>
            <h2>{self.name} - AOE 关键路径图</h2>
            <div class="graph-container">
                {svg_data}
            </div>
        </body>
        </html>
        """

        # 保存为 HTML 文件
        html_file = f"{output_file}.html"
        try:
            with open(html_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            logger.info(f"✅ 已保存为 {os.path.abspath(html_file)}")
            logger.info("👉 可以用浏览器打开查看，自动适配屏幕宽度")
        except Exception as e:
            logger.error(f"保存HTML文件失败: {e}")

        return html_file

    def generate_visualization_image(self, output_file="project_graph", format="png"):
        """
        使用 Graphviz 可视化 AOE 图，并高亮关键路径。
        输出格式支持 png、svg 等
        排版方式：从上到下（TB）
        """
        logger.info(f"生成图像可视化文件: {output_file}.{format}")
        dot = Digraph(format=format)
        dot.attr(rankdir="TB")  # 修改为 Top to Bottom 布局

        # 设置图的全局属性，限制宽度并自动换行
        dot.attr(
            size="100,200!",  # 宽度限制为 10 英寸（约屏幕宽度），高度自适应
            nodesep="0.6",  # 节点间距
            ranksep="1.2",  # 层级间距
        )

        # 获取关键路径上的所有边 (u -> v)
        critical_edges = set()
        for u, v, _ in self.critical_path:
            critical_edges.add((u, v))

        # 添加节点
        for node_id, node_name in self.nodes.items():
            is_critical_node = self.ve.get(node_id, 0) == self.vl.get(node_id, 0)
            label = (
                f"{node_name}\n({self.ve.get(node_id, '')}-{self.vl.get(node_id, '')})"
            )
            dot.node(
                node_id,
                label,
                color="red" if is_critical_node else "black",
                fontcolor="red" if is_critical_node else "black",
                style="filled" if is_critical_node else "",
                fillcolor="lightcoral" if is_critical_node else "white",
            )

        # 添加边
        for u, edges in self.adj.items():
            for v, w in edges:
                edge_color = "red" if (u, v) in critical_edges else "black"
                dot.edge(u, v, label=f"{w}天", color=edge_color)

        # 渲染图像
        try:
            dot.render(output_file, view=True)
            logger.info(f"✅ 图已保存为 {output_file}.{format}")
        except Exception as e:
            logger.error(f"保存图像文件失败: {e}")

        return f"http://localhost:8001/{output_file}.{format}"


@staticmethod
def find_critical_path(project_key: str):
    logger.info(f"[DEBUG] find_critical_path called with:  {project_key}")
    try:
        project_name = f"{project_key}项目"
        tasks = ProjectIssueCache.get_project_issues(project_key)
        logger.info(f"获取到 {len(tasks)} 个任务")
        if len(tasks) > 0:
            graph = AOEGraph(key=project_key, name=project_name)
            graph.build_graph_from_tasks(tasks, key=project_key, name=project_name)
            critical_tasks = graph.get_critical_tasks().get(project_key, [])
            logger.info(f"项目 {project_key} 的关键任务数量: {len(critical_tasks)}")

            # graph.generate_visualization_html(
            #     f"./visualizations/critical_path_{project_key}"
            # )
            # image_url = f"http://localhost:8000/critical_path_{project_key}.html"
            return {
                f"项目{project_key}任务列表": tasks,
                f"项目{project_key}关键路径任务列表": critical_tasks,
                # f"项目{project_key}关键路径图链接地址": image_url,
            }

    except Exception as e:
        logger.error(f"查找关键任务失败: {e}")
        return []


if __name__ == "__main__":
    # 配置日志
    log_dir = "log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, "aoe_graph_main.log")),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    # 示例任务列表
    tasks = [
        {
            "key": "T1",
            "name": "任务1",
            "plan_start": "2025-05-29T12:00:00",
            "plan_end": "2025-06-02T17:00:00",
            "predecessors": [],
        },
        {
            "key": "T2",
            "name": "任务2",
            "plan_start": "2025-06-02T09:00:00",
            "plan_end": "2025-06-04T17:00:00",
            "predecessors": ["T1"],
        },
        {
            "key": "T3",
            "name": "任务3",
            "plan_start": "2025-06-03T09:00:00",
            "plan_end": "2025-06-06T17:00:00",
            "predecessors": [],
        },
        {
            "key": "T4",
            "name": "任务4",
            "plan_start": "2025-06-04T09:00:00",
            "plan_end": "2025-06-08T17:00:00",
            "predecessors": ["T2", "T3"],
        },
    ]

    # 创建AOEGraph实例并构建图
    # graph = AOEGraph(key="P1", name="项目1")
    # graph.build_graph_from_tasks(tasks, key="P1", name="项目1")
    # # 计算关键路径
    # critical_edges, project_duration = graph.calculate_critical_path()

    # # 打印结果
    # graph.print_graph()
    # graph.print_critical_path()
    # graph.generate_visualization("project_graph", format="png")
    # find_critical_tasks("WORK")
