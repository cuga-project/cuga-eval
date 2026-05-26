# 🧪 CUGA Evaluation Framework - Project Overview

## 🎯 Purpose
This is an **evaluation framework** for testing the CUGA Agent (an AI agent system) across three different benchmark scenarios. It measures agent performance on real-world tasks involving API interactions, multi-hop reasoning, and web automation.

## 🏗️ Architecture

### Core Components

**1. CUGA Agent (External Dependency)**
- Located at `../cuga-agent` (editable install)
- The AI agent being evaluated
- Supports policies, tool calling, and MCP (Model Context Protocol) servers

**2. Configuration System**
- **Hierarchical loading**: `.env` → `config/global.env` → `benchmarks/{name}/config/{name}.env`
- **Critical timing**: `config_loader.load_eval_config()` MUST run BEFORE any cuga imports
- **CUGA_LOGGING_DIR** race condition: Must be set in `os.environ` before cuga modules load

**3. Four Benchmarks**

#### **BPO** (Business Process Outsourcing - Recruiting Analytics)
- FastAPI server with 13 tool APIs (port 8000)
- Tests: candidate sourcing, SLA metrics, skills analysis, funnel conversion
- 26 evaluation tasks across easy/medium/hard difficulties
- 2 terminals: API server, eval script

#### **Oak Health Insurance** (Healthcare Domain)
- FastAPI app simulating insurance system (port 8090)
- Tests: claims, coverage, benefits, plans queries
- 3 terminals needed: app, registry, eval script
- Direct OpenAPI integration

#### **M3** (Multi-hop Q&A)
- Hockey statistics domain
- 211 API endpoints for player/team/coach data
- Tests multi-hop reasoning (questions requiring multiple API calls)
- 2 terminals: registry, eval script

#### **AppWorld** (Web Automation)
- 13 service integrations (Gmail, Spotify, Todoist, Venmo, etc.)
- Tests complex multi-app workflows
- OAuth2 authentication
- Requires Git LFS for dataset

### Key Patterns

**Import Order Enforcement**
```python
# CRITICAL: This order is mandatory
from config_loader import load_eval_config
load_eval_config("benchmark_name")  # Sets env vars
# NOW safe to import cuga modules
from cuga.sdk import CugaAgent
```

**Policy Management**
- Always clear existing policies first
- Add via `agent.policies.add()` API
- Support for Playbooks, ToolGuides, ToolRestrictions

**Evaluation Flow**
1. Load config → 2. Setup agent + tools → 3. Clear/add policies → 4. Run tasks → 5. Check keywords → 6. Report results

## 🔧 Technology Stack

- **Python 3.12+** with `uv` package manager
- **FastAPI** (Oak Health Insurance app)
- **Langfuse** (optional LLM tracing/analytics)
- **Langchain** (LLM framework)
- **Pydantic** (data validation)
- **MCP Protocol** (Model Context Protocol for tool integration)

## 📊 Evaluation Metrics

**Standard Metrics**
- Success rate, task completion
- Keyword matching in responses
- Difficulty-based filtering (easy/medium/hard)

**With ActivityTracker**
- Steps per task, API calls
- Duration tracking

**With Langfuse**
- Total LLM calls, tokens, cost
- Node timings, generation timings
- Cache hit rates

## 🚀 Running Benchmarks

**BPO** (1 terminal from `benchmarks/bpo/`):
```bash
./eval.sh                    # Starts servers, runs eval, cleans up
./eval.sh --task 1 2 3       # Run specific tasks
./eval.sh --task 1 --verbose # With verbose output
```

**Oak Health Insurance** (3 terminals from `benchmarks/oak_health_insurance/`):
```bash
./run_app.sh          # Terminal 1: FastAPI app
./run_registry.sh     # Terminal 2: MCP registry
uv run eval_bench_sdk.py  # Terminal 3: Evaluation
```

**M3/AppWorld** (2 terminals from `benchmarks/{name}/`):
```bash
./run_registry.sh     # Terminal 1: MCP registry
uv run eval_{name}.py # Terminal 2: Evaluation
```

**Visualization** (from project root):
```bash
./scripts/viz.sh {benchmark_name}
```

## 📁 Project Structure

