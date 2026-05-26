"""
M3 Task 1 Evaluation - Enterprise Benchmark Style
==================================================

This script mimics the enterprise-benchmark's approach for Task 1 evaluation:
- Persistent stdio connection per domain (not registry-based)
- Explicit get_data() call BEFORE each query
- Single agent instance reused per domain
- No query augmentation (clean queries)

Key Differences from eval_m3_task_1_support.py:
1. Direct stdio connection to MCP server (bypasses registry)
2. Pre-loads universe with explicit get_data() call
3. Reuses agent across all queries in a domain
4. More efficient and reliable for Task 1

Usage:
    # Single domain
    python benchmarks/m3/eval_m3_task_1_enterprise_style.py --domain movie --max-samples 5

    # Multiple domains
    python benchmarks/m3/eval_m3_task_1_enterprise_style.py --domain movie --domain hockey

    # All domains
    python benchmarks/m3/eval_m3_task_1_enterprise_style.py

    # Custom container
    python benchmarks/m3/eval_m3_task_1_enterprise_style.py --container task_1_m3_environ --runtime podman
"""

# CRITICAL: Load environment variables FIRST
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from config_loader import load_eval_config

load_eval_config("m3")

import argparse
import asyncio
import json
import os
import time
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.state.agent_state import VariablesManager

# Import CUGA modules
from cuga.sdk import CugaAgent
from langchain_core.messages import HumanMessage
from loguru import logger

# Import helpers
from benchmarks.helpers import (
    create_activity_tracker_callback,
    print_evaluation_summary,
    save_evaluation_results,
    setup_langfuse,
)

# Import MCP client utilities
from benchmarks.m3.direct_mcp_client import (
    DirectMCPConfig,
    create_direct_mcp_client,
    detect_container_runtime,
)

tracker = ActivityTracker()
var_manager = VariablesManager()


async def wrap_tool_with_tracking(tool, app_name: str = "mcp_server"):
    """
    Wrap a tool to enable ToolCallTracker recording.

    This ensures tool calls are tracked when track_tool_calls=True is passed to agent.invoke().
    """
    import time

    from cuga.backend.cuga_graph.nodes.cuga_lite.tool_call_tracker import ToolCallTracker

    # Store original function
    original_func = tool.coroutine if hasattr(tool, 'coroutine') and tool.coroutine else tool.func
    if not original_func:
        logger.warning(f"Tool {tool.name} has no callable function to wrap")
        return tool

    # Get operation_id (use tool name as operation_id for MCP tools)
    operation_id = tool.name

    # Create wrapped function
    async def tracked_func(**kwargs):
        start_time = time.time()
        result = None
        error_msg = None

        try:
            # Call original function
            if asyncio.iscoroutinefunction(original_func):
                result = await original_func(**kwargs)
            else:
                result = original_func(**kwargs)
            return result
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in tool {tool.name}: {error_msg}")
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # Record the tool call
            ToolCallTracker.record_call(
                tool_name=tool.name,
                arguments=kwargs,
                result=result,
                app_name=app_name,
                operation_id=operation_id,
                duration_ms=duration_ms,
                error=error_msg,
            )

    # Replace the tool's function with the tracked version
    tool.coroutine = tracked_func
    tool.func = lambda **kw: asyncio.run(tracked_func(**kw))  # Sync wrapper

    return tool


