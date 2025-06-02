# mcp_client.py
import json
from json.decoder import JSONDecodeError
from pathlib import Path
from typing import Any, Type

import dacite
from mcp_client.base_client import BaseMCPClient
from config import get_logger
from mcp import StdioServerParameters
from mcp_client.schemas import BaseServerConfig, SSEServerConfig, StdioServerConfig
from mcp_client.stdio_client import MCPStdioClient

logger = get_logger(__name__)


class MCPClientRegister:
    _config_types = [StdioServerConfig, SSEServerConfig]
    _client_creators = {}

    @classmethod
    def register(cls, config_type: Type[BaseServerConfig]):
        """Decorator to register client creators"""

        def decorator(func):
            cls._client_creators[config_type] = func
            return func

        return decorator

    @classmethod
    def create_client(cls, server_name: str, config: dict[str, Any]) -> BaseMCPClient:
        try:
            logger.debug(f"Attempting to create MCP client for {server_name}")
            server_config = cls._parse_config(config)
            creator_function = cls._client_creators[type(server_config)]
            return creator_function(server_name, server_config)
        # Log errors don't re-raise. Not need to stop program
        except KeyError:
            logger.warning(f"Unknown server type from {server_name}. Skipping.")
        except NotImplementedError:
            logger.warning(f"SSE servers not supported yet. Will ignore: {server_name}")
        except ValueError as e:
            logger.warning(f"Skipping {server_name}: {e}")

    @classmethod
    def _parse_config(cls, config_dict: dict[str, Any]) -> BaseServerConfig:
        # Try each configuration type until one succeeds
        for config_type in cls._config_types:
            logger.debug(f"Checking if server is of transport type {config_type}")
            try:
                logger.debug(f"Server is of transport type {config_type}")
                return dacite.from_dict(
                    data_class=config_type,
                    data=config_dict,
                    config=dacite.Config(strict=True),
                )
            except dacite.DaciteError:
                logger.debug(f"Server is not of transport type {config_type}")
                continue  # Try next config type

        # If we get here, none of the config types worked
        available_types = [t.__name__ for t in cls._config_types]
        raise ValueError(
            f"Configuration doesn't match any known types: {available_types}"
        )


# Register client creators for each specific config type
@MCPClientRegister.register(StdioServerConfig)
def create_stdio_client(
    server_name: str, config: StdioServerConfig
) -> StdioServerParameters:
    """Create STDIO MCP client"""
    server_params = StdioServerParameters(
        command=config.command, args=config.args or [], env=config.env or None
    )
    server = MCPStdioClient(name=server_name, params=server_params)
    return server


@MCPClientRegister.register(SSEServerConfig)
def create_sse_client(server_name: str, config: SSEServerConfig) -> None:
    logger.debug("User attempted to create unsupported SSE server type")
    raise NotImplementedError()


def load_mcp_servers(path: str) -> dict[str, BaseMCPClient]:
    clients = {}
    try:
        config_path = path
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.loads(f.read())
            if config is None:
                raise ValueError(
                    "MCP Config file is empty. Set ENV var 'ENABLE_MCP' if you wish to disable MCP proxy"
                )
            for server_name, server_config in config.get("mcpServers", {}).items():
                client = MCPClientRegister.create_client(server_name, server_config)
                if client:
                    logger.debug(f"Successfully parsed server {server_name}")
                    clients[server_name] = client
            return clients

    except FileNotFoundError:
        raise FileNotFoundError(f"MCP Config file not found: {config_path}")
    except JSONDecodeError:
        raise JSONDecodeError(f"Error parsing MCP Config file: {config_path}")
    except Exception as e:
        raise Exception(f"Error loading MCP Config file: {e}")