```
cuga-eval/
├── .env                          # Secrets (API keys)
├── pyproject.toml                # Dependencies
├── README.md                     # Main documentation
├── AGENTS.md                     # Agent coding rules
├── PROJECT_OVERVIEW.md           # This file
│
├── config/
│   └── global.env                # Global configuration
│
├── config_loader/
│   ├── __init__.py
│   └── loader.py                 # Critical: loads env before cuga imports
│
├── benchmarks/
│   ├── helpers/
│   │   ├── config_loader.py      # Config loading utilities
│   │   ├── sdk_eval_helpers.py   # Evaluation helper functions
│   │   └── run_registry.sh       # Shared registry script
│   │
│   ├── bpo/
│   │   ├── config/
│   │   │   └── bpo.env
│   │   ├── data/
│   │   │   └── candidate_data.parquet
│   │   ├── mcp_servers/
│   │   │   └── bpo.yaml
│   │   ├── eval_bench_sdk.py     # Evaluation script
│   │   ├── bpo_test_suite_v1.json
│   │   ├── main.py               # FastAPI app
│   │   ├── mcp_server.py         # MCP server
│   │   └── eval.sh           # All-in-one runner
│   │
│   ├── oak_health_insurance/
│   │   ├── config/
│   │   │   └── oak_health_insurance.env
│   │   ├── main.py               # FastAPI app
│   │   ├── eval_bench_sdk.py     # Evaluation script
│   │   ├── oak_policies.py       # Policy definitions
│   │   ├── oak_mcp_servers.yaml  # MCP configuration
│   │   ├── oak_health_test_suite_v1.json
│   │   ├── run_app.sh
│   │   └── run_registry.sh
│   │
│   ├── m3/
│   │   ├── config/
│   │   │   └── m3.env
│   │   ├── eval_m3.py            # Evaluation script
│   │   ├── hockey.json           # Test dataset (19 samples)
│   │   ├── hockey_yaml.yaml      # MCP configuration (211 endpoints)
│   │   └── run_registry.sh
│   │
│   └── appworld/
│       ├── config/
│       │   └── appworld.env
│       ├── appworld_eval.py      # Evaluation script
│       ├── mcp_servers_appworld.yaml  # 13 services
│       ├── eval_config.toml      # Task groups
│       └── utils/
│
├── scripts/
│   └── viz.sh                    # Visualization script
│
└── templates/
    ├── eval_loop_template.py     # Template for new benchmarks
    └── simple_example.json
```

## 🎓 Enhancement Opportunities

### 1. Add New Benchmarks
- Follow template in `templates/eval_loop_template.py`
- Create `benchmarks/{name}/config/{name}.env`
- Define MCP servers YAML
- Implement evaluation script

### 2. Improve Evaluation
- Add more sophisticated metrics
- Implement automated scoring
- Add regression testing
- Create comparison dashboards

### 3. Policy System
- Expand policy types
- Add policy validation
- Create policy templates
- Implement policy versioning

### 4. Observability
- Enhanced Langfuse integration
- Custom metrics collection
- Real-time monitoring
- Error analysis tools

### 5. Testing Infrastructure
- Add unit tests (currently none)
- Integration test suite
- CI/CD pipeline
- Automated benchmark runs

### 6. Documentation
- API documentation
- Architecture diagrams
- Tutorial videos
- Best practices guide

### 7. Performance Optimization
- Parallel task execution
- Caching strategies
- Resource management
- Benchmark optimization

## ⚠️ Critical Gotchas

1. **Config loading order** - Must happen before cuga imports or CUGA_LOGGING_DIR race condition occurs
2. **Working directories** - Scripts must run from benchmark directories (not project root)
3. **Path manipulation** - Relative paths in .env files are automatically converted to absolute
4. **Langfuse flushing** - Manual flush needed in short-lived scripts via `flush_langfuse()`
5. **Policy clearing** - Always clear before adding new policies to avoid duplicates/conflicts
6. **Keyword checking with OR** - Use `|` for alternatives: `"1000|1,000"` matches either format
7. **ActivityTracker callbacks** - Must use `create_activity_tracker_callback()` helper
8. **DYNACONF_ prefix** - All feature flags require this prefix (e.g., `DYNACONF_POLICY__ENABLED=true`)

## 🔍 Key Files to Understand

