# MCP Proxy for Llama CPP Server

---

## Table of Contents

- [MCP Proxy for Llama CPP Server](#mcp-proxy-for-llama-cpp-server)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Features](#features)
  - [Setup \& Installation](#setup--installation)
  - [Usage](#usage)
    - [Options](#options)
  - [MCP Config JSON](#mcp-config-json)
  - [Limitations](#limitations)
  - [Contributions](#contributions)
  - [License](#license)

---

## Overview

I created this proxy to integrate my MCP server tools with `llama.cpp`. It works by discovering all available tools on the MCP server and presenting them as OpenAI-compatible tools for the LLM. When the LLM requests a tool, this proxy intercepts the call and invokes the appropriate MCP tool.

---

## Features

* **Seamless Integration:** Exposes MCP server tools to Llama CPP.
* **Automatic Tool Discovery:** Automatically identifies and registers tools from connected MCP servers and translates them into a format compatible with OpenAI's tool specifications.
* **Tool Routing:** Intercepts LLM tool calls and ensures the correct MCP tool is executed.

---

## Setup & Installation

This project uses `uv` for dependency management.

1.  **Install `uv`**:
    ```bash
    curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh
    ```
2.  **Clone the repository**:
    ```bash
    git clone <your-repository-url> # Replace with your actual repository URL
    cd <your-repository-name>       # Replace with your actual repository name
    ```
3.  **Install dependencies and activate the virtual environment**:
    ```bash
    uv sync
    . ./.venv/bin/activate
    ```

---

## Usage

To start the proxy server, use the following command:

```bash
python src/llama_mcp_proxy/main.py \
    --enable_mcp=true \
    --openai_api_base_url=[http://192.168.1.16:9091](http://192.168.1.16:9091) \
    --port=8000 \
    --mcp_config_path=/Users/dave/Workspace/llama-cpp-mcp-bridge/mcp_config.json
```


### Options

* `--enable_mcp`: Set to true to enable MCP server integration. If false, MCP servers won't be initialized or used, and the proxy will function as a basic proxy without additional actions.
* `--openai_api_base_url`: The base URL of your Llama CPP server.
* `--port`: The port on which the proxy server will run.
* `--mcp_config_path`: The full path to your MCP configuration JSON file.

---

## MCP Config JSON

A typical MCP configuration JSON file should resemble the following structure:

```json
{
    "mcpServers": {
        "hass-mcp": {
            "command": "docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "-e",
                "HA_URL",
                "-e",
                "HA_TOKEN",
                "voska/hass-mcp"
            ],
            "env": {
                "HA_URL": "[http://192.168.1.49:8123](http://192.168.1.49:8123)",
                "HA_TOKEN": "abcde"
            }
        },
        "airbnb": {
            "command": "npx",
            "args": [
                "-y",
                "@openbnb/mcp-server-airbnb",
                "--ignore-robots-txt"
            ]
        }
    }
}
```
---

## Limitations

This was a rapid weekend project, and as such, there are several areas for improvement:

1. Only the `/v1/chat/completions` endpoint is currently supported.
2. Only MCP tools are exposed to the LLM; no other tool types are supported.
3. Streaming support is not yet implemented.

---

## Contributions

Contributions are welcome! Feel free to open issues or submit pull requests.

---

## License

MIT