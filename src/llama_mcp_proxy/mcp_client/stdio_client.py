from contextlib import AsyncExitStack

from config import get_logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_client.base_client import BaseMCPClient
from mcp_client.client_exceptions import MCPConnectionError
from mcp_client.mcp_enums import ConnectionState

logger = get_logger(__name__)


class MCPStdioClient(BaseMCPClient):
    def __init__(self, name: str, params: StdioServerParameters):
        super().__init__(name)
        self.stdio_params = params

    async def connect(self):
        if self.state == ConnectionState.CONNECTED:
            logger.info(f"{self.name} already connected")
            return

        self.state = ConnectionState.CONNECTING
        logger.info(f"Connecting to {self.name}")

        try:
            self.exit_stack = AsyncExitStack()
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(self.stdio_params)
            )
            self.stdio, self.write = stdio_transport

            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.stdio, self.write)
            )

            await self.session.initialize()
            response = await self.session.list_tools()
            self.mcp_tools = response.tools
            self._convert_mcp_tools_to_openai()

            self.state = ConnectionState.CONNECTED
            logger.info(f"Connected to {self.name}, found {len(self.mcp_tools)} tools")

        except Exception as e:
            self.state = ConnectionState.ERROR
            logger.debug(f"Failed to connect to {self.name}: {e}")
            await self.exit_stack.aclose()
            self.session = None
            raise MCPConnectionError(str(e))

    def list_tools(self) -> list:
        if not self.is_connected:
            raise RuntimeError(f"Not connected to {self.name}")
        return self.openai_tools or []

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if not self.is_connected:
            raise RuntimeError(f"Not connected to {self.name}")

        try:
            response = await self.session.call_tool(name, arguments)
            text = response.content[0].text
            return text
        except Exception as e:
            logger.error(f"Tool call failed on {self.name}: {e}")
            raise