### Configuration
- `config_loader/loader.py` - Critical config loading logic
- `benchmarks/helpers/sdk_eval_helpers.py` - Reusable evaluation functions

### Evaluation Scripts
- `benchmarks/bpo/eval_bench_sdk.py` - BPO evaluation
- `benchmarks/oak_health_insurance/eval_bench_sdk.py` - Oak evaluation
- `benchmarks/m3/eval_m3.py` - M3 evaluation
- `benchmarks/appworld/appworld_eval.py` - AppWorld evaluation

### Policies
- `benchmarks/oak_health_insurance/oak_policies.py` - Example policy definitions

### Data
- `benchmarks/bpo/bpo_test_suite_v1.json` - BPO test cases (26 tasks)
- `benchmarks/oak_health_insurance/oak_health_test_suite_v1.json` - Oak test cases
- `benchmarks/m3/hockey.json` - M3 test cases (19 samples)
- `benchmarks/appworld/eval_config.toml` - AppWorld task groups

## 🤝 Contributing

When adding features or fixing bugs:

1. **Follow the import order pattern** - Always load config before cuga imports
2. **Use helper functions** - Don't reinvent the wheel (see `sdk_eval_helpers.py`)
3. **Clear policies first** - Before adding new ones
4. **Test with all benchmarks** - Ensure changes don't break existing evaluations
5. **Update documentation** - Keep READMEs and this overview in sync
6. **Add to AGENTS.md** - Document non-obvious patterns for AI agents

## 📚 Additional Resources

- [Main README](README.md) - Installation and quick start
- [AGENTS.md](AGENTS.md) - Coding rules for AI agents
- [BPO README](benchmarks/bpo/README.md)
- [Oak Health Insurance README](benchmarks/oak_health_insurance/README.md)
- [M3 README](benchmarks/m3/README.md)
- [AppWorld README](benchmarks/appworld/README.md)
- [CUGA Agent Repository](../cuga-agent) - The agent being evaluated

## 🐛 Troubleshooting

**"CUGA_LOGGING_DIR not set" error**
- Ensure `config_loader.load_eval_config()` is called before any cuga imports

**"Module not found" errors**
- Check that `../cuga-agent` exists and is properly installed
- Run `uv sync` to install dependencies

**Registry connection errors**
- Ensure registry is running (`./run_registry.sh`)
- Check MCP_SERVERS_FILE path in config

**Langfuse not working**
- Verify Langfuse is running (`docker compose up` in langfuse directory)
- Check API keys in `.env` file
- Ensure `langfuse_tracing = true` in cuga settings.toml

**FastAPI app not starting (Oak)**
- Check port 8090 is not in use
- Verify all dependencies are installed

---

## 🎯 Adoptable Features Deep Dive

This section provides detailed explanations of key features that can be adopted in other projects.

### 1. 📊 ActivityTracker for API Calls (Instead of Logs)

**Purpose**: Capture structured, queryable data about agent behavior rather than relying solely on logs.

**Implementation Location**: `benchmarks/helpers/sdk_eval_helpers.py:163-229`

**Core Concept**:
```python
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step

tracker = ActivityTracker()

# Before each task
tracker.reset(intent=intent, task_id=task_name)

# During execution
tracker.collect_step(Step(name="StepName", data=step_data))

# After task completion
tracker.finish_task(
    intent=intent,
    site="",
    task_id=task_name,
    eval=report_md,           # JSON-serializable evaluation report
    score=score,              # Numeric score (0.0-1.0)
    agent_answer=response,
    exception=False,
    num_steps=0,
    total_llm_calls=0,
    total_tokens=0,
    total_cost=0.0,
    agent_v="",
)
tracker.collect_score(score)
```

**Key Benefits**:
- **Structured data**: JSON-serializable, queryable
- **Metrics tracking**: Steps, scores, costs, tokens, duration
- **Experiment management**: Track multiple tasks in batches
- **Programmatic analysis**: Query and analyze results
- **Separation of concerns**: Operational data separate from debug logs

