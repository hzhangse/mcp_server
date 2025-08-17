import asyncio
import json
import logging
import os
import re
import shutil
from contextlib import AsyncExitStack
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

# 配置日志
log_dir = "log"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "bst_chat.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class Configuration:
    """Manages configuration and environment variables for the MCP client."""

    def __init__(self) -> None:
        """Initialize configuration with environment variables."""
        logger.info("初始化配置")
        self.load_env()
        self.api_key = os.getenv("LLM_API_KEY")
        self.api_url = os.getenv("LLM_API_URL")
        self.llm_model = os.getenv("LLM_MODEL")
        logger.debug(
            f"配置加载完成: api_url={self.api_url}, llm_model={self.llm_model}"
        )

    @staticmethod
    def load_env() -> None:
        """Load environment variables from .env file."""
        logger.debug("加载环境变量")
        load_dotenv()

    @staticmethod
    def load_config(file_path: str) -> dict[str, Any]:
        """Load server configuration from JSON file.

        Args:
            file_path: Path to the JSON configuration file.

        Returns:
            Dict containing server configuration.

        Raises:
            FileNotFoundError: If configuration file doesn't exist.
            JSONDecodeError: If configuration file is invalid JSON.
        """
        logger.info(f"加载配置文件: {file_path}")
        with open(file_path, "r") as f:
            config = json.load(f)
        logger.debug(f"配置文件加载完成: {file_path}")
        return config

    @property
    def llm_api_key(self) -> str:
        """Get the LLM API key.

        Returns:
            The API key as a string.

        Raises:
            ValueError: If the API key is not found in environment variables.
        """
        if not self.api_key:
            error_msg = "LLM_API_KEY not found in environment variables"
            logger.error(error_msg)
            raise ValueError(error_msg)
        logger.debug("获取LLM API密钥成功")
        return self.api_key


