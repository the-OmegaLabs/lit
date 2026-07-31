"""Expose tools from remote MCP servers as Lit plugin functions."""

import asyncio
import inspect
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client


CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp.json"
DEFAULT_TIMEOUT_SECONDS = 30
ENVIRONMENT_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TOOL_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_]+")


class McpConfigurationError(ValueError):
    """Raised when mcp.json does not have the expected server definition."""


def _expand_environment(value: Any) -> Any:
    """Expand ${VARIABLE} values without silently dropping an absent secret."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in os.environ:
                raise McpConfigurationError(
                    f"Environment variable {variable!r} is required by mcp.json."
                )
            return os.environ[variable]

        return ENVIRONMENT_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value


def _normalise_name(value: str) -> str:
    name = TOOL_NAME_PATTERN.sub("_", value).strip("_")
    return name or "tool"


def _result_to_json(result: Any) -> Any:
    """Convert pydantic MCP result models into JSON-compatible data."""
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json", exclude_none=True)
    if hasattr(result, "dict"):
        return result.dict(exclude_none=True)
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return result
    return str(result)


class Plugin:
    """A config-driven bridge for remote Streamable HTTP and SSE MCP servers."""

    def __init__(self):
        self.name = "MCP servers"
        self.version = "v1.0"
        self.author = "Lit"
        self.export_function = {}

        for server_name, server_config in self._load_servers().items():
            if not server_config.get("enabled", True):
                continue
            try:
                self._register_server_tools(server_name, server_config)
            except Exception as error:
                print(f"MCP server {server_name!r} was skipped: {error}")

    def _load_servers(self) -> dict[str, dict[str, Any]]:
        if not CONFIG_PATH.exists():
            return {}

        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise McpConfigurationError(f"Invalid JSON in {CONFIG_PATH.name}: {error}") from error

        if not isinstance(raw, dict):
            raise McpConfigurationError(f"{CONFIG_PATH.name} must contain a JSON object.")

        servers = raw.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise McpConfigurationError("mcpServers must be an object keyed by server name.")

        validated = {}
        for name, config in servers.items():
            if not isinstance(name, str) or not name:
                raise McpConfigurationError("Each MCP server needs a non-empty string name.")
            if not isinstance(config, dict):
                raise McpConfigurationError(f"Configuration for MCP server {name!r} must be an object.")
            if not config.get("enabled", True):
                validated[name] = config
                continue
            if not isinstance(config.get("url"), str) or not config["url"]:
                raise McpConfigurationError(f"MCP server {name!r} requires a non-empty url.")
            validated[name] = _expand_environment(config)
        return validated

    @staticmethod
    def _server_options(config: dict[str, Any]) -> tuple[str, dict[str, str], float]:
        transport = str(config.get("transport", "streamable_http")).lower().replace("-", "_")
        if transport not in {"streamable_http", "sse"}:
            raise McpConfigurationError(
                "transport must be 'streamable_http' or 'sse'."
            )

        headers = config.get("headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise McpConfigurationError("headers must be an object with string keys and values.")

        timeout = config.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise McpConfigurationError("timeout must be a positive number of seconds.")

        return transport, headers, float(timeout)

    async def _with_session(self, config: dict[str, Any], operation):
        transport, headers, timeout = self._server_options(config)

        async def run_operation():
            if transport == "streamable_http":
                async with streamablehttp_client(
                    config["url"], headers=headers, timeout=timeout
                ) as streams:
                    read_stream, write_stream = streams[:2]
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        return await operation(session)

            async with sse_client(config["url"], headers=headers, timeout=timeout) as streams:
                read_stream, write_stream = streams[:2]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await operation(session)

        return await asyncio.wait_for(run_operation(), timeout=timeout)

    def _list_tools(self, config: dict[str, Any]):
        async def operation(session: ClientSession):
            return await session.list_tools()

        result = asyncio.run(self._with_session(config, operation))
        tools = getattr(result, "tools", None)
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list returned an invalid response.")
        return tools

    def _register_server_tools(self, server_name: str, config: dict[str, Any]) -> None:
        seen_names = set(self.export_function)
        for remote_tool in self._list_tools(config):
            remote_name = getattr(remote_tool, "name", None)
            input_schema = getattr(remote_tool, "inputSchema", None)
            if not isinstance(remote_name, str) or not remote_name:
                raise RuntimeError("MCP tools/list returned a tool without a valid name.")
            if not isinstance(input_schema, dict):
                raise RuntimeError(f"MCP tool {remote_name!r} did not include an input schema.")

            local_name = f"mcp_{_normalise_name(server_name)}_{_normalise_name(remote_name)}"
            suffix = 2
            base_name = local_name
            while local_name in seen_names:
                local_name = f"{base_name}_{suffix}"
                suffix += 1
            seen_names.add(local_name)

            description = getattr(remote_tool, "description", "") or ""
            function = self._make_tool_function(
                server_name, config, remote_name, local_name, description, input_schema
            )
            self.export_function[f"MCP {server_name}: {remote_name}"] = function

    def _make_tool_function(
        self,
        server_name: str,
        config: dict[str, Any],
        remote_name: str,
        local_name: str,
        description: str,
        input_schema: dict[str, Any],
    ):
        def call_mcp_tool(**arguments):
            return self._call_tool(config, remote_name, arguments)

        call_mcp_tool.__name__ = local_name
        call_mcp_tool.__qualname__ = local_name
        call_mcp_tool.__doc__ = (
            f"Call MCP server {server_name!r}, tool {remote_name!r}.\n\n{description}".strip()
        )
        call_mcp_tool.__lit_input_schema__ = input_schema
        call_mcp_tool.__signature__ = inspect.Signature()
        return call_mcp_tool

    def _call_tool(
        self, config: dict[str, Any], remote_name: str, arguments: dict[str, Any]
    ) -> Any:
        async def operation(session: ClientSession):
            return await session.call_tool(remote_name, arguments=arguments)

        return _result_to_json(asyncio.run(self._with_session(config, operation)))