**Callback Pattern** (lines 163-229):
```python
def create_activity_tracker_callback(tracker, var_manager=None):
    """Create a tracker callback for evaluation results."""
    def tracker_callback(result: Dict[str, Any], keyword_check: Dict[str, Any], intent: str):
        if result.get("error"):
            # Handle errors
            tracker.finish_task(score=0.0, exception=True, ...)
        else:
            # Handle success
            score = keyword_check["match_rate"]
            tracker.finish_task(score=score, exception=False, ...)
            tracker.collect_step(Step(name="EvaluationResult", data=report_md))
    return tracker_callback
```

**How to Adopt**:
1. Create `ActivityTracker()` instance
2. Call `tracker.reset()` before each task
3. Use `tracker.collect_step()` during execution
4. Call `tracker.finish_task()` with all metrics
5. Use `tracker.start_experiment()` for batch runs
6. Query tracker data for analysis

---

### 2. 📋 tasks.json Format

**Purpose**: Standardized JSON format for test cases with validation criteria.

**Implementation Location**: `benchmarks/oak_health_insurance/oak_health_test_suite_v1.json`

**Format Structure**:
```json
[
  {
    "name": "benchmark_name",
    "user_info": [
      "member_id:121231234",
      "location:[latitude:40.7128, longitude:-74.0060]",
      "current_date:2025-06-15"
    ],
    "test_cases": [
      {
        "name": "task_identifier",
        "description": "Human-readable description",
        "intent": "The actual prompt/query sent to the agent",
        "difficulty": "easy|medium|hard",
        "expected_output": {
          "response": "Expected response text (optional)",
          "keywords": [
            "exact_keyword",
            "1000|1,000",              // OR syntax for alternatives
            "approved|accepted"        // Synonym alternatives
          ],
          "tool_calls": [
            {
              "name": "expected_tool_name",
              "args": {"param": "value"}
            }
          ]
        }
      }
    ]
  }
]
```

**Key Features**:
- **Difficulty levels**: Filter tests by complexity (easy/medium/hard)
- **Keywords with OR**: Use `|` for format alternatives
- **Expected tool calls**: Validate agent's tool usage
- **User context**: Inject user-specific data per benchmark
- **Hierarchical structure**: Group tests by benchmark/app

**Usage Pattern** (from `eval_bench_sdk.py:120-151`):
```python
# Load test data
with open("oak_health_test_suite_v1.json", "r") as f:
    data = json.load(f)

# Extract test cases
test_cases = []
for app_data in data:
    if "test_cases" in app_data:
        test_cases.extend(app_data["test_cases"])

# Filter by difficulty
if difficulty_filter:
    test_cases = [tc for tc in test_cases
                  if tc.get("difficulty", "").lower() == difficulty_filter.lower()]

# Filter by specific task ID
if task_id:
    test_cases = [tc for tc in test_cases
                  if tc.get("name", "").lower() == task_id.lower()]
```

**How to Adopt**:
1. Create JSON file with test_cases array
2. Define difficulty levels for progressive testing
3. Use keywords with `|` for OR alternatives
4. Include expected tool_calls for validation
5. Add user_info for context injection
6. Implement filtering by difficulty/task_id

---

### 3. 🔍 Langfuse Integration

**Purpose**: Comprehensive LLM observability including tokens, costs, cache hits, and call tracing.

**Implementation Location**: `benchmarks/helpers/sdk_eval_helpers.py:50-72, 326-385`

#### 3a. Setup

```python
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

def setup_langfuse():
    """Setup Langfuse tracing callback handler."""
    try:
        handler = LangfuseCallbackHandler()
        return handler
    except Exception as e:
        logger.error(f"Failed to create Langfuse handler: {e}")
        return None

# Pass to agent
agent = CugaAgent(tool_provider=tool_provider, callbacks=[langfuse_handler])
```

**Environment Variables Required**:
```bash
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted URL
```

#### 3b. Token Tracking

**Automatic**: Langfuse automatically captures:
- Input tokens (prompt)
- Output tokens (completion)
- Total tokens per call
- Aggregated tokens across traces
- Token usage by model

**View in Langfuse UI**: Traces → Select trace → View token metrics

#### 3c. Cost Tracking

**Automatic calculation**: Langfuse computes costs based on:
- Model pricing (configured in Langfuse settings)
- Token counts (input + output)
- Per-call costs
- Aggregated costs across traces/sessions

**View in Langfuse UI**: Dashboard → Cost analytics

#### 3d. LLM Call Tracking with Custom Spans