class Server:
    """Manages MCP server connections and tool execution."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config
        self.stdio_context: Any | None = None
        self.session: ClientSession | None = None
        self._cleanup_lock: asyncio.Lock = asyncio.Lock()
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        logger.info(f"初始化服务器: {name}")

    async def initialize(self) -> None:
        """Initialize the server connection."""
        logger.info(f"初始化服务器连接: {self.name}")
        server_type = self.config.get("type", "stdio")
        logger.debug(f"服务器类型: {server_type}")

        if server_type == "stdio":
            logger.info(f"初始化stdio服务器: {self.name}")
            command = (
                shutil.which("npx")
                if self.config["command"] == "npx"
                else self.config["command"]
            )
            if command is None:
                error_msg = "The command must be a valid string and cannot be None."
                logger.error(error_msg)
                raise ValueError(error_msg)

            server_params = StdioServerParameters(
                command=command,
                args=self.config["args"],
                env=(
                    {**os.environ, **self.config["env"]}
                    if self.config.get("env")
                    else None
                ),
            )
            try:
                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read, write = stdio_transport
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self.session = session
                logger.info(f"stdio服务器初始化完成: {self.name}")
            except Exception as e:
                logger.error(
                    f"Error initializing server {self.name}: {e}", exc_info=True
                )
                await self.cleanup()
                raise
        elif server_type == "sse":
            logger.info(f"初始化SSE服务器: {self.name}")
            try:
                base_url = self.config["baseUrl"]
                sse_transport = await self.exit_stack.enter_async_context(
                    sse_client(url=base_url)
                )
                read, write = sse_transport
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self.session = session
                logger.info(f"SSE服务器初始化完成: {self.name}")
            except Exception as e:
                logger.error(
                    f"Error initializing SSE server {self.name}: {e}", exc_info=True
                )
                await self.cleanup()
                raise
        elif server_type == "streamableHttp":
            logger.info(f"初始化Streamable HTTP服务器: {self.name}")
            try:
                base_url = self.config["baseUrl"]
                streamable_http_transport = await self.exit_stack.enter_async_context(
                    streamablehttp_client(url=base_url)
                )
                read, write, _ = streamable_http_transport
                session = await self.exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self.session = session
                logger.info(f"Streamable HTTP服务器初始化完成: {self.name}")
            except Exception as e:
                logger.error(
                    f"Error initializing Streamable HTTP server {self.name}: {e}",
                    exc_info=True,
                )
                await self.cleanup()
                raise
        else:
            error_msg = f"Unsupported server type: {server_type}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    async def list_tools(self) -> list[Any]:
        """List available tools from the server.

        Returns:
            A list of available tools.

        Raises:
            RuntimeError: If the server is not initialized.
        """
        logger.info(f"列出服务器工具: {self.name}")
        if not self.session:
            error_msg = f"Server {self.name} not initialized"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        tools_response = await self.session.list_tools()
        tools = []

        for item in tools_response:
            if isinstance(item, tuple) and item[0] == "tools":
                tools.extend(
                    Tool(tool.name, tool.description, tool.inputSchema)
                    for tool in item[1]
                )

        logger.info(f"服务器 {self.name} 共找到 {len(tools)} 个工具")
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        retries: int = 2,
        delay: float = 1.0,
    ) -> Any:
        """Execute a tool with retry mechanism.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments.
            retries: Number of retry attempts.
            delay: Delay between retries in seconds.

        Returns:
            Tool execution result.

        Raises:
            RuntimeError: If server is not initialized.
            Exception: If tool execution fails after all retries.
        """
        logger.info(f"执行工具: {tool_name}")
        logger.debug(f"工具参数: {arguments}")
        if not self.session:
            error_msg = f"Server {self.name} not initialized"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        attempt = 0
        while attempt < retries:
            try:
                logger.info(f"执行 {tool_name}...")
                result = await self.session.call_tool(tool_name, arguments)
                logger.info(f"工具 {tool_name} 执行完成")
                return result

            except Exception as e:
                attempt += 1
                logger.warning(
                    f"Error executing tool: {e}. Attempt {attempt} of {retries}."
                )
                if attempt < retries:
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("Max retries reached. Failing.")
                    raise

    async def cleanup(self) -> None:
        """Clean up server resources."""
        logger.info(f"清理服务器资源: {self.name}")
        async with self._cleanup_lock:
            try:
                await self.exit_stack.aclose()
                self.session = None
                self.stdio_context = None
                logger.info(f"服务器 {self.name} 资源清理完成")
            except Exception as e:
                logger.error(
                    f"Error during cleanup of server {self.name}: {e}", exc_info=True
                )


class Tool:
    """Represents a tool with its properties and formatting."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self.name: str = name
        self.description: str = description
        self.input_schema: dict[str, Any] = input_schema
        logger.debug(f"创建工具对象: {name}")

    def format_for_llm(self) -> str:
        """Format tool information for LLM.

        Returns:
            A formatted string describing the tool.
        """
        logger.debug(f"格式化工具信息: {self.name}")
        args_desc = []
        if "properties" in self.input_schema:
            for param_name, param_info in self.input_schema["properties"].items():
                arg_desc = (
                    f"- {param_name}: {param_info.get('description', 'No description')}"
                )
                if param_name in self.input_schema.get("required", []):
                    arg_desc += " (required)"
                args_desc.append(arg_desc)

        # Build the formatted output with title as a separate field
        output = f"Tool: {self.name}\n"

        output += f"""Description: {self.description}
Arguments:
{chr(10).join(args_desc)}
"""

        logger.debug(f"工具 {self.name} 格式化完成")
        return output


