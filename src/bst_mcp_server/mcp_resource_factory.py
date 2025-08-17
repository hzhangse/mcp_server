# ... existing code ...

import json
from typing import Optional
from mcp.server.fastmcp import FastMCP

from bst_mcp_server.http_utils import call_restful_api


def make_rest_resource(
    mcp_server: FastMCP,
    endpoint: str,
    description: Optional[str] = None,
    base_config: Optional[str] = None,
):
    """
    Factory function to create a MCP resource for calling RESTful APIs.
    """

    resource_url = f"resource://jira_timesheet/{endpoint}/{{params}}"

    @mcp_server.resource(resource_url)
    async def rest_resource_handler(params: str) -> str:
        try:
            request_params = json.loads(params)
        except json.JSONDecodeError as e:
            return f"Invalid JSON input: {e}"

        try:
            result = call_restful_api(
                base_config or "default", endpoint, request_params
            )
            return json.dumps(result) if isinstance(result, dict) else str(result)
        except Exception as e:
            return f"Error calling API: {str(e)}"

    if description:
        rest_resource_handler.__doc__ = description

    return rest_resource_handler