**Implementation** (lines 326-385):
```python
from langfuse import get_client

langfuse = get_client()

# Create deterministic trace ID
trace_name = f"eval_{task_name}_{task_index}"
predefined_trace_id = langfuse.create_trace_id(
    seed=f"{task_name}_{task_index}_{thread_id}"
)

# Start observation span
with langfuse.start_as_current_observation(
    as_type="span",
    name=trace_name,
    trace_context={"trace_id": predefined_trace_id},
    input={
        "intent": intent,
        "task_name": task_name,
        "difficulty": difficulty,
        "expected_keywords": expected_keywords
    },
    metadata={"thread_id": thread_id, "task_index": task_index},
) as span:
    # Execute agent
    invoke_result = await agent.invoke(
        [HumanMessage(content=intent)],
        thread_id=thread_id,
        user_context=user_context
    )

    # Update span with results
    span.update(
        output={
            "response_preview": response,
            "keyword_results": {
                "found_keywords": keyword_check["found_keywords"],
                "missing_keywords": keyword_check["missing_keywords"],
                "total_keywords": keyword_check["total_keywords"],
                "found_count": keyword_check["found_count"],
            }
        },
        metadata={"thread_id": thread_id, "task_index": task_index}
    )

    # Add custom scores
    span.score_trace(
        name="keyword_match",
        value=keyword_check["match_rate"],
        data_type="NUMERIC",
        comment=f"Found {found_count}/{total_keywords} keywords"
    )

    span.score_trace(
        name="success",
        value=keyword_check["all_found"],
        data_type="BOOLEAN",
        comment="Overall task success"
    )
```

#### 3e. Cache Input Tokens

**Automatic with supported models**: When using models with prompt caching (e.g., Claude 3.5 Sonnet):
- Langfuse automatically tracks cache creation tokens
- Tracks cache read tokens (cached input tokens)
- Calculates cache hit rates
- Shows cost savings from caching

**View in Langfuse UI**: Traces → Select trace → View cache metrics

#### 3f. Critical: Flushing in Short-Lived Scripts

**Location**: `sdk_eval_helpers.py:535-549`

```python
def flush_langfuse(langfuse_handler):
    """Flush Langfuse events in short-lived applications.

    CRITICAL: Langfuse batches events for efficiency. Short-lived scripts
    may exit before events are sent. Always call this before script exit.
    """
    if langfuse_handler:
        try:
            from langfuse import get_client
            langfuse = get_client()
            langfuse.flush()  # Force send all pending events
            logger.info("✅ Flushed Langfuse events")
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse events: {e}")
```

**Usage** (from `eval_bench_sdk.py:170`):
```python
# After all tasks complete
flush_langfuse(self.langfuse_handler)
```

**How to Adopt**:
1. Install: `pip install langfuse`
2. Set environment variables (keys + host)
3. Create `LangfuseCallbackHandler()`
4. Pass handler to agent callbacks
5. Use `start_as_current_observation()` for custom spans
6. Add custom scores with `span.score_trace()`
7. Update spans with `span.update()`
8. **ALWAYS call `langfuse.flush()` before script exit**

---

### 4. 🔑 Keyword Checking System

**Purpose**: Flexible keyword validation with OR logic for alternative matches.

**Implementation Location**: `benchmarks/helpers/sdk_eval_helpers.py:232-281`

**Core Implementation**:
```python
def check_keywords(response: str, expected_keywords: List[str]) -> Dict[str, Any]:
    """Check if expected keywords are present in the response.

    Supports OR mechanism: keywords can use "|" to specify alternatives.
    Example: "1000|1,000" will match if either "1000" or "1,000" is found.

    Args:
        response: Agent's response text
        expected_keywords: List of keywords (can use "|" for OR)

    Returns:
        Dictionary with keyword check results
    """
    # Normalize spaces (handle Unicode non-breaking spaces)
    answer_str = response.replace("\u202f", " ")
    response_lower = answer_str.lower()

    found_keywords = []
    missing_keywords = []

    for keyword in expected_keywords:
        if "|" in keyword:
            # OR logic: match any alternative
            alternatives = [alt.strip() for alt in keyword.split("|")]
            matched = False
            for alt in alternatives:
                alt_lower = alt.lower()
                if alt_lower in response_lower:
                    matched = True
                    break

            if matched:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)
        else:
            # Simple substring match
            keyword_lower = keyword.lower()
            if keyword_lower in response_lower:
                found_keywords.append(keyword)
            else:
                missing_keywords.append(keyword)

    all_found = len(missing_keywords) == 0
    match_rate = len(found_keywords) / len(expected_keywords) if expected_keywords else 0.0

    return {
        "all_found": all_found,           # Boolean: all keywords present
        "match_rate": match_rate,         # Float 0-1: percentage found
        "found_keywords": found_keywords, # List of matched keywords
        "missing_keywords": missing_keywords, # List of missing keywords
        "total_keywords": len(expected_keywords),
        "found_count": len(found_keywords),
    }
```