class LLMClient:
    """Manages communication with the LLM provider."""

    def __init__(self, api_key: str, api_url: str, llm_model: str) -> None:
        self.api_key: str = api_key
        self.api_url: str = api_url
        self.llm_model: str = llm_model
        logger.info("初始化LLM客户端")
        logger.debug(f"LLM配置: api_url={api_url}, model={llm_model}")

    def get_response(self, messages: list[dict[str, str]]) -> str:
        """Get a response from the LLM.

        Args:
            messages: A list of message dictionaries.

        Returns:
            The LLM's response as a string.

        Raises:
            httpx.RequestError: If the request to the LLM fails.
        """
        logger.info("获取LLM响应")
        logger.debug(f"消息数量: {len(messages)}")
        url = self.api_url + ""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "messages": messages,
            "model": self.llm_model,
            "temperature": 0.7,
            "max_tokens": 32768,
            "top_p": 0.95,
            "chat_template_kwargs": {"enable_thinking": True},
            "stream": True,
            "stop": None,
        }

        try:
            with httpx.Client() as client:
                timeout = httpx.Timeout(60.0, read=60.0)
                response = client.post(
                    url, headers=headers, json=payload, timeout=timeout
                )
                response.raise_for_status()
                # Handle streaming response
                full_response = ""
                logger.debug("处理流式响应")
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix
                        if data != "[DONE]":
                            try:
                                chunk = json.loads(data)
                                if "choices" in chunk and len(chunk["choices"]) > 0:
                                    choice = chunk["choices"][0]
                                    if (
                                        "delta" in choice
                                        and "content" in choice["delta"]
                                    ):
                                        full_response += choice["delta"]["content"]
                            except json.JSONDecodeError:
                                # Skip lines that aren't valid JSON
                                continue
                logger.info("LLM响应获取完成")
                logger.debug(f"响应长度: {len(full_response)} 字符")
                return full_response
        except httpx.RequestError as e:
            error_message = f"Error getting LLM response: {str(e)}"
            logger.error(error_message, exc_info=True)

            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code
                logger.error(f"Status code: {status_code}")
                logger.error(f"Response details: {e.response.text}")

            return (
                f"I encountered an error: {error_message}. "
                "Please try again or rephrase your request."
            )


