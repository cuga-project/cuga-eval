# TokenUsageTracker Implementation for SDK Mode

## Overview

This implementation addresses issues [#37](https://github.ibm.com/research-rpa/cuga-internal-evaluation/issues/37) and [cuga-agent#71](https://github.com/cuga-project/cuga-agent/issues/71) by adding TokenUsageTracker-like functionality to SDK mode (CugaAgent) evaluations.

## Problem Statement

Previously, benchmarks invoked CUGA in two different ways with inconsistent trajectory outputs:

- **SDK mode** (BPO, M3, Oak): Used `CugaAgent` with minimal trajectory data
- **AgentRunner mode** (AppWorld): Used full agent loop with rich trajectory data including all LLM prompts

This inconsistency made cross-benchmark trajectory analysis and visualization unreliable.

## Solution

Created a LangChain callback handler (`SDKTokenUsageTrackerCallback`) that mimics the behavior of `TokenUsageTracker` from cuga-agent's `agent_loop.py`. This callback:

1. Captures system and user prompts when LLM calls start (`on_llm_start`)
2. Captures assistant responses when LLM calls complete (`on_llm_end`)
3. Forwards all captured data to `ActivityTracker` via `collect_prompt()`

## Files Changed

### New Files

1. **`benchmarks/helpers/token_usage_tracker_callback.py`**
   - New module containing `SDKTokenUsageTrackerCallback` class
   - Factory function `create_token_usage_tracker_callback(tracker)`
   - Implements LangChain `AsyncCallbackHandler` interface

### Modified Files

1. **`benchmarks/helpers/sdk_eval_helpers.py`**
   - Updated `setup_agent_with_tools()` to automatically add TokenUsageTracker callback
   - New parameter: `enable_token_usage_tracker` (default: True)
   - Automatically enabled for all benchmarks using this helper

2. **`benchmarks/m3/eval_m3.py`**
   - Added TokenUsageTracker callback to CugaAgent creation (line ~1392)
   - Uses global ActivityTracker singleton

3. **`benchmarks/m3/eval_m3_task_1_enterprise_style.py`**
   - Added TokenUsageTracker callback to CugaAgent creation (line ~320)
   - Uses existing tracker instance

## Affected Benchmarks

All four benchmarks now have TokenUsageTracker support:

### ✅ Automatically Enabled (via `setup_agent_with_tools`)

1. **BPO** (`benchmarks/bpo/eval_bench_sdk.py`)
   - Uses `setup_agent_with_tools()` → automatically gets callback

2. **M3 Multi-turn** (`benchmarks/m3/eval_m3_multiturn.py`)
   - Uses `setup_agent_with_tools()` → automatically gets callback

3. **Oak Health Insurance** (`benchmarks/oak_health_insurance/eval_bench_sdk.py`)
   - Uses `setup_agent_with_tools()` → automatically gets callback

4. **AppWorld SDK** (`benchmarks/appworld/eval_appworld_sdk.py`)
   - Uses `setup_agent_with_tools()` → automatically gets callback

### ✅ Manually Added

5. **M3 Single-turn** (`benchmarks/m3/eval_m3.py`)
   - Manually added callback during CugaAgent creation

6. **M3 Task 1 Enterprise** (`benchmarks/m3/eval_m3_task_1_enterprise_style.py`)
   - Manually added callback during CugaAgent creation

## Usage

### For New Benchmarks

If using `setup_agent_with_tools()`, TokenUsageTracker is automatically enabled:

```python
from benchmarks.helpers import setup_agent_with_tools

# Automatically includes TokenUsageTracker callback
agent, langfuse_handler = await setup_agent_with_tools()
```

To disable (not recommended):

```python
agent, langfuse_handler = await setup_agent_with_tools(
    enable_token_usage_tracker=False
)
```

### For Direct CugaAgent Creation

If creating CugaAgent directly, add the callback manually:

```python
from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.sdk import CugaAgent
from benchmarks.helpers.token_usage_tracker_callback import create_token_usage_tracker_callback

tracker = ActivityTracker()  # Singleton
callbacks = [langfuse_handler] if langfuse_handler else []

# Add TokenUsageTracker callback
try:
    token_tracker_callback = create_token_usage_tracker_callback(tracker)
    callbacks.append(token_tracker_callback)
    logger.info("✅ TokenUsageTracker callback enabled")
except Exception as e:
    logger.warning(f"Failed to enable TokenUsageTracker callback: {e}")

agent = CugaAgent(
    tool_provider=tool_provider,
    callbacks=callbacks,
)
```

## Expected Impact

### Before

SDK mode trajectories had:
- Empty `prompts` fields on most steps (except manually added UserPrompt)
- Minimal step granularity (5 steps: Raw_Assistant_Response, Assistant_nl, FinalAnswerAgent, UserPrompt, EvaluationResult)
- Token tracking via Langfuse only

### After

SDK mode trajectories now have:
- **Full LLM conversation history** in `prompts` fields
- System prompts, user prompts, and assistant responses captured for every LLM call
- Same prompt richness as AgentRunner mode
- Compatible with cuga-viz and other trajectory analysis tools

### Trajectory File Structure

Each step in the trajectory now includes:

```json
{
  "name": "UserPrompt",
  "data": "...",
  "prompts": [
    {
      "role": "system",
      "value": "You are a helpful assistant..."
    },
    {
      "role": "user",
      "value": "What is the weather today?"
    },
    {
      "role": "assistant",
      "value": "I'll check the weather for you..."
    }
  ]
}
```

## Testing

To verify the implementation:

1. Run any SDK-mode evaluation:
   ```bash
   ./benchmarks/bpo/eval.sh --task 1
   ```

2. Check the trajectory file in `benchmarks/bpo/logging/trajectory_data/`

3. Verify that steps now include `prompts` arrays with system/user/assistant messages

4. Compare with previous trajectories to see the enrichment

## Limitations

This is a **workaround** until the upstream fix in cuga-agent#71 is implemented. The callback approach:

- ✅ Captures all LLM prompts and responses
- ✅ Works with existing SDK code without breaking changes
- ✅ Compatible with all benchmarks
- ⚠️ Does not provide the same step-by-step granularity as AgentRunner (5 steps vs 50+ steps)
- ⚠️ Requires manual addition for direct CugaAgent instantiations

## Future Work

Once [cuga-agent#71](https://github.com/cuga-project/cuga-agent/issues/71) is implemented:

1. Remove this workaround callback
2. Update to use native TokenUsageTracker from cuga-agent
3. Achieve full parity between SDK and AgentRunner modes

## Related Issues

- [cuga-internal-evaluation#37](https://github.ibm.com/research-rpa/cuga-internal-evaluation/issues/37) - Standardize CUGA invocation mode across benchmarks
- [cuga-agent#71](https://github.com/cuga-project/cuga-agent/issues/71) - Instrument CugaAgent SDK with TokenUsageTracker
- [cuga-internal-evaluation#31](https://github.ibm.com/research-rpa/cuga-internal-evaluation/issues/31) - Changes and fixes to new evaluation framework (closed)
