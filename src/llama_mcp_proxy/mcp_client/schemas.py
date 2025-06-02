from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class BaseServerConfig:
    """Base class for all server configurations"""

    pass


@dataclass
class StdioServerConfig(BaseServerConfig):
    """Configuration for STDIO MCP servers - requires command, no url"""

    command: str
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    timeout: Optional[float] = None


@dataclass
class SSEServerConfig(BaseServerConfig):
    """Configuration for STDIO MCP servers - requires command, no url"""

    url: str
    transport: Optional[str] = None
    headers: Optional[dict[str, Literal["sse", "websocket"]]] = None