class ChatSession:
    """Orchestrates the interaction between user, LLM, and tools."""

    def __init__(self, servers: list[Server], llm_client: LLMClient) -> None:
        self.servers: list[Server] = servers
        self.llm_client: LLMClient = llm_client
        logger.info(f"初始化聊天会话，服务器数量: {len(servers)}")

    async def cleanup_servers(self) -> None:
        """Clean up all servers properly."""
        logger.info("清理所有服务器")
        for server in reversed(self.servers):
            try:
                await server.cleanup()
            except Exception as e:
                logger.warning(f"Warning during final cleanup: {e}")

    async def process_llm_response(self, llm_response: str) -> str:
        """Process the LLM response and execute tools if needed.

        Args:
            llm_response: The response from the LLM.

        Returns:
            The result of tool execution or the original response.
        """
        logger.info("处理LLM响应")
        logger.debug(f"响应内容长度: {len(llm_response)} 字符")
        import json

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*({.*?})\s*```", llm_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = llm_response
        think_end = "</think>"
        idx = json_str.find(think_end)
        if idx != -1:
            # 只保留 </think> 之后的内容
            json_str = json_str[idx + len(think_end) :].strip()
        try:
            tool_call = json.loads(json_str)
            if "tool" in tool_call and "arguments" in tool_call:
                logger.info(f"执行工具调用: {tool_call['tool']}")
                logger.debug(f"工具参数: {tool_call['arguments']}")

                for server in self.servers:
                    tools = await server.list_tools()
                    if any(tool.name == tool_call["tool"] for tool in tools):
                        try:
                            result = await server.execute_tool(
                                tool_call["tool"], tool_call["arguments"]
                            )

                            if isinstance(result, dict) and "progress" in result:
                                progress = result["progress"]
                                total = result["total"]
                                percentage = (progress / total) * 100
                                logger.info(
                                    f"Progress: {progress}/{total} ({percentage:.1f}%)"
                                )

                            logger.info(f"工具执行完成: {tool_call['tool']}")
                            return f"Tool execution result: {result}"
                        except Exception as e:
                            error_msg = f"Error executing tool: {str(e)}"
                            logger.error(error_msg, exc_info=True)
                            return error_msg

                return f"No server found with tool: {tool_call['tool']}"
            logger.debug("响应中未找到工具调用")
            return llm_response
        except json.JSONDecodeError:
            logger.debug("响应不是有效的JSON格式")
            return llm_response

    async def start(self) -> None:
        """Main chat session handler."""
        logger.info("启动聊天会话")
        try:
            for server in self.servers:
                try:
                    await server.initialize()
                except Exception as e:
                    logger.error(f"Failed to initialize server: {e}", exc_info=True)
                    await self.cleanup_servers()
                    return

            all_tools = []
            for server in self.servers:
                tools = await server.list_tools()
                all_tools.extend(tools)

            tools_description = "\n".join([tool.format_for_llm() for tool in all_tools])

            system_message = (
                "你是一个有用的助手，可以访问以下工具:\n\n"
                f"{tools_description}\n"
                "根据用户的问题选择合适的工具。如果不需要工具，请直接回答. "
                # "If no tool is needed, reply directly.\n\n"
                "重要：当你需要使用工具时，必须用以下精确的 JSON 对象格式进行响应，不要包含其他内容:\n "
                "the exact JSON object format below, nothing else:\n"
                "{\n"
                '    "tool": "tool-name",\n'
                '    "arguments": {\n'
                '        "argument-name": "value"\n'
                "    }\n"
                "}\n\n"
                "收到工具的响应后：\n"
                "1. 对数据无需任何解读和阐述，只做数据格式转化，把json数组里的数据重新组织并表格化即可\n\n"
                "请只使用上面明确指定的工具."
            )

            messages = [{"role": "system", "content": system_message}]

            while True:
                try:
                    user_input = input("You: ").strip().lower()
                    if user_input in ["quit", "exit"]:
                        logger.info("用户退出聊天")
                        break

                    messages.append({"role": "user", "content": user_input})

                    llm_response = self.llm_client.get_response(messages)
                    logger.info(f"\nAssistant: {llm_response}")

                    result = await self.process_llm_response(llm_response)

                    if result != llm_response:

                        # 提取 text='...' 中的内容
                        text_match = re.search(r"text='(.*?)'", result, re.DOTALL)

                        if text_match:
                            # 提取原始 JSON 字符串
                            raw_str = text_match.group(1)
                            try:
                                # ✅ 正确方法：先 encode 成 bytes，用 utf-8 避免中文出错
                                json_str = (
                                    raw_str.replace(
                                        "\\\\", "\\"
                                    )  # 先：\\\\ → \（处理双重转义）
                                    .replace("\\n", "\n")  # 换行
                                    .replace("\\t", "\t")  # 制表符
                                    .replace("\\r", "\r")  # 回车
                                    .replace('\\"', '"')  # 双引号
                                )
                                json_data = json.loads(json_str)
                                logger.debug(
                                    json.dumps(json_data, ensure_ascii=False, indent=4)
                                )

                            except json.JSONDecodeError as e:
                                logger.error(f"JSON 解析失败: {e}")
                            logger.debug("修复后的内容为：\n", json_data)
                        else:
                            logger.debug("未找到 text 值")

                        messages = [
                            {
                                "role": "system",
                                "content": "你是一个数据格式整理助手，你的指责是将杂乱的数据转换成表格形式并展示",
                            }
                        ]
                        messages.append(
                            {
                                "role": "user",
                                "content": f"/no_think 请提取下面json内容，把json数组里的数据重新组织并表格化即可，禁止做任何形式的解读和阐述，只做数据格式转化 \n {json_str}",
                            }
                        )

                        # messages.append({"role": "assistant", "content": llm_response})

                        # messages.append({"role": "assistant", "content": result})
                        # messages.append({"role": "system", "content":  result})

                        final_response = self.llm_client.get_response(messages)

                        logger.info(f"\nFinal response: {final_response}")
                        messages.append(
                            {"role": "assistant", "content": final_response}
                        )
                    else:
                        messages.append({"role": "assistant", "content": llm_response})

                except KeyboardInterrupt:
                    logger.info("用户中断聊天")
                    break

        finally:
            await self.cleanup_servers()


async def main() -> None:
    """Initialize and run the chat session."""
    logger.info("启动主程序")
    try:
        config = Configuration()

        # 获取当前模块所在目录，然后拼接到 config 目录下的 config.yaml
        current_dir = os.path.dirname(__file__)
        config_file = os.path.join(current_dir, "config", "mcp_servers_config.json")

        if not os.path.exists(config_file):
            error_msg = f"配置文件 {config_file} 不存在"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        server_config = config.load_config(config_file)
        servers = [
            Server(name, srv_config)
            for name, srv_config in server_config["mcpServers"].items()
        ]
        llm_client = LLMClient(config.api_key, config.api_url, config.llm_model)
        chat_session = ChatSession(servers, llm_client)
        await chat_session.start()
        logger.info("主程序执行完成")
    except Exception as e:
        logger.error(f"主程序执行出错: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
