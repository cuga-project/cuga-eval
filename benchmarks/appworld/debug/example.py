# CRITICAL: Load environment variables FIRST, before ANY other imports
import sys
from pathlib import Path

# Add project root to path to import config_loader
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import and call config loader before anything else
from config_loader import load_eval_config

load_eval_config("appworld")

# Verify env vars are set before importing cuga modules
import os

cuga_logging_dir = os.getenv("CUGA_LOGGING_DIR")
if not cuga_logging_dir:
    raise RuntimeError("CUGA_LOGGING_DIR not set after load_eval_config! Check config files.")

# Now safe to import other modules
import asyncio
from typing import List

import httpx
from appworld import AppWorld
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.nodes.cuga_lite.providers.combined import CombinedToolProvider
from cuga.backend.cuga_graph.nodes.cuga_lite.cuga_lite_graph import make_tool_awaitable
from cuga.backend.cuga_graph.nodes.cuga_lite.executors import CodeExecutor
from cuga.backend.cuga_graph.state.agent_state import AgentState, VariablesManager
from loguru import logger

debug_dir = Path(__file__).parent
task_id = (debug_dir / "task_id.txt").read_text().strip()
experiment_name = "example_spotify_account"


def get_registry_base_url() -> str:
    """Get the base URL for the registry API."""
    return "http://localhost:8001"


async def call_authenticate_apps(apps: List[str]):
    """Authenticate apps with the registry."""
    payload = {"apps": apps}
    async with httpx.AsyncClient() as client:
        registry_base = get_registry_base_url()
        try:
            response = await client.post(
                f"{registry_base}/api/authenticate_apps",
                json=payload,
                timeout=10.0,
            )
            logger.info(f"Authenticate apps response status: {response.status_code}")
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"Authenticated apps: {result}")
                except Exception as e:
                    logger.warning(
                        f"Could not parse response JSON: {e}, response text: {response.text[:200]}"
                    )
            else:
                logger.warning(
                    f"Authentication returned status {response.status_code}: {response.text[:200]}"
                )
        except httpx.TimeoutException:
            logger.error(f"Timeout connecting to registry at {registry_base}/api/authenticate_apps")
        except Exception as e:
            logger.error(f"Error authenticating apps: {e}")


async def main():
    world = None
    try:
        with AppWorld(
            task_id=task_id,
            experiment_name=experiment_name,
            remote_environment_url="http://localhost:8000",
            remote_apis_url="http://localhost:9111",
        ) as world:
            logger.info(f"Initialized AppWorld with task: {task_id}")
            logger.info(f"Task instruction: {world.task.instruction}")
            import httpx
            from cuga.config import settings

            supervisor_url = f"http://localhost:{settings.server_ports.apis_url}/supervisor/profile"
            try:
                with httpx.Client(timeout=5.0) as client:
                    r = client.get(supervisor_url)
                    if r.status_code == 200:
                        logger.info("✅ Supervisor is available")
                        logger.info(f"Supervisor profile: {r.json()}")
                    else:
                        logger.warning(f"⚠️ Supervisor returned status {r.status_code}: {r.text}")
            except Exception as e:
                logger.error(f"❌ Could not reach supervisor at {supervisor_url}: {e}")
                logger.error("Make sure AppWorld API server is running: cuga start appworld")
                return

            ActivityTracker()
            # Get supervisor info from world.task.supervisor (same as appworld_eval.py:190)
            supervisor_info = world.task.supervisor
            supervisor_first_name = supervisor_info.get("first_name", "Test")
            supervisor_last_name = supervisor_info.get("last_name", "User")
            supervisor_email = supervisor_info.get("email", "test@example.com")
            supervisor_password = "TestPassword123"  # noqa: S105 — synthetic data for AppWorld debug

            # Get APIs URL from settings
            from cuga.config import settings

            apis_url = f"http://localhost:{settings.server_ports.apis_url}"

            state = AgentState(input="Example task", variables_manager=VariablesManager(), url=apis_url)

            tool_provider = CombinedToolProvider(app_names=["spotify", "gmail", "file_system"])
            await tool_provider.initialize()

            # Authenticate apps
            apps_to_authenticate = ["spotify", "gmail", "file_system"]
            await call_authenticate_apps(apps_to_authenticate)

            _locals = {}

            for app_name in ["spotify", "gmail", "file_system"]:
                tools = await tool_provider.get_tools(app_name)
                for tool in tools:
                    tool_func = tool.func if hasattr(tool, 'func') else tool._run
                    awaitable_tool_func = make_tool_awaitable(tool_func)
                    _locals[tool.name] = awaitable_tool_func
                    logger.info(f"Added tool: {tool.name}")

            code_template = (debug_dir / "code.txt").read_text()
            code = (
                code_template.replace("{supervisor_first_name}", supervisor_first_name)
                .replace("{supervisor_last_name}", supervisor_last_name)
                .replace("{supervisor_email}", supervisor_email)
                .replace("{supervisor_password}", supervisor_password)
            )

            output, new_vars = await CodeExecutor.eval_with_tools_async(
                code=code,
                _locals=_locals,
                state=state,
                apps_list=["spotify", "gmail", "file_system"],
                mode='local',
            )

            # Re-authenticate apps after login to refresh tokens in registry
            logger.info("Re-authenticating apps after login...")
            await call_authenticate_apps(["spotify", "gmail", "file_system"])

            is_error = False
            world.execute(
                "\n" + f"apis.supervisor.complete_task(status='{"success" if not is_error else "fail"}')"
            )
            evaluation = world.evaluate()
            try:
                world.close_all()
            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")

            if evaluation.success:
                logger.info("**Task succeeded**")
            else:
                logger.warning("**Task failed**")
                logger.warning(f"Pass percentage: {str(evaluation.pass_percentage)}")
            logger.info(f"Execution output: {output}")
            logger.info(f"New variables: {new_vars}")
    except (IndexError, Exception) as e:
        if isinstance(e, IndexError) and "pop from empty list" in str(e):
            logger.warning(f"Known AppWorld cleanup issue (IndexError in freezegun): {e}")
        else:
            logger.error(f"Error in main: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
