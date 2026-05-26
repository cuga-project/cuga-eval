"""
Direct MCP Client for Task 1 (stdio mode)
==========================================

This module provides a direct stdio connection to MCP servers, bypassing the registry.
It's based on the enterprise benchmark's approach for improved reliability.

Usage:
    async with create_direct_mcp_client(container_name, domain) as session:
        tools = await session.list_tools()
        result = await session.call_tool("get_data", {"tool_universe_id": uuid})
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass
class DirectMCPConfig:
    """Configuration for direct MCP connection."""

    container_name: str
    domain: str
    container_runtime: str = "podman"  # or "docker"
    container_command: Optional[List[str]] = None
    container_env: Optional[Dict[str, str]] = None

    def __post_init__(self):
        if self.container_command is None:
            # Default command for Task 1 MCP server
            self.container_command = ["python", "-m", "apis.m3.python_tools.mcp.cli"]


def detect_container_runtime() -> str:
    """Auto-detect available container runtime (podman or docker)."""
    import shutil

    # Check for podman first (preferred on some systems)
    if shutil.which("podman"):
        return "podman"
    elif shutil.which("docker"):
        return "docker"
    else:
        raise RuntimeError("No container runtime found. Please install podman or docker.")


def assert_container_running(runtime: str, container_name: str) -> None:
    """Verify that the specified container is running."""
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603 — runtime is a fixed enum (docker/podman), no shell
            [runtime, "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        running_containers = result.stdout.strip().split("\n")
        if container_name not in running_containers:
            raise RuntimeError(
                f"Container '{container_name}' is not running. "
                f"Start it with: {runtime} start {container_name}"
            )
        logger.info(f"✅ Container '{container_name}' is running")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to check container status: {e.stderr}") from e


@contextlib.asynccontextmanager
async def create_direct_mcp_client(
    config: DirectMCPConfig,
) -> AsyncGenerator[ClientSession, None]:
    """
    Create a direct stdio connection to an MCP server running in a container.

    This bypasses the registry and connects directly to the container,
    similar to the enterprise benchmark approach.

    Args:
        config: DirectMCPConfig with container and domain settings

    Yields:
        ClientSession: Initialized MCP client session

    Example:
        config = DirectMCPConfig(
            container_name="task_1_m3_environ",
            domain="movie",
            container_runtime="podman"
        )
        async with create_direct_mcp_client(config) as session:
            tools = await session.list_tools()
            result = await session.call_tool("get_data", {"tool_universe_id": uuid})
    """
    # Auto-detect runtime if not specified
    runtime = config.container_runtime
    if not runtime:
        runtime = detect_container_runtime()
        logger.info(f"Auto-detected container runtime: {runtime}")

    # Verify container is running
    assert_container_running(runtime, config.container_name)

    # Build environment variables for container exec
    exec_env = {"MCP_DOMAIN": config.domain}
    if config.container_env:
        exec_env.update(config.container_env)

    # Build docker/podman exec command
    env_args = []
    for k, v in exec_env.items():
        env_args += ["-e", f"{k}={v}"]

    # Ensure container_command is not None (should be set in __post_init__)
    container_cmd = config.container_command or ["python", "-m", "apis.m3.python_tools.mcp.cli"]
    full_args = ["exec", "-i"] + env_args + [config.container_name] + container_cmd

    logger.info(f"🚀 Starting direct MCP connection: {runtime} {' '.join(full_args)}")

    # Create stdio server parameters
    server_params = StdioServerParameters(
        command=runtime,
        args=full_args,
        env=None,  # Environment is passed via -e flags to docker/podman exec
    )

    try:
        # Establish stdio connection
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the MCP session
                await session.initialize()
                logger.info(f"✅ Direct MCP session initialized for domain '{config.domain}'")

                # Yield the session for use
                yield session

                logger.info(f"🔌 Closing direct MCP session for domain '{config.domain}'")

    except FileNotFoundError as e:
        raise RuntimeError(
            f"Container runtime not found: {runtime!r}. "
            "Ensure podman or docker is installed and available in PATH."
        ) from e
    except Exception as e:
        logger.error(f"❌ Failed to connect to MCP server: {e}")
        raise RuntimeError(
            f"Failed to establish direct MCP connection to container '{config.container_name}': {e}"
        ) from e


async def get_tools_from_direct_session(session: ClientSession) -> List:
    """
    Get list of available tools from an MCP session.

    Args:
        session: Active ClientSession

    Returns:
        List of Tool objects from MCP
    """
    try:
        tools_result = await session.list_tools()
        tools = tools_result.tools if hasattr(tools_result, 'tools') else []
        logger.info(f"📋 Retrieved {len(tools)} tools from MCP server")
        return tools
    except Exception as e:
        logger.error(f"❌ Failed to list tools: {e}")
        raise


async def call_tool_direct(
    session: ClientSession,
    tool_name: str,
    arguments: Dict,
) -> Dict:
    """
    Call a tool via direct MCP session.

    Args:
        session: Active ClientSession
        tool_name: Name of the tool to call
        arguments: Tool arguments

    Returns:
        Tool result as dictionary
    """
    try:
        import json

        from mcp.types import TextContent

        logger.debug(f"🔧 Calling tool: {tool_name} with args: {arguments}")
        result = await session.call_tool(tool_name, arguments)

        # Extract content from result - following enterprise benchmark pattern
        if hasattr(result, 'content') and result.content:
            content = result.content[0]
            # Type narrow to TextContent (most common case)
            if isinstance(content, TextContent):
                return json.loads(content.text)
            # Fallback: try to access text attribute directly
            elif hasattr(content, 'text'):
                text_val = getattr(content, 'text', '')
                return json.loads(str(text_val))

        return {"error": "No content in tool result"}

    except Exception as e:
        logger.error(f"❌ Tool call failed: {tool_name} - {e}")
        return {"error": str(e)}


# Example usage
if __name__ == "__main__":

    async def test_direct_connection():
        """Test direct MCP connection."""
        config = DirectMCPConfig(
            container_name="task_1_m3_environ",
            domain="movie",
            container_runtime="podman",
        )

        async with create_direct_mcp_client(config) as session:
            # List tools
            tools = await get_tools_from_direct_session(session)
            tool_names = [t.name for t in tools] if tools else []
            print(f"Available tools: {tool_names}")

            # Test get_data
            result = await call_tool_direct(
                session, "get_data", {"tool_universe_id": "8a6ba32c9bed-3f22227dee2c"}
            )
            print(f"get_data result keys: {list(result.keys())}")

    # Run test
    asyncio.run(test_direct_connection())

# Made with Bob
