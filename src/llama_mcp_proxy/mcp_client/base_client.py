from abc import abstractmethod
from typing import Any, Optional

from config import get_logger
from mcp import ClientSession
from mcp_client.mcp_enums import ConnectionState

logger = get_logger(__name__)


class BaseMCPClient:
    """_summary_

    _extended_summary_
    """

    def __init__(self, name: str):
        self.name = name
        self.state = ConnectionState.DISCONNECTED
        self.session: Optional[ClientSession] = None
        self.exit_stack = None
        self.mcp_tools: Optional[list] = None
        self.openai_tools: Optional[list] = None

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the MCP server. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> dict:
        pass

    def _convert_mcp_tools_to_openai(self):
        openai_tools = []
        logger.debug(f'Attempting to convert {len(self.mcp_tools)} to OpenAI format')
        for mcp_tool in self.mcp_tools:
            try:
                openai_tool = BaseMCPClient._convert_single_tool(self.name, mcp_tool)
                if openai_tool:
                    openai_tools.append(openai_tool)
            except Exception as e:
                logger.warning(
                    f"Failed to convert tool {mcp_tool.get('name', 'unknown')} to OpenAi format: {e}"
                )
                continue
        self.openai_tools = openai_tools

    @staticmethod
    def _convert_single_tool(namespace: str, mcp_tool: Any) -> Optional[dict]:
        # Handle both dict and object formats
        if hasattr(mcp_tool, "name"):
            name = mcp_tool.name
            description = mcp_tool.description
            input_schema = (
                mcp_tool.inputSchema if hasattr(mcp_tool, "inputSchema") else {}
            )
        else:
            name = mcp_tool.get("name")
            description = mcp_tool.get("description", "")
            input_schema = mcp_tool.get("inputSchema", {})

        if not name:
            raise RuntimeError("Tool missing name, skipping")
        logger.debug(f'Attempting to convert tool {name} to OpenAI format')

        # Convert MCP input schema to OpenAI parameters format
        parameters = BaseMCPClient._convert_input_schema(input_schema)

        # add namespace to tool to avoid collision
        logger.debug(f'Successfully converted MCP tool {name} to OpenAI format')
        return {
            "type": "function",
            "function": {
                "name": f"{namespace}.{name}",
                "description": description or f"Execute {name} tool",
                "parameters": parameters,
            },
        }

    @staticmethod
    def _convert_input_schema(input_schema: dict) -> dict:
        """
        Convert MCP input schema (JSON Schema) to OpenAI parameters format.

        MCP uses standard JSON Schema, OpenAI expects the same format
        so this is mostly a pass-through with some cleanup.
        """
        if not input_schema:
            return {"type": "object", "properties": {}, "required": []}

        # JSON Schema is largely compatible with OpenAI format
        # Just ensure we have required fields
        schema = input_schema.copy()

        # Ensure we have the basic structure
        if "type" not in schema:
            schema["type"] = "object"

        if "properties" not in schema:
            schema["properties"] = {}

        if "required" not in schema:
            schema["required"] = []

        return schema

    async def disconnect(self):
        if self.state != ConnectionState.DISCONNECTED:
            await self.exit_stack.aclose()
            self.session = None
            self.tools = None
            self.state = ConnectionState.DISCONNECTED
            logger.info(f"Disconnected from  MCP server {self.name}")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