**Key Features**:

1. **OR Logic**: Use `|` for alternatives
   ```python
   keywords = [
       "1000|1,000",              # Number format alternatives
       "approved|accepted",       # Synonym alternatives
       "John Smith|J. Smith",     # Name variations
       "2025-01-15|01/15/2025"   # Date format alternatives
   ]
   ```

2. **Case-Insensitive**: All matching is lowercase

3. **Unicode Handling**: Normalizes Unicode spaces (`\u202f`)

4. **Rich Results**: Returns comprehensive match information

**Usage Example**:
```python
# Define keywords in test case
keywords = [
    "2025034AA5006",           # Exact claim ID
    "1000|1,000",              # Amount with/without comma
    "approved|accepted",       # Status synonyms
    "John Smith|J. Smith"      # Name variations
]

# Check response
result = check_keywords(agent_response, keywords)

if result["all_found"]:
    print("✅ All keywords found!")
else:
    print(f"❌ Missing: {result['missing_keywords']}")
    print(f"Match rate: {result['match_rate']:.1%}")
    print(f"Found: {result['found_keywords']}")
```

**Integration with Evaluation** (from `sdk_eval_helpers.py:352-385`):
```python
# Check keywords
keyword_check = check_keywords(result_state, expected_keywords)

# Log results
if keyword_check["all_found"]:
    logger.info("✅ PASS: All keywords found")
else:
    logger.warning(f"❌ FAIL: Missing keywords: {keyword_check['missing_keywords']}")
    logger.info(f"   Match rate: {keyword_check['match_rate']:.1%}")

# Add to Langfuse trace
span.score_trace(
    name="keyword_match",
    value=keyword_check["match_rate"],
    data_type="NUMERIC",
    comment=f"Found {keyword_check['found_count']}/{keyword_check['total_keywords']} keywords"
)
```

**How to Adopt**:
1. Copy `check_keywords()` function
2. Define keywords in test cases JSON
3. Use `|` for OR alternatives
4. Call after agent response
5. Use `match_rate` for partial credit scoring
6. Log `missing_keywords` for debugging
7. Integrate with scoring/tracking systems

---

## 🎯 Quick Adoption Checklist

### ActivityTracker
- [ ] Import `ActivityTracker` and `Step`
- [ ] Create tracker instance
- [ ] Call `reset()` before each task
- [ ] Use `collect_step()` during execution
- [ ] Call `finish_task()` with all metrics
- [ ] Use `start_experiment()` for batch runs

### tasks.json Format
- [ ] Create JSON with `test_cases` array
- [ ] Add `difficulty` levels (easy/medium/hard)
- [ ] Define `keywords` with OR syntax (`|`)
- [ ] Include `expected_output` with tool_calls
- [ ] Add `user_info` for context
- [ ] Implement filtering by difficulty/task_id

### Langfuse Integration
- [ ] Install `langfuse` package
- [ ] Set environment variables (keys + host)
- [ ] Create `LangfuseCallbackHandler()`
- [ ] Pass to agent callbacks
- [ ] Use `start_as_current_observation()` for spans
- [ ] Add custom scores with `span.score_trace()`
- [ ] **Always call `langfuse.flush()` before exit**

### Keyword Checking
- [ ] Copy `check_keywords()` function
- [ ] Define keywords in test cases
- [ ] Use `|` for OR alternatives
- [ ] Check `match_rate` for scoring
- [ ] Log `missing_keywords` for debugging
- [ ] Integrate with evaluation system

- Check logs in terminal output