async def get_tools_from_session(session) -> List:
    """Extract LangChain-compatible tools from MCP session."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    # List available tools from MCP server
    tools_response = await session.list_tools()
    mcp_tools = tools_response.tools if hasattr(tools_response, 'tools') else []

    logger.info(f"Found {len(mcp_tools)} tools from MCP server")

    # Convert MCP tools to LangChain tools
    langchain_tools = []
    for mcp_tool in mcp_tools:
        tool_name = mcp_tool.name
        tool_description = mcp_tool.description or f"Tool: {tool_name}"

        # Create dynamic Pydantic model for tool input
        input_schema = mcp_tool.inputSchema if hasattr(mcp_tool, 'inputSchema') else {}
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])

        # Build field definitions with proper annotations
        fields = {}
        annotations = {}
        for prop_name, prop_info in properties.items():
            field_type = str  # Default to string
            field_description = prop_info.get("description", "")
            is_required = prop_name in required

            # Add type annotation
            if is_required:
                annotations[prop_name] = field_type
                fields[prop_name] = Field(..., description=field_description)
            else:
                annotations[prop_name] = Optional[field_type]
                fields[prop_name] = Field(None, description=field_description)

        # Add __annotations__ to fields dict
        fields['__annotations__'] = annotations

        # Create dynamic model
        InputModel = type(f"{tool_name}_Input", (BaseModel,), fields)

        # Create async function that calls MCP tool
        async def tool_func(**kwargs):
            """Call MCP tool via session."""
            nonlocal session, tool_name
            result = await session.call_tool(tool_name, kwargs)

            # Extract content from MCP response
            if hasattr(result, 'content') and result.content:
                content_items = result.content
                if isinstance(content_items, list) and content_items:
                    first_item = content_items[0]
                    if hasattr(first_item, 'text'):
                        return first_item.text
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        return first_item['text']
                return str(content_items)
            return str(result)

        # Create LangChain StructuredTool
        lc_tool = StructuredTool(
            name=tool_name,
            description=tool_description,
            func=lambda **kw: asyncio.run(tool_func(**kw)),  # Sync wrapper
            coroutine=tool_func,  # Async version
            args_schema=InputModel,
        )

        # Wrap tool with tracking
        tracked_tool = await wrap_tool_with_tracking(lc_tool, app_name="mcp_server")
        langchain_tools.append(tracked_tool)

    return langchain_tools


async def run_benchmark_for_domain_with_retry(
    domain: str,
    items: List[Dict[str, Any]],
    config: DirectMCPConfig,
    max_samples: Optional[int] = None,
    agent_timeout: int = 300,
    max_retries: int = 3,
) -> List[Dict[str, Any]]:
    """Run benchmark with automatic reconnection on connection failures."""
    all_results = []
    remaining_items = items[:max_samples] if max_samples else items
    retry_count = 0

    while remaining_items and retry_count < max_retries:
        if retry_count > 0:
            logger.warning(f"\n🔄 Reconnection attempt {retry_count}/{max_retries}")
            logger.info(f"   Resuming with {len(remaining_items)} remaining queries")
            await asyncio.sleep(2)

        batch_results = await run_benchmark_for_domain_single_connection(
            domain=domain,
            items=remaining_items,
            config=config,
            max_samples=None,
            agent_timeout=agent_timeout,
        )

        all_results.extend(batch_results)  # Append results from this batch

        if len(batch_results) >= len(remaining_items):
            break  # All items completed

        # Prepare retry with remaining items
        completed_count = len(batch_results)
        remaining_items = remaining_items[completed_count:]
        retry_count += 1

    if remaining_items and retry_count >= max_retries:
        logger.error(f"❌ Max retries reached. {len(remaining_items)} queries not completed.")

    return all_results


async def run_benchmark_for_domain_single_connection(
    domain: str,
    items: List[Dict[str, Any]],
    config: DirectMCPConfig,
    max_samples: Optional[int] = None,
    agent_timeout: int = 300,
) -> List[Dict[str, Any]]:
    """
    Run benchmark for a single domain using persistent stdio connection.

    This mimics enterprise-benchmark's approach:
    1. Opens ONE persistent stdio connection for the entire domain
    2. Creates ONE agent instance for all queries
    3. Explicitly calls get_data() before each query
    4. Reuses the connection and agent for efficiency

    Args:
        domain: Domain name (e.g., "movie", "hockey")
        items: List of benchmark items for this domain
        config: DirectMCPConfig for MCP connection
        max_samples: Maximum number of samples to process
        agent_timeout: Timeout in seconds for each agent invocation

    Returns:
        List of result dictionaries
    """
    # Limit samples if requested
    if max_samples and max_samples < len(items):
        items = items[:max_samples]

    logger.info(f"\n{'#' * 60}")
    logger.info(f"# DOMAIN: {domain} ({len(items)} items)")
    logger.info(f"{'#' * 60}")

    results = []

    try:
        # Use AsyncExitStack to maintain persistent connection
        async with AsyncExitStack() as stack:
            # Create persistent MCP session for this domain
            logger.info(f"🔧 Establishing persistent MCP connection for domain '{domain}'")
            session = await stack.enter_async_context(create_direct_mcp_client(config))

            # Get tools from session
            tools = await get_tools_from_session(session)
            logger.info(f"✅ Loaded {len(tools)} tools for domain '{domain}'")

            # Find get_data tool (required for universe switching)
            get_data_tool = next((t for t in tools if t.name == "get_data"), None)
            if not get_data_tool:
                logger.error(f"❌ 'get_data' tool not found for domain '{domain}'")
                raise RuntimeError(f"get_data tool required for Task 1 but not found in domain '{domain}'")

            logger.info("✅ Found 'get_data' tool for universe switching")

            # Create single agent instance for this domain (reused for all queries)
            logger.info(f"🤖 Creating agent instance for domain '{domain}'")
            langfuse_handler = setup_langfuse()

            # Create a DirectLangChainToolsProvider to wrap our tools
            # This ensures tool call tracking works properly
            from cuga.backend.cuga_graph.nodes.cuga_lite.direct_langchain_tools_provider import (
                DirectLangChainToolsProvider,
            )

            tool_provider = DirectLangChainToolsProvider(tools)

            # Create agent with tool_provider (not raw tools)
            # Note: Code executor timeout is hardcoded at 30s in CUGA
            # For slow queries, consider increasing container resources or using --max-samples
            if langfuse_handler:
                agent = CugaAgent(
                    tool_provider=tool_provider,
                    callbacks=[langfuse_handler],
                )
            else:
                agent = CugaAgent(tool_provider=tool_provider)
            logger.info(f"✅ Agent created with {len(tools)} tools via DirectLangChainToolsProvider")
            logger.warning("⚠️  Code executor timeout is 30s (hardcoded in CUGA). Slow queries may timeout.")

            # Start experiment tracking
            experiment_name = os.getenv("M3_EXPERIMENT_NAME", "m3_task1_enterprise_style")
            item_uuids = [item["uuid"] for item in items]
            tracker.start_experiment(
                task_ids=item_uuids,
                experiment_name=experiment_name,
                description=f"M3 Task 1 (enterprise-style) - domain: {domain}",
            )

            # Process each query
            for i, item in enumerate(items, 1):
                uuid = item["uuid"]
                query = item["query"]
                turn_id = item.get("turn_id", 0)

                logger.info(f"\n  [{i}/{len(items)}] uuid={uuid}")
                logger.info(f"  Query: {query[:80]}{'...' if len(query) > 80 else ''}")

                # Reset tracking for this item
                tracker.reset(intent=query, task_id=uuid)
                var_manager.reset()
                create_activity_tracker_callback(tracker, var_manager)

                result = {
                    "uuid": uuid,
                    "domain": domain,
                    "intent": query,
                    "turn_id": turn_id,
                    "m3_task_id": 1,
                    "status": "pending",
                    "response": "",
                    "tool_calls": [],
                    "error": "",
                    "duration_s": 0.0,
                }

                start_time = time.perf_counter()

                try:
                    # STEP 1: Explicitly call get_data to switch universe
                    logger.info(f"  🔄 Switching to universe: {uuid}")
                    data_result = await get_data_tool.ainvoke({"tool_universe_id": uuid})

                    # Parse the result
                    parsed_data = json.loads(data_result)

                    # Handle MCP TextContent format
                    if isinstance(parsed_data, list) and parsed_data:
                        first_item = parsed_data[0]
                        if isinstance(first_item, dict) and "text" in first_item:
                            parsed_data = json.loads(first_item["text"])
                        else:
                            parsed_data = first_item

                    # Check for errors in universe loading
                    if isinstance(parsed_data, dict) and "error" in parsed_data:
                        raise RuntimeError(f"Universe switch failed: {parsed_data['error']}")

                    logger.info("  ✅ Universe loaded successfully")

                    # STEP 2: Run agent with clean query (no augmentation)
                    logger.info("  🤖 Running agent...")
                    invoke_result = await asyncio.wait_for(
                        agent.invoke(
                            [HumanMessage(content=query)],
                            thread_id=f"task1_{uuid}",
                            user_context="",
                            track_tool_calls=True,
                        ),
                        timeout=agent_timeout,
                    )

                    # Extract response and tool calls
                    response = (
                        invoke_result.answer if hasattr(invoke_result, 'answer') else str(invoke_result)
                    )
                    tool_calls = invoke_result.tool_calls if hasattr(invoke_result, 'tool_calls') else []

                    # Ensure response is a string
                    if not isinstance(response, str):
                        response = str(response)

                    # Check for tool call errors
                    has_errors = False
                    if tool_calls:
                        for tc in tool_calls:
                            if isinstance(tc, dict):
                                args = tc.get("arguments", {})
                                if isinstance(args, dict):
                                    data = args.get("data", {})
                                    if isinstance(data, dict) and "error" in data:
                                        error_msg = data["error"]
                                        if "HTTP Error" in error_msg or "500" in error_msg:
                                            has_errors = True
                                            logger.warning(f"  ⚠️  Tool call error: {error_msg}")
                                            break

                    # Update result
                    success = not has_errors
                    result.update(
                        {
                            "status": "success" if success else "error",
                            "response": response,
                            "tool_calls": tool_calls,
                            "success": success,
                            "match_rate": 1.0 if success else 0.0,
                            "passed": success,
                        }
                    )

                    elapsed = time.perf_counter() - start_time
                    logger.info(
                        f"  ✅ Status: {'success' if success else 'error'} | "
                        f"Tools: {len(tool_calls)} | Time: {elapsed:.2f}s"
                    )

                    # Log answer preview
                    answer_preview = response[:200] if response else "(empty)"
                    ans_suffix = "..." if len(response) > 200 else ""
                    logger.info(f"  Answer: {answer_preview}{ans_suffix}")

                except asyncio.TimeoutError:
                    result["status"] = "error"
                    result["error"] = f"Agent timed out after {agent_timeout} seconds"
                    result["success"] = False
                    result["match_rate"] = 0.0
                    result["passed"] = False
                    logger.error(f"  ❌ Timeout after {agent_timeout}s")

                except Exception as e:
                    # Check if this is a connection closed error
                    import anyio

                    if isinstance(e, anyio.ClosedResourceError):
                        logger.error(f"  ❌ MCP connection closed at query {i}/{len(items)}")
                        logger.warning(f"  ⚠️  Saving {len(results)} results collected so far")
                        result["status"] = "error"
                        result["error"] = "MCP connection closed"
                        result["success"] = False
                        result["match_rate"] = 0.0
                        result["passed"] = False
                        result["duration_s"] = time.perf_counter() - start_time
                        results.append(result)
                        break  # Exit the loop, connection is dead

                    # Handle other exceptions normally
                    result["status"] = "error"
                    result["error"] = str(e)
                    result["success"] = False
                    result["match_rate"] = 0.0
                    result["passed"] = False
                    logger.error(f"  ❌ Error: {str(e)[:100]}")
                    import traceback

                    logger.debug(traceback.format_exc())

                result["duration_s"] = time.perf_counter() - start_time
                results.append(result)

                # Delay between queries to reduce memory pressure
                if i < len(items):
                    await asyncio.sleep(1.0)  # 1 second delay to allow garbage collection

        logger.info(f"\n✅ Domain '{domain}' completed: {len(results)} results")

    except Exception as e:
        logger.error(f"❌ Domain '{domain}' failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        raise

    return results


def save_ground_truth_format(results: List[Dict], output_dir: Path) -> Path:
    """Save results in ground truth format for M3 benchmark.

    Output structure:
        <output_dir>/<experiment_timestamp>/task_1/<domain>.json

    Each domain file contains a list of ground truth entries for that domain.

    Args:
        results: List of evaluation results
        output_dir: Base output directory path

    Returns:
        Path to the experiment directory that was created
    """
    import hashlib
    from datetime import datetime

    timestamp = datetime.now().strftime("%b_%d_%I_%M%p").lower()

    # Root experiment folder: results/<timestamp>/
    experiment_dir = output_dir / timestamp
    experiment_dir.mkdir(parents=True, exist_ok=True)

    # Group results by domain
    from collections import defaultdict

    grouped: dict = defaultdict(list)
    for result in results:
        domain = result.get("domain", "unknown")
        grouped[domain].append(result)

    saved_files = []

    for domain, domain_results in grouped.items():
        # Create task subfolder: task_1/
        task_dir = experiment_dir / "task_1"
        task_dir.mkdir(parents=True, exist_ok=True)

        domain_entries = []

        for result in domain_results:
            task_name = result.get("task_name") or result.get("sample_id", "unknown")

            # Use UUID from result if present, otherwise generate deterministic one
            if "uuid" in result:
                formatted_uuid = result["uuid"]
            else:
                # Fallback: Deterministic UUID based on task_name + domain
                uuid_seed = f"{task_name}_{domain}"
                uuid_hash = hashlib.md5(uuid_seed.encode(), usedforsecurity=False).hexdigest()
                formatted_uuid = f"{uuid_hash[:12]}-{uuid_hash[12:24]}"

            # Extract data
            intent = result.get("intent", "")
            response = result.get("response", "")
            tool_calls_data = result.get("tool_calls", [])
            entry_error = result.get("error", "")
            entry_duration = result.get("duration_s", 0.0)

            # Check if tool calls contain errors
            def has_tool_call_errors(tool_calls):
                """Check if any tool call results contain errors."""
                if not tool_calls:
                    return False
                for tc in tool_calls:
                    # Check if tool call result contains error
                    result_data = tc.get("result", [])
                    if isinstance(result_data, list):
                        for item in result_data:
                            if isinstance(item, dict) and "error" in item:
                                error_msg = item["error"]
                                if (
                                    "HTTP Error" in error_msg
                                    or "500" in error_msg
                                    or "Internal Server Error" in error_msg
                                ):
                                    return True
                return False

            tool_call_has_errors = has_tool_call_errors(tool_calls_data)

            # Success only if: has tool calls AND no explicit error AND no tool call errors
            _has_tool_calls = bool(tool_calls_data)
            is_success = _has_tool_calls and not entry_error and not tool_call_has_errors
            entry_status = "success" if is_success else "error"

            # Update error message if tool calls had errors
            if tool_call_has_errors and not entry_error:
                entry_error = "Tool call returned error (HTTP 500 or Internal Server Error)"

            # Build sequence from tool calls
            def build_sequence(raw_tool_calls):
                """Build sequence dict from tool calls."""
                if not raw_tool_calls:
                    return None
                calls = []
                for tc in raw_tool_calls:
                    call = {
                        "name": tc.get("name", "unknown"),
                        "arguments": tc.get("arguments", {}),
                    }
                    calls.append(call)
                return {"tool_call": calls}

            turn_entry = {
                "turn_id": 0,
                "query": intent,
                "answer": response,
            }
            seq = build_sequence(tool_calls_data)
            if seq is not None:
                turn_entry["sequence"] = seq

            entry = {
                "uuid": formatted_uuid,
                "domain": domain,
                "status": entry_status,
                "error": entry_error,
                "duration_s": entry_duration,
                "output": [turn_entry],
            }

            domain_entries.append(entry)

        # Write one file per domain: task_1/<domain>.json
        domain_file = task_dir / f"{domain}.json"
        with open(domain_file, "w") as f:
            json.dump(domain_entries, f, indent=4)
        saved_files.append(domain_file)
        logger.info(f"  📄 {domain_file} ({len(domain_entries)} entries)")

    logger.info(f"📁 Ground truth saved to: {experiment_dir}  ({len(saved_files)} domain files)")
    return experiment_dir


async def main():
    parser = argparse.ArgumentParser(description="M3 Task 1 Evaluation (Enterprise Benchmark Style)")
    parser.add_argument(
        "--domain",
        type=str,
        action="append",
        default=None,
        help="Domain(s) to evaluate (can specify multiple times, default: all)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples per domain (default: all)",
    )
    parser.add_argument(
        "--container",
        type=str,
        default="task_1_m3_environ",
        help="Container name (default: task_1_m3_environ)",
    )
    parser.add_argument(
        "--runtime",
        type=str,
        choices=["docker", "podman"],
        default=None,
        help="Container runtime (default: auto-detect)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: benchmarks/m3/results_enterprise_style/)",
    )
    parser.add_argument(
        "--agent-timeout",
        type=int,
        default=300,
        help="Agent timeout in seconds (default: 300)",
    )

    args = parser.parse_args()

    # Auto-detect runtime if not specified
    runtime = args.runtime or detect_container_runtime()
    logger.info(f"Using container runtime: {runtime}")

    # Determine data directory
    data_dir = os.getenv("M3_DATA_DIR")
    if data_dir is None:
        data_dir = Path(__file__).parent / "data"
    else:
        data_dir = Path(data_dir)

    # Get list of domains
    if args.domain:
        domains = args.domain
    else:
        # Load all available domains
        json_files = sorted(data_dir.glob("*.json"))
        domains = [f.stem for f in json_files if not f.stem.endswith("_multiturn")]

    logger.info(f"Processing {len(domains)} domain(s): {domains}")

    # Process each domain
    all_results = []
    for domain in domains:
        # Load domain data
        data_path = data_dir / f"{domain}.json"
        if not data_path.exists():
            logger.warning(f"Data file not found: {data_path}, skipping domain '{domain}'")
            continue

        with open(data_path, "r") as f:
            raw_items = json.load(f)

        # Parse items
        items = []
        for item_data in raw_items:
            dialogue = item_data.get("dialogue", {})
            turns = dialogue.get("turns", [])
            query = turns[0]["query"] if turns else ""
            turn_id = turns[0].get("turn_id", 0) if turns else 0
            items.append(
                {
                    "uuid": item_data.get("uuid", ""),
                    "domain": item_data.get("domain", domain),
                    "query": query,
                    "turn_id": turn_id,
                }
            )

        logger.info(f"\nLoaded {len(items)} items for domain '{domain}'")

        # Create MCP config for this domain
        config = DirectMCPConfig(
            container_name=args.container,
            domain=domain,
            container_runtime=runtime,
            container_command=["python", "/app/mcp_dispatch.py"],
            container_env={"CAPABILITY_ID": "1"},
        )

        # Run benchmark for this domain
        domain_results = await run_benchmark_for_domain_with_retry(
            domain=domain,
            items=items,
            config=config,
            max_samples=args.max_samples,
            agent_timeout=args.agent_timeout,
        )

        all_results.extend(domain_results)

        # Save results after each domain (incremental save)
        if domain_results:
            output_dir = Path(args.output) if args.output else Path(__file__).parent / "results"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save cumulative results so far
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            incremental_path = output_dir / f"m3_task1_enterprise_incremental_{timestamp}.json"

            with open(incremental_path, "w") as f:
                json.dump(all_results, f, indent=2)

            logger.info(f"💾 Incremental save: {len(all_results)} results saved to {incremental_path}")

            # Also save ground truth format incrementally
            try:
                ground_truth_dir = save_ground_truth_format(all_results, output_dir)
                logger.info(f"💾 Ground truth incremental save: {ground_truth_dir}")
            except Exception as e:
                logger.warning(f"⚠️  Ground truth incremental save failed: {e}")

    # Print summary
    if all_results:
        logger.info(f"\n{'=' * 60}")
        logger.info("OVERALL SUMMARY")
        logger.info(f"{'=' * 60}\n")
        print_evaluation_summary(all_results)

        # Save results
        output_dir = Path(args.output) if args.output else Path(__file__).parent / "results"
        saved_path = save_evaluation_results(all_results, output_dir, prefix="m3_task1_enterprise")
        logger.info(f"\n✅ Results saved to: {saved_path}")

        # Save ground truth format
        logger.info(f"\n{'=' * 60}")
        logger.info("SAVING GROUND TRUTH FORMAT")
        logger.info(f"{'=' * 60}\n")
        ground_truth_dir = save_ground_truth_format(all_results, output_dir)
        logger.info(f"\n✅ Ground truth format saved to: {ground_truth_dir}")
    else:
        logger.warning("No results to display")


if __name__ == "__main__":
    asyncio.run(main())

# Made with Bob
