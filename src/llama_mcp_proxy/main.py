# server.py
import asyncio
import argparse
import json
import os
from typing import Any, Optional

from aiohttp import ClientSession, ClientTimeout, web
from config import get_root_logger
from mcp_client import BaseMCPClient, load_mcp_servers

logger = get_root_logger()

# Configuration
OPENAI_API_BASE_URL = None
ENABLE_MCP = None
MAX_ITERATION = None
MCP_CONFIG_PATH = None
SERVER_PORT = None
TIMEOUT = ClientTimeout(total=60)

connected_servers: dict[str, BaseMCPClient] = {}


def parse_tools_from_response(response_data: dict):
    tool_calls = []
    if (
        response_data.get("choices")
        and len(response_data["choices"]) > 0
        and response_data["choices"][0].get("message", {}).get("tool_calls")
    ):
        tool_calls = response_data["choices"][0]["message"]["tool_calls"]
    return tool_calls


async def proxy_request(
    path: str, request: web.Request, inject_tools: bool = True
) -> web.Response:
    """Generic proxy function that forwards requests to OpenAI API and handles MCP tool calls."""
    try:
        # Read request body
        body = await request.read()
        request_data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON in request body"}, status=400)

    # Remove these headers because
    headers = {}
    excluded_headers = {
        "host",
        "content-length",
        "content-encoding",
        "connection",
        "upgrade",
        "proxy-connection",
        "trailer",
    }
    for header_name, header_value in request.headers.items():
        if header_name.lower() not in excluded_headers:
            headers[header_name] = header_value

    logger.info(f"Proxying {request.method} request to {path}")

    # Add tools if requested and not already present
    if inject_tools and "tools" not in request_data:
        tools = get_mcp_tools()
        request_data["tools"] = tools

    # Make request to OpenAI
    url = f"{OPENAI_API_BASE_URL}/{path}"

    async with ClientSession(timeout=TIMEOUT) as session:
        try:
            async with session.request(
                method=request.method,
                url=url,
                headers=headers,
                json=request_data if body else None,
            ) as response:
                logger.info(f"OpenAI API responded with status: {response.status}")

                # IF streaming, but Llama CPP doesn't support tool streaming yet
                if request_data.get("stream", False) and response.status == 200:
                    resp = web.StreamResponse(
                        status=response.status,
                        headers={
                            "Content-Type": "text/event-stream",
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                        },
                    )
                    await resp.prepare(request)

                    async for chunk in response.content.iter_any():
                        await resp.write(chunk)

                    await resp.write_eof()
                    return resp

                # Handle non-streaming
                content = await response.read()
                if response.status == 200 and ENABLE_MCP:
                    try:
                        response_data = json.loads(content)
                        # Check if response contains tool calls
                        if tool_calls := parse_tools_from_response(response_data):
                            processed_response = await handle_tool_calls(
                                tool_calls, request_data, headers, session
                            )

                            return web.json_response(processed_response, status=200)

                    except json.JSONDecodeError:
                        logger.warning("Could not parse OpenAI response as JSON")

                # Return original response if no tool calls, ENABLE_MCP False or Error
                return web.Response(
                    body=content,
                    status=response.status,
                    headers=response.headers,
                )

        except Exception as e:
            logger.error(f"Error proxying request: {str(e)}", exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)


async def execute_tool_calls(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    messages = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
    # Execute each tool call and add results to messages
    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]

        logger.info(f"Executing MCP tool: {tool_name} with args: {tool_args}")
        namespace, tool_name = tool_name.split(".")
        mcp_tool = connected_servers.get(namespace, {})
        if not mcp_tool:
            # TODO: We gotta do something if it makes up a tool
            logger.error("LLM called tool which does not exist", exc_info=True)

        try:
            # Execute the MCP function
            tool_result = await mcp_tool.call_tool(tool_name, tool_args)

            # Add tool result to messages
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tool_result)
                    if isinstance(tool_result, (dict, list))
                    else str(tool_result),
                }
            )

        except Exception as e:
            logger.error(f"Error executing MCP tool {tool_name}: {str(e)}", exc_info=True)
            # Add error message as tool result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": f"Error executing tool: {str(e)}",
                }
            )
    return messages


async def handle_tool_calls(
    tool_calls: list[dict[str, Any]],
    original_request: dict,
    headers: dict,
    session: ClientSession,
) -> dict:
    """Handle tool calls by executing MCP functions and getting final response."""
    # Add tool responses to original message
    messages = original_request.get("messages", []).copy()
    tool_responses = await execute_tool_calls(tool_calls=tool_calls)
    messages.extend(tool_responses)

    follow_up_request = original_request.copy()
    follow_up_request["messages"] = messages

    # Remove tool_choice if it was set to force tool usage
    if "tool_choice" in follow_up_request:
        del follow_up_request["tool_choice"]

    url = f"{OPENAI_API_BASE_URL}/chat/completions"
    # Keeping looping until no more tool calls
    for _ in range(MAX_ITERATION):
        async with session.request(
            method="POST",
            url=url,
            headers=headers,
            json=follow_up_request,
        ) as follow_up_response:
            if follow_up_response.status == 200:
                final_content = await follow_up_response.read()
                final_response = json.loads(final_content)

                if tool_calls := parse_tools_from_response(final_response):
                    messages = follow_up_request.get("messages", []).copy()
                    tool_responses = await execute_tool_calls(tool_calls=tool_calls)
                    messages.extend(tool_responses)
                    follow_up_request["messages"] = messages
                else:
                    return final_response
            else:
                logger.error(
                    f"Follow-up request failed with status: {follow_up_response.status}", exc_info=True
                )
                error_content = await follow_up_response.read()
                logger.error(f"Follow-up error response: {error_content}")

                # Return original response
                return final_response
    msg = f"Reached Max iteration of {MAX_ITERATION}."
    raise RuntimeError(msg)


async def chat_completions_handler(request: web.Request) -> web.Response:
    """Handle /v1/chat/completions requests."""
    return await proxy_request("v1/chat/completions", request)


async def health_handler(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "healthy", "service": "openai-proxy"})


@web.middleware
async def logging_middleware(request: web.Request, handler):
    """Log all requests and responses."""
    logger.info(f"Incoming request: {request.method} {request.path}")
    response = await handler(request)
    logger.info(f"Response status: {response.status}")
    return response


def get_mcp_tools(server_names: Optional[str] = None):
    tools = []
    if not server_names:
        server_names = connected_servers.keys()
    for server_name, mcp_server in connected_servers.items():
        if server_name in server_names:
            tools.extend(mcp_server.openai_tools)
    return tools


async def init_mcp_servers(app):
    """Initialize MCP servers on app startup"""
    global connected_servers


    try:
        logger.info("Attempting to connect to MCP servers")
        # Load and connect to MCP servers
        mcp_servers = load_mcp_servers(MCP_CONFIG_PATH)
        for server_name, mcp_server in mcp_servers.items():
            try:
                logger.info(f"Attempting to connect {server_name}")
                await mcp_server.connect()
                connected_servers[server_name] = mcp_server
                logger.info(f"Connected to MCP server: {server_name}")
            except Exception as e:
                logger.error(f"Failed to connect to {server_name}: {e}")

    except Exception as e:
        logger.error(f"Error initializing MCP servers: {e}", exc_info=True)


async def cleanup_mcp_servers(app):
    """Cleanup MCP servers on app shutdown"""
    global connected_servers

    logger.info("Cleaning up MCP servers...")
    for server_name, server in connected_servers.items():
        try:
            await server.disconnect()
            logger.info(f"Disconnected from {server_name}", exc_info=True)
        except Exception as e:
            logger.error(f"Error disconnecting {server_name}: {e}", exc_info=True)

    connected_servers.clear()


def create_app():
    app = web.Application(middlewares=[logging_middleware])

    if ENABLE_MCP:
        app.on_startup.append(init_mcp_servers)
        app.on_cleanup.append(cleanup_mcp_servers)
    else:
        logger.info(
            "Environment variable 'ENABLE_MCP' is set to false. "
            "MCP servers WILL NOT be initialized. Proxy mode only"
        )

    # Add routes
    app.router.add_post("/v1/chat/completions", chat_completions_handler)
    app.router.add_get("/health", health_handler)

    return app


def parse_args():
    parser = argparse.ArgumentParser(description='OpenAI API Proxy with MCP support')
    
    parser.add_argument(
        '--openai_api_base_url',
        default='http://192.168.1.16:9091',
        help='Base URL for OpenAI API (default: http://192.168.1.16:9091)'
    )
    
    parser.add_argument(
        '--enable_mcp',
        type=str,
        choices=['true', 'false', '1', '0', 'yes', 'no'],
        default='true',
        help='Enable MCP functionality (default: true)'
    )
    
    parser.add_argument(
        '--max_iteration',
        type=int,
        default=25,
        help='Maximum iterations for tool calls (default: 25)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=8001,
        help='Port to run the server on'
    )
    
    parser.add_argument(
        '--mcp_config_path',
        default='/config/mcp_config.json',
        help='Path to MCP configuration file (default: /config/mcp_config.json)'
    )
    
    return parser.parse_args()


async def main():
    global OPENAI_API_BASE_URL, ENABLE_MCP, MAX_ITERATION, MCP_CONFIG_PATH, SERVER_PORT
    
    args = parse_args()
    OPENAI_API_BASE_URL = args.openai_api_base_url
    ENABLE_MCP = args.enable_mcp.lower() in ("true", "1", "yes")
    MAX_ITERATION = args.max_iteration
    MCP_CONFIG_PATH = args.mcp_config_path
    SERVER_PORT =  args.port

    app = create_app()

    logger.info("Starting OpenAI API Proxy on port 8000")
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=8000)
    await site.start()

    logger.info("Server started successfully")

    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("LLAMA MCP Proxy shutting down")
    except Exception as e:
        logger.critical(f"Fatal error in main application: {e}", exc_info=True)
