"""Reproducibility bundles for evaluation runs.

Creates self-contained directories with metadata, results, tasks, and
(optionally) policies needed to audit or reproduce an evaluation run.

Works for any benchmark — pass ``benchmark_dir`` to customise paths.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.helpers.incremental_results import atomic_write_json

BUNDLE_VERSION = "2"

# Only these environment variables are captured (no secrets)
ALLOWED_ENV_VARS = [
    "MODEL_NAME",
    "AGENT_SETTING_CONFIG",
    "OPENAI_BASE_URL",
    "OPENAI_API_VERSION",
    "CUGA_MODE",
    "AGENT_MODE",
    "MEMORY_ENABLED",
    "LANGFUSE_HOST",
    "BPO_LOG_API_CALLS",
    "M3_VAKRA_LIVE_MCP",
]

# Dynaconf overrides that affect CUGA behaviour
DYNACONF_PREFIXES = [
    "DYNACONF_POLICY__",
    "DYNACONF_ADVANCED_FEATURES__",
    "DYNACONF_FEATURES__",
    "DYNACONF_AGENT__",
    "DYNACONF_STORAGE__",
    "DYNACONF_CONTEXT_SUMMARIZATION__",
    "DYNACONF_EVOLVE__",
]

# Resolve once: <project_root>/benchmarks/helpers -> <project_root>
_HELPERS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _HELPERS_DIR.parent.parent


def _bundle_timestamp() -> str:
    """Local-time stamp for auto-generated bundle directory names.

    Deliberately local, not UTC: every other artifact of the same run — the
    ``RUN_ID`` exported by ``eval.sh``, the results JSON filename, the
    trajectory directory — is stamped with local wall-clock time. A UTC bundle
    name made a single run look like two runs an offset apart and sorted
    bundles out of step with the results files they contain.

    Machine-readable timestamps stay absolute; see :func:`_utc_now_iso`.
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _utc_now_iso() -> str:
    """Valid ISO-8601 UTC instant for machine-readable metadata fields.

    Absolute rather than local so bundles produced on machines in different
    timezones stay comparable and orderable. ``isoformat()`` already emits the
    ``+00:00`` offset — appending a ``Z`` on top of it (as this did before the
    timestamp fix in PR #162) produced ``...+00:00Z``, which
    ``datetime.fromisoformat`` rejects.
    """
    return datetime.now(timezone.utc).isoformat()


def _sanitize_model_slug(model_name: str) -> str:
    """Filesystem-safe label from a model name (e.g. google/gemma-4-31b → gemma-4-31b)."""
    name = model_name.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9._-]", "_", name)[:64]


def _bundle_profile_label(model_profile: str | None) -> str:
    """Directory label for single-run bundles; honour --dotenv MODEL_NAME when set."""
    use_dotenv = os.environ.get("USE_DOTENV", "").lower() == "true"
    model_name = (os.environ.get("MODEL_NAME") or "").strip()
    if use_dotenv and model_name:
        return _sanitize_model_slug(model_name)
    return model_profile or "default"


def _load_benchmark_env(benchmark_name: str) -> None:
    """Load project .env + global + benchmark .env files (dotenv strips inline comments).

    Project ``.env`` is loaded first with ``override=False`` so local-only secrets
    (e.g. ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_SECRET_KEY``, ``LANGFUSE_HOST`` for
    self-hosted Langfuse) reach this CLI when it runs as a subprocess from the
    benchmark shell scripts. Without it, the trace-download step silently
    bails out with zero files because the env vars are invisible.
    """
    from dotenv import load_dotenv

    project_env = PROJECT_ROOT / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=False)
    global_env = PROJECT_ROOT / "config" / "global.env"
    if global_env.exists():
        load_dotenv(global_env, override=True)
    benchmark_env = PROJECT_ROOT / "benchmarks" / benchmark_name / "config" / f"{benchmark_name}.env"
    if benchmark_env.exists():
        load_dotenv(benchmark_env, override=True)


# ---------------------------------------------------------------------------
# Git / hash helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: str | Path | None = None) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 — args is a fixed list, no shell, no untrusted input
            ["git"] + args,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_task_file(tf: Path, tasks_dir: Path | None) -> str | None:
    """Copy a task file into ``tasks_dir`` (if given) and return its hash entry.

    ``--m3-data`` runs pass a dataset *directory* as the task source. Copying a
    whole corpus into every bundle is wasteful, so for directories we write a
    ``<name>.source`` pointer file instead and record a ``dir:`` marker in place
    of a content hash. Returns None when ``tf`` does not exist.
    """
    if not tf.exists():
        return None
    if tf.is_dir():
        if tasks_dir is not None:
            tasks_dir.mkdir(exist_ok=True)
            (tasks_dir / f"{tf.name}.source").write_text(f"{tf.resolve()}\n")
        return f"dir:{tf.resolve()}"
    if tasks_dir is not None:
        tasks_dir.mkdir(exist_ok=True)
        shutil.copy2(tf, tasks_dir / tf.name)
    return f"sha256:{_file_sha256(tf)}"


# ---------------------------------------------------------------------------
# Metadata collectors
# ---------------------------------------------------------------------------


def collect_repo_git_info() -> dict:
    """Git info for *this* evaluation repository."""
    commit = _run_git(["rev-parse", "--short", "HEAD"])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    dirty = _run_git(["status", "--short"])
    return {
        "git_commit": commit,
        "git_branch": branch,
        "git_dirty": bool(dirty) if dirty is not None else None,
    }


def collect_cuga_info(git_info: dict | None = None) -> dict:
    """Git/version info for the cuga-agent checkout used by this run.

    ``git_info`` is an optional pre-captured {"git_commit", "git_branch",
    "git_dirty"} snapshot. Pass it for any multi-run bundle (eval.sh/compare.sh
    runs that take more than a few seconds) — querying git live here, in the
    bundle-assembly step, reflects whatever is checked out at *finalization*
    time, not what was actually checked out while the run(s) executed. If the
    checkout is shared (e.g. someone switches branches in it for unrelated
    work) while a long compare.sh run is in flight, a live query silently
    mislabels the whole bundle. Callers should capture git_info once, before
    kicking off any eval.sh subprocess, and thread it through unchanged.
    """
    cuga_version = None
    try:
        import cuga

        cuga_version = getattr(cuga, "__version__", None)
    except ImportError:
        pass

    if git_info is not None:
        cuga_git = git_info
    else:
        cuga_repo = os.environ.get("CUGA_REPO_PATH", os.path.expanduser("~/workspace/cuga-agent"))
        cuga_repo_path = Path(cuga_repo)
        cuga_git = {}
        if cuga_repo_path.exists():
            cuga_git = {
                "git_commit": _run_git(["rev-parse", "--short", "HEAD"], cwd=cuga_repo_path),
                "git_branch": _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cuga_repo_path),
                "git_dirty": bool(_run_git(["status", "--short"], cwd=cuga_repo_path) or ""),
            }

    return {
        "version": cuga_version,
        **cuga_git,
        "mode": os.environ.get("CUGA_MODE"),
        "memory_enabled": os.environ.get("MEMORY_ENABLED"),
        "agent_mode": os.environ.get("AGENT_MODE"),
    }


def collect_environment() -> dict:
    env = {k: os.environ.get(k) for k in ALLOWED_ENV_VARS if os.environ.get(k)}
    for key, value in os.environ.items():
        if any(key.startswith(p) for p in DYNACONF_PREFIXES):
            env[key] = value
    return env


def collect_policy_metadata(policies_dir: Path | None) -> dict:
    if policies_dir is None or not policies_dir.exists():
        return {"policies_json_hash": None}
    pj = policies_dir / "policies.json"
    if pj.exists():
        return {"policies_json_hash": f"sha256:{_file_sha256(pj)}"}
    return {"policies_json_hash": None}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_cuga_settings_path(benchmark_dir: Path | None = None) -> Path | None:
    config_name = os.environ.get("AGENT_SETTING_CONFIG")
    if not config_name:
        return None
    cuga_repo = os.environ.get("CUGA_REPO_PATH", os.path.expanduser("~/workspace/cuga-agent"))
    candidates = [
        Path(cuga_repo) / "src" / "cuga" / config_name,
        Path(cuga_repo) / "config" / config_name,
        Path(cuga_repo) / config_name,
    ]
    if benchmark_dir:
        candidates.append(benchmark_dir / "config" / config_name)
    candidates.append(Path.cwd() / config_name)
    for p in candidates:
        if p.exists():
            return p
    return None


def _write_run_env(bundle_dir: Path) -> None:
    env = collect_environment()
    if not env:
        return
    config_dir = bundle_dir / "config"
    config_dir.mkdir(exist_ok=True)
    lines = [
        "# Actual environment variables captured at runtime",
        f"# Generated: {_utc_now_iso()}",
        "",
    ]
    for key, value in sorted(env.items()):
        lines.append(f"{key}={value}")
    (config_dir / "run.env").write_text("\n".join(lines) + "\n")


def _copy_cuga_settings(bundle_dir: Path, benchmark_dir: Path | None = None) -> str | None:
    settings_path = _resolve_cuga_settings_path(benchmark_dir)
    if settings_path is None:
        return None
    config_dir = bundle_dir / "config"
    config_dir.mkdir(exist_ok=True)
    shutil.copy2(settings_path, config_dir / settings_path.name)
    return settings_path.name


def _copy_policies(bundle_dir: Path, policies_dir: Path | None) -> bool:
    if policies_dir is None:
        return False
    pj = policies_dir / "policies.json"
    if not pj.exists():
        return False
    dest = bundle_dir / "policies"
    dest.mkdir(exist_ok=True)
    shutil.copy2(pj, dest / "policies.json")
    return True


def _copy_trajectories(
    bundle_dir: Path, trajectory_dir: Path | None, dest_subdir: str = "trajectories"
) -> bool:
    """Copy a trajectory folder into the bundle.

    Parameters
    ----------
    trajectory_dir : Path | None
        Path to a specific trajectory folder (e.g.
        ``logging/trajectory_data/test_normal_easy_12-03--12h33m24s470ms``).
    dest_subdir : str
        Subdirectory name inside the bundle (default ``"trajectories"``).
    """
    if trajectory_dir is None or not trajectory_dir.exists():
        return False
    dest = bundle_dir / dest_subdir
    shutil.copytree(trajectory_dir, dest, dirs_exist_ok=True)
    return True


def find_latest_trajectory(trajectory_data_dir: Path) -> Path | None:
    """Return the most recently modified subfolder under *trajectory_data_dir*."""
    if not trajectory_data_dir.is_dir():
        return None
    subdirs = [d for d in trajectory_data_dir.iterdir() if d.is_dir()]
    if not subdirs:
        return None
    return max(subdirs, key=lambda d: d.stat().st_mtime)


def _copy_logs(bundle_dir: Path, log_files: list[str | Path] | None, dest_subdir: str = "logs") -> bool:
    """Copy log files into the bundle.

    Parameters
    ----------
    log_files : list
        Paths to individual log files to include.
    """
    if not log_files:
        return False
    copied = False
    dest = bundle_dir / dest_subdir
    for lf in log_files:
        lf = Path(lf)
        if lf.exists() and lf.stat().st_size > 0:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(lf, dest / lf.name)
            copied = True
    return copied


def _retry_after_seconds(err, default: float) -> float:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds."""
    try:
        ra = err.headers.get("Retry-After") if err.headers else None
    except Exception:
        ra = None
    if not ra:
        return default
    ra = ra.strip()
    if ra.isdigit():
        return float(ra)
    try:
        import time as _t
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(ra)
        if dt is not None:
            return max(0.0, dt.timestamp() - _t.time())
    except Exception:  # noqa: S110 — malformed Retry-After is expected/benign, fall back to default
        pass
    return default


def _download_langfuse_traces(
    bundle_dir: Path,
    result_files: list[str | Path],
    dest_subdir: str = "langfuse_traces",
    skip_existing: bool = True,
) -> bool:
    """Download Langfuse trace data for all trace IDs found in result files.

    Reads each result JSON, extracts ``trace_id`` fields from individual
    task results, and fetches the full trace from the Langfuse API.  Only
    runs when ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        print("Langfuse trace download skipped: LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set.")
        return False

    host = os.environ.get("LANGFUSE_HOST") or os.environ.get(
        "LANGFUSE_BASE_URL", "https://cloud.langfuse.com"
    )

    # Collect trace IDs from result files
    trace_ids: list[tuple[str, str]] = []  # (task_name, trace_id)
    for rf in result_files:
        rf = Path(rf)
        if not rf.exists():
            continue
        try:
            data = json.loads(rf.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        # SDK-style results: {"results": [{"trace_id": "...", "task_name": "..."}, ...]}
        for r in data.get("results", []):
            tid = r.get("trace_id")
            if tid:
                task_name = r.get("task_name", r.get("task_id", "unknown"))
                trace_ids.append((str(task_name), tid))

        # Appworld-style results: {"task_results": {"task_id": {"trace_id": "..."}}}
        task_results = data.get("task_results", {})
        if isinstance(task_results, dict):
            for task_id, tr in task_results.items():
                if isinstance(tr, dict) and tr.get("trace_id"):
                    trace_ids.append((str(task_id), tr["trace_id"]))

    if not trace_ids:
        return False

    import base64
    import time
    import urllib.error
    import urllib.request

    dest = bundle_dir / dest_subdir
    dest.mkdir(parents=True, exist_ok=True)
    downloaded = False
    auth_header = "Basic " + base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    max_attempts = 10
    retry_delay = 2.0
    # Inter-request pause: self-hosted Langfuse (e.g. local Docker) drops
    # connections under back-to-back urlopen bursts. Cloud Langfuse is fine
    # with this and pays only the small total wall-clock cost (~0.3s × N).
    inter_request_pause = 0.3

    for task_name, trace_id in trace_ids:
        url = f"{host}/api/public/traces/{trace_id}"
        req_headers = {"Authorization": auth_header}
        safe_name = task_name.replace("/", "_").replace("\\", "_")
        out_file = dest / f"{safe_name}_{trace_id}.json"
        success = False

        # Idempotency: a trace already on disk is never re-fetched. This makes
        # resume/retry cheap and turns partial fetches into "just fetch the rest".
        if skip_existing and out_file.exists():
            continue

        for attempt in range(1, max_attempts + 1):
            req = urllib.request.Request(url, headers=req_headers)  # noqa: S310 — URL built from configured Langfuse host
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  # nosec B310 — same controlled URL
                    trace_data = json.loads(resp.read().decode())
                out_file.write_text(json.dumps(trace_data, indent=2, default=str) + "\n")
                downloaded = True
                success = True
                print(f"  Langfuse trace saved: {out_file.name}")
                break
            except urllib.error.HTTPError as e:
                # 404 = trace not yet flushed to Langfuse; 429 = rate limited
                # (common when a Langfuse key is shared across people). Both are
                # transient and worth retrying; 429 honors Retry-After when sent.
                if e.code in (404, 429) and attempt < max_attempts:
                    delay = _retry_after_seconds(e, retry_delay) if e.code == 429 else retry_delay
                    if attempt == 1:
                        reason = "rate limited (429)" if e.code == 429 else "not yet available"
                        print(f"  Trace {trace_id} {reason}, retrying (up to {max_attempts} attempts)...")
                    time.sleep(delay)
                    continue
                # 4xx/5xx other than 404/429 are typically permanent (e.g. 500
                # "Observations in trace are too large"); don't retry.
                print(f"  Warning: Failed to download Langfuse trace {trace_id}: {e}")
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                # Transient network/connection issues — retry with backoff.
                if attempt < max_attempts:
                    if attempt == 1:
                        print(
                            f"  Connection issue fetching trace {trace_id}: {e}; "
                            f"retrying (up to {max_attempts} attempts)..."
                        )
                    time.sleep(retry_delay)
                    continue
                print(f"  Warning: Failed to download Langfuse trace {trace_id}: {e}")
                break
            except Exception as e:
                print(f"  Warning: Failed to download Langfuse trace {trace_id}: {e}")
                break

        if not success and not out_file.exists():
            print(f"  Warning: Could not fetch trace {trace_id} after {max_attempts} attempts")

        if inter_request_pause > 0:
            time.sleep(inter_request_pause)

    return downloaded


def _write_per_model_config(bundle_dir: Path, model_envs: dict, benchmark_dir: Path | None = None) -> dict:
    config_dir = bundle_dir / "config"
    config_dir.mkdir(exist_ok=True)
    settings_files = {}
    for model_name, env_data in model_envs.items():
        settings_path = env_data.pop("settings_path", "")
        lines = [
            f"# Runtime environment for model profile: {model_name}",
            f"# Generated: {_utc_now_iso()}",
            "",
        ]
        for key, value in sorted(env_data.items()):
            if value:
                lines.append(f"{key}={value}")
        (config_dir / f"run_{model_name}.env").write_text("\n".join(lines) + "\n")

        # Resolve settings file: explicit path first, then from AGENT_SETTING_CONFIG
        sp = None
        if settings_path:
            sp = Path(settings_path)
        elif env_data.get("AGENT_SETTING_CONFIG"):
            # Temporarily set env var so _resolve_cuga_settings_path can find it
            orig = os.environ.get("AGENT_SETTING_CONFIG")
            os.environ["AGENT_SETTING_CONFIG"] = env_data["AGENT_SETTING_CONFIG"]
            sp = _resolve_cuga_settings_path(benchmark_dir)
            if orig is not None:
                os.environ["AGENT_SETTING_CONFIG"] = orig
            else:
                os.environ.pop("AGENT_SETTING_CONFIG", None)

        if sp and sp.exists():
            shutil.copy2(sp, config_dir / sp.name)
            settings_files[model_name] = sp.name
    return settings_files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_bundle(
    result_files: list[str | Path],
    task_files: list[str | Path],
    args: dict,
    benchmark_name: str = "default",
    model_profile: str | None = None,
    bundle_root: Path | None = None,
    policies_dir: Path | None = None,
    trajectory_dir: Path | None = None,
    log_files: list[str | Path] | None = None,
    fetch_langfuse: bool = False,
    report_content: str | None = None,
    cuga_git_info: dict | None = None,
) -> Path:
    """Create a single-run reproducibility bundle.

    Parameters
    ----------
    benchmark_name : str
        Used in the bundle directory name (e.g. "bpo", "appworld").
    policies_dir : Path | None
        If provided, ``policies.json`` is copied into the bundle.
    """
    benchmark_dir = PROJECT_ROOT / "benchmarks" / benchmark_name
    if bundle_root is None:
        bundle_root = benchmark_dir / "evaluation_bundles"

    timestamp = _bundle_timestamp()
    profile_label = _bundle_profile_label(model_profile)
    bundle_dir = bundle_root / f"{timestamp}_{profile_label}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Results
    results_dir = bundle_dir / "results"
    results_dir.mkdir(exist_ok=True)
    for rf in result_files:
        rf = Path(rf)
        if rf.exists():
            shutil.copy2(rf, results_dir / rf.name)

    # Tasks
    tasks_dir = bundle_dir / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    task_file_hashes = {}
    for tf in task_files:
        tf = Path(tf)
        entry = _record_task_file(tf, tasks_dir)
        if entry is not None:
            task_file_hashes[tf.name] = entry

    # Policies (only if the benchmark has them)
    _copy_policies(bundle_dir, policies_dir)

    # Cuga trajectories
    _copy_trajectories(bundle_dir, trajectory_dir)

    # Copy .progress to bundle root so cuga-viz can find it at either level
    _traj_progress = bundle_dir / "trajectories" / ".progress"
    if _traj_progress.exists():
        shutil.copy2(_traj_progress, bundle_dir / ".progress")

    # Logs
    _copy_logs(bundle_dir, log_files)

    # Langfuse traces
    if fetch_langfuse:
        _download_langfuse_traces(bundle_dir, result_files)

    # Report
    if report_content:
        (bundle_dir / "report.md").write_text(report_content)

    # Runtime config
    _write_run_env(bundle_dir)
    settings_file = _copy_cuga_settings(bundle_dir, benchmark_dir)

    metadata = {
        "bundle_version": BUNDLE_VERSION,
        "created_at": _utc_now_iso(),
        "benchmark": benchmark_name,
        "eval_repo": collect_repo_git_info(),
        "run": {
            "agent": args.get("agent", "cuga_sdk"),
            "model_profile": model_profile,
            "policies_enabled": not args.get("no_policies", False),
            "task_files": [str(Path(tf).name) for tf in task_files],
            "task_ids": args.get("task_ids"),
            "eval_key": args.get("eval_key"),
        },
        "runtime_config": {
            "env_vars": collect_environment(),
            "settings_file": settings_file,
            "model_profile": model_profile,
        },
        "model": {
            "model_name": os.environ.get("MODEL_NAME"),
            "agent_setting_config": os.environ.get("AGENT_SETTING_CONFIG"),
            "openai_base_url": os.environ.get("OPENAI_BASE_URL"),
            "openai_api_version": os.environ.get("OPENAI_API_VERSION"),
        },
        "cuga": collect_cuga_info(cuga_git_info),
        "policies": collect_policy_metadata(policies_dir),
        "environment": collect_environment(),
        "ground_truth": {
            "task_count": len(task_files),
            "task_file_hashes": task_file_hashes,
        },
    }

    (bundle_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")
    return bundle_dir


def assemble_compare_bundle(
    report_content: str,
    config_results: dict[str, list[str]],
    benchmark_name: str = "default",
    task_files: list[str | Path] | None = None,
    bundle_root: Path | None = None,
    model_envs: dict | None = None,
    policies_dir: Path | None = None,
    trajectory_dirs: dict[str, list[list[Path]]] | None = None,
    log_files: dict[str, list[str | Path]] | None = None,
    fetch_langfuse: bool = False,
    eval_key: str | None = None,
    cuga_git_info: dict | None = None,
    bundle_dir_override: Path | None = None,
) -> Path:
    """Create a comparison-level bundle directory.

    ``trajectory_dirs`` maps each config key to a list of RUNS, where each run
    is itself a list of trajectory folders (cuga emits one folder per domain).
    All folders within a run are merged into a single ``runN/trajectories`` dir.

    ``log_files`` maps each config key to either a grouped per-run list
    (``[[run1 logs], [run2 logs], ...]`` → ``runN/logs``) or a flat list
    (legacy / ``"shared"`` key → ``runs/<key>/logs``). Per-run grouping keeps
    each run's own console + registry log instead of only the last run's.

    ``bundle_dir_override``, when given, is used verbatim instead of computing
    a fresh timestamped directory name — used by workspace/experiment-mode
    compare runs, where the bundle directory already exists (created upfront
    by ``prepare_compare_experiment_workspace``) and must be finalized in
    place rather than duplicated into a second, separate directory.
    """
    benchmark_dir = PROJECT_ROOT / "benchmarks" / benchmark_name
    if bundle_root is None:
        bundle_root = benchmark_dir / "evaluation_bundles"

    if bundle_dir_override is not None:
        bundle_dir = Path(bundle_dir_override)
    else:
        timestamp = _bundle_timestamp()
        models = sorted(set(k.split(":")[0] for k in config_results))
        # Detect inner-dim variants (agent and/or policy mode) so the dir name
        # reflects what was compared. Config keys are "model[:agent[:policy_mode]]".
        agents = sorted({parts[1] for k in config_results if len(parts := k.split(":")) > 1 and parts[1]})
        policy_modes = sorted(
            {parts[2] for k in config_results if len(parts := k.split(":")) > 2 and parts[2]}
        )
        suffix_bits = ["_".join(models)]
        if len(agents) > 1:
            suffix_bits.append("_".join(agents))
        if len(policy_modes) > 1:
            suffix_bits.append("_vs_".join(policy_modes))  # e.g. "policies_vs_no-policies"
        elif len(policy_modes) == 1 and policy_modes[0] == "no-policies":
            suffix_bits.append("no-policies")
        suffix = "_".join(suffix_bits)
        bundle_dir = bundle_root / f"{timestamp}_compare_{suffix}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Per-run results
    runs_dir = bundle_dir / "runs"
    for config_key, file_paths in config_results.items():
        for i, fp in enumerate(file_paths, 1):
            fp = Path(fp)
            if not fp.exists():
                continue
            run_label = f"{config_key.replace(':', '_')}_run{i}"
            run_dir = runs_dir / run_label / "results"
            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fp, run_dir / fp.name)

    # Tasks
    task_file_hashes = {}
    if task_files:
        tasks_dir = bundle_dir / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        for tf in task_files:
            tf = Path(tf)
            entry = _record_task_file(tf, tasks_dir)
            if entry is not None:
                task_file_hashes[tf.name] = entry

    # Policies
    _copy_policies(bundle_dir, policies_dir)

    # Cuga trajectories (per-model, per-run). `trajectory_dirs[config]` is a
    # list of RUNS, and each run is a list of trajectory folders (cuga writes
    # one folder per domain). All folders belonging to one eval.sh run are
    # merged into that run's single `trajectories/` dir, so one bundle run maps
    # to one eval run (all 200 trajectories) rather than one per-domain folder.
    if trajectory_dirs:
        for config_key, run_groups in trajectory_dirs.items():
            for i, group in enumerate(run_groups, 1):
                run_label = f"{config_key.replace(':', '_')}_run{i}"
                copied_any = False
                for traj_path in group:
                    traj_path = Path(traj_path)
                    if not traj_path.exists():
                        continue
                    if _copy_trajectories(
                        bundle_dir,
                        traj_path,
                        dest_subdir=f"runs/{run_label}/trajectories",
                    ):
                        copied_any = True
                if not copied_any:
                    continue
                # Copy .progress to run root so cuga-viz can find it
                _run_progress = bundle_dir / "runs" / run_label / "trajectories" / ".progress"
                if _run_progress.exists():
                    shutil.copy2(_run_progress, bundle_dir / "runs" / run_label / ".progress")

    # Logs. Two accepted shapes per config key:
    #   grouped per-run (preferred): [[run1 logs...], [run2 logs...], ...]
    #     → each run's logs land in runs/<config>_run<i>/logs so every run in a
    #       multi-run comparison keeps its OWN console/registry log.
    #   flat (legacy / "shared"): [log, log, ...]
    #     → placed in runs/<config>/logs (e.g. the "shared" key → runs/shared/logs).
    if log_files:
        for config_key, lf_val in log_files.items():
            if lf_val and isinstance(lf_val[0], list):
                for i, group in enumerate(lf_val, 1):
                    run_label = f"{config_key.replace(':', '_')}_run{i}"
                    _copy_logs(bundle_dir, group, dest_subdir=f"runs/{run_label}/logs")
            else:
                run_label = f"{config_key.replace(':', '_')}"
                _copy_logs(bundle_dir, lf_val, dest_subdir=f"runs/{run_label}/logs")

    # Langfuse traces (per-model, per-run)
    if fetch_langfuse:
        for config_key, file_paths in config_results.items():
            for i, fp in enumerate(file_paths, 1):
                run_label = f"{config_key.replace(':', '_')}_run{i}"
                _download_langfuse_traces(
                    bundle_dir,
                    [fp],
                    dest_subdir=f"runs/{run_label}/langfuse_traces",
                )

    # Config
    settings_files = {}
    if model_envs:
        settings_files = _write_per_model_config(bundle_dir, model_envs, benchmark_dir)
    else:
        _write_run_env(bundle_dir)
        sf = _copy_cuga_settings(bundle_dir, benchmark_dir)
        if sf:
            settings_files["default"] = sf

    # Report
    if report_content:
        (bundle_dir / "report.md").write_text(report_content)

    # Build per-model runtime config from model_envs if available
    models_config = {}
    if model_envs:
        for m, env_data in model_envs.items():
            entry = {"settings_file": settings_files.get(m)}
            # Include env vars from model_envs (MODEL_NAME, DYNACONF_*, etc.)
            entry["env_vars"] = {k: v for k, v in env_data.items() if k != "settings_path" and v}
            models_config[m] = entry
    else:
        for m, sf in settings_files.items():
            models_config[m] = {"settings_file": sf}

    metadata = {
        "bundle_version": BUNDLE_VERSION,
        "created_at": _utc_now_iso(),
        "bundle_type": "comparison",
        "benchmark": benchmark_name,
        "eval_repo": collect_repo_git_info(),
        "configs": list(config_results.keys()),
        "runs_per_config": {k: len(v) for k, v in config_results.items()},
        "eval_key": eval_key,
        "runtime_config": {
            "models": models_config,
            "env_vars": collect_environment(),
        },
        "model": {
            "model_name": os.environ.get("MODEL_NAME"),
            "agent_setting_config": os.environ.get("AGENT_SETTING_CONFIG"),
            "openai_base_url": os.environ.get("OPENAI_BASE_URL"),
            "openai_api_version": os.environ.get("OPENAI_API_VERSION"),
        },
        "cuga": collect_cuga_info(cuga_git_info),
        "policies": collect_policy_metadata(policies_dir),
        "environment": collect_environment(),
        "ground_truth": {
            "task_count": len(task_files) if task_files else 0,
            "task_file_hashes": task_file_hashes,
        },
    }

    (bundle_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")
    return bundle_dir


def create_workspace_bundle(
    bundle_dir: Path,
    benchmark_name: str = "default",
    *,
    experiment_name: str | None = None,
    args: dict | None = None,
    model_profile: str | None = None,
) -> Path:
    """Create (or re-open) a bundle directory as a live workspace.

    Called *before* the evaluator runs. Creates ``results/partial/`` up front so
    the evaluator can write per-task results incrementally, and writes an initial
    ``metadata.json`` marked ``"status": "in_progress"``. Idempotent: re-invoking
    on an existing bundle (a ``--resume``) preserves ``created_at`` and
    ``experiment_name`` and appends a new entry to ``resume_history``.
    """
    bundle_dir = Path(bundle_dir)
    (bundle_dir / "results" / "partial").mkdir(parents=True, exist_ok=True)

    now = _utc_now_iso()
    meta_path = bundle_dir / "metadata.json"
    metadata: dict = {}
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            metadata = {}

    metadata.setdefault("bundle_version", BUNDLE_VERSION)
    metadata.setdefault("created_at", now)
    metadata["benchmark"] = benchmark_name
    if experiment_name is not None:
        metadata.setdefault("experiment_name", experiment_name)
    metadata["status"] = "in_progress"
    history = metadata.get("resume_history") or []
    history.append({"started_at": now, "model_profile": model_profile})
    metadata["resume_history"] = history
    if args:
        run = metadata.get("run") or {}
        run.update(
            {
                "agent": args.get("agent", run.get("agent", "cuga_sdk")),
                # Fall back to the previously-recorded profile when this call
                # doesn't supply one (e.g. a --resume-experiment invocation
                # that omits --model-profile) instead of clobbering it with None.
                "model_profile": model_profile if model_profile is not None else run.get("model_profile"),
                "policies_enabled": not args.get("no_policies", False),
                # Same fallback as model_profile: preserve the previously-recorded
                # task_ids when this call (e.g. a --resume-experiment invocation
                # without task filtering) doesn't supply any.
                "task_ids": args.get("task_ids") if args.get("task_ids") is not None else run.get("task_ids"),
                "eval_key": args.get("eval_key"),
            }
        )
        metadata["run"] = run

    atomic_write_json(meta_path, metadata)
    return bundle_dir


def finalize_workspace_bundle(
    bundle_dir: Path,
    benchmark_name: str = "default",
    *,
    task_files: list[str | Path] | None = None,
    args: dict | None = None,
    model_profile: str | None = None,
    policies_dir: Path | None = None,
    trajectory_dir: Path | None = None,
    log_files: list[str | Path] | None = None,
    fetch_langfuse: bool = False,
    partial: bool = False,
    cuga_git_info: dict | None = None,
) -> Path:
    """Finalize a workspace bundle after the evaluator finishes (or is resumed).

    Idempotent and safe to re-run after ``--resume``: it only fills in what can't
    be produced incrementally -- ``report.md``, Langfuse traces (with
    ``skip_existing=True`` so a resume only fetches new traces), copied
    task/policy/trajectory/log artifacts, and the full ``metadata.json`` -- then
    flips the bundle status to ``completed`` (or ``partial``).
    """
    bundle_dir = Path(bundle_dir)
    benchmark_dir = PROJECT_ROOT / "benchmarks" / benchmark_name
    results_dir = bundle_dir / "results"
    result_files = sorted(str(p) for p in results_dir.glob("*.json"))
    args = args or {}

    # Tasks
    task_file_hashes: dict = {}
    for tf in task_files or []:
        tf = Path(tf)
        entry = _record_task_file(tf, bundle_dir / "tasks")
        if entry is not None:
            task_file_hashes[tf.name] = entry

    _copy_policies(bundle_dir, policies_dir)
    _copy_trajectories(bundle_dir, trajectory_dir)
    _traj_progress = bundle_dir / "trajectories" / ".progress"
    if _traj_progress.exists():
        shutil.copy2(_traj_progress, bundle_dir / ".progress")
    _copy_logs(bundle_dir, log_files)

    if fetch_langfuse and result_files:
        _download_langfuse_traces(bundle_dir, result_files, skip_existing=True)

    # Report (best-effort; a partial bundle should still report what it has)
    if result_files:
        try:
            from benchmarks.helpers.compare_report import generate_eval_report

            report = generate_eval_report(result_files[0])
            (bundle_dir / "report.md").write_text(report)
        except Exception as e:  # noqa: BLE001 — never let report gen fail finalization
            print(f"  Warning: report generation failed: {e}")

    _write_run_env(bundle_dir)
    settings_file = _copy_cuga_settings(bundle_dir, benchmark_dir)

    meta_path = bundle_dir / "metadata.json"
    metadata: dict = {}
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            metadata = {}

    now = _utc_now_iso()
    metadata.setdefault("bundle_version", BUNDLE_VERSION)
    metadata.setdefault("created_at", now)
    metadata["benchmark"] = benchmark_name
    metadata["finalized_at"] = now
    metadata["eval_repo"] = collect_repo_git_info()
    run = metadata.get("run") or {}
    run.update(
        {
            "agent": args.get("agent", run.get("agent", "cuga_sdk")),
            # Same fallback as create_workspace_bundle: don't clobber a
            # previously-recorded profile when this finalize call (e.g. after
            # a --resume-experiment that omitted --model-profile) doesn't
            # supply one.
            "model_profile": model_profile if model_profile is not None else run.get("model_profile"),
            "policies_enabled": not args.get("no_policies", False),
            "task_files": [str(Path(tf).name) for tf in (task_files or [])],
            "task_ids": args.get("task_ids"),
            "eval_key": args.get("eval_key"),
        }
    )
    metadata["run"] = run
    metadata["runtime_config"] = {
        "env_vars": collect_environment(),
        "settings_file": settings_file,
        "model_profile": model_profile,
    }
    metadata["model"] = {
        "model_name": os.environ.get("MODEL_NAME"),
        "agent_setting_config": os.environ.get("AGENT_SETTING_CONFIG"),
        "openai_base_url": os.environ.get("OPENAI_BASE_URL"),
        "openai_api_version": os.environ.get("OPENAI_API_VERSION"),
    }
    metadata["cuga"] = collect_cuga_info(cuga_git_info)
    metadata["policies"] = collect_policy_metadata(policies_dir)
    metadata["environment"] = collect_environment()
    metadata["ground_truth"] = {
        "task_count": len(task_files or []),
        "task_file_hashes": task_file_hashes,
    }
    metadata["status"] = "partial" if partial else "completed"

    atomic_write_json(meta_path, metadata)
    return bundle_dir


def zip_bundle(bundle_dir: Path) -> Path:
    archive = shutil.make_archive(str(bundle_dir), "zip", bundle_dir.parent, bundle_dir.name)
    return Path(archive)


# ---------------------------------------------------------------------------
# CLI — called from eval.sh / compare.sh for any benchmark
# ---------------------------------------------------------------------------


def cli():
    """CLI entry point.

    Usage::

        python -m benchmarks.helpers.bundle assemble \\
            --benchmark bpo --result-files r.json --task-files t.json [--zip]

        python -m benchmarks.helpers.bundle assemble-compare \\
            --benchmark bpo --config-results '{...}' --report r.md [--zip]
    """
    import argparse

    parser = argparse.ArgumentParser(description="Evaluation bundle CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- assemble (single-run) ---
    p_asm = sub.add_parser("assemble", help="Create single-run bundle")
    p_asm.add_argument("--benchmark", required=True)
    p_asm.add_argument("--result-files", nargs="+", required=True)
    p_asm.add_argument("--task-files", nargs="+", required=True)
    p_asm.add_argument("--model-profile", default=None)
    p_asm.add_argument("--no-policies", action="store_true")
    p_asm.add_argument(
        "--policies-dir", default=None, help="Path to policies directory (omit if benchmark has none)"
    )
    p_asm.add_argument("--task-ids", nargs="*", default=None)
    p_asm.add_argument(
        "--eval-key",
        default=None,
        help="Eval-config split used for this run (e.g. 'train'/'test'), recorded in bundle metadata",
    )
    p_asm.add_argument(
        "--trajectory-dir", default=None, help="Path to a specific trajectory folder to include"
    )
    p_asm.add_argument("--log-files", nargs="*", default=None, help="Log files to include in the bundle")
    p_asm.add_argument(
        "--fetch-langfuse", action="store_true", help="Download Langfuse traces for tasks that have trace IDs"
    )
    p_asm.add_argument("--report", default=None, help="Path to report.md to include in bundle")
    p_asm.add_argument(
        "--cuga-git-info",
        default=None,
        help='JSON {"git_commit", "git_branch", "git_dirty"} captured before the run started, e.g. by '
        "eval.sh. Overrides a live git query, which would otherwise reflect whatever is checked out "
        "in the cuga-agent repo at bundle-assembly time (after the run), not what actually ran.",
    )
    p_asm.add_argument("--zip", action="store_true")

    # --- assemble-compare ---
    p_cmp = sub.add_parser("assemble-compare", help="Create comparison bundle")
    p_cmp.add_argument("--benchmark", required=True)
    p_cmp.add_argument("--config-results", required=True, help='JSON: {"model:config": ["file.json", ...]}')
    p_cmp.add_argument("--report", default=None, help="Path to report.md")
    p_cmp.add_argument("--task-files", nargs="*", default=None)
    p_cmp.add_argument("--policies-dir", default=None)
    p_cmp.add_argument("--model-envs", default=None, help='JSON: {"model": {"MODEL_NAME": "...", ...}}')
    p_cmp.add_argument(
        "--trajectory-dirs",
        default=None,
        help='JSON grouped by run: {"model": [["/run1/domA", "/run1/domB"], ["/run2/domA"]]}. '
        'A flat {"model": ["/dir1", ...]} is still accepted (each dir treated as its own run).',
    )
    p_cmp.add_argument(
        "--log-files",
        default=None,
        help='JSON: {"model": ["/tmp/server.log", ...]} or space-separated paths for single-run',
    )
    p_cmp.add_argument(
        "--fetch-langfuse", action="store_true", help="Download Langfuse traces for tasks that have trace IDs"
    )
    p_cmp.add_argument(
        "--eval-key",
        default=None,
        help="Eval-config split used for these runs (e.g. 'train'/'test'), recorded in bundle metadata",
    )
    p_cmp.add_argument(
        "--cuga-git-info",
        default=None,
        help='JSON {"git_commit", "git_branch", "git_dirty"} captured before any run started, e.g. by '
        "compare.sh. Overrides a live git query, which would otherwise reflect whatever is checked out "
        "in the cuga-agent repo at bundle-assembly time (after all runs finish), not what actually ran "
        "-- a real risk for multi-run comparisons if the checkout is shared with other work.",
    )
    p_cmp.add_argument(
        "--bundle-dir",
        default=None,
        help="Finalize in place into this existing directory instead of creating a new "
        "timestamped one (workspace/experiment-mode compare runs).",
    )
    p_cmp.add_argument("--zip", action="store_true")

    # --- retry-langfuse (repair an existing bundle) ---
    p_rl = sub.add_parser("retry-langfuse", help="Fetch missing Langfuse traces for an existing bundle")
    p_rl.add_argument("--bundle-dir", required=True)
    p_rl.add_argument("--benchmark", default=None, help="Override benchmark (else read from metadata)")

    # --- regenerate-report (repair an existing bundle) ---
    p_rr = sub.add_parser(
        "regenerate-report", help="Regenerate report.md from an existing bundle's merged results"
    )
    p_rr.add_argument("--bundle-dir", required=True)
    p_rr.add_argument("--benchmark", default=None, help="Override benchmark (else read from metadata)")

    p_replay = sub.add_parser("replay", help="Reconstruct eval.sh argv from bundle metadata")
    p_replay.add_argument("--bundle-dir", required=True)
    p_replay.add_argument(
        "--format",
        choices=("argv", "shell", "json"),
        default="shell",
        help="Output format (default: shell comment + command)",
    )

    args = parser.parse_args()

    # Reload benchmark env from disk (dotenv strips inline comments). Shell-sourced
    # vars from eval.sh may include trailing comment text in values.
    benchmark_name = getattr(args, "benchmark", None)
    if not benchmark_name and getattr(args, "bundle_dir", None):
        try:
            _meta = json.loads((Path(args.bundle_dir) / "metadata.json").read_text())
            benchmark_name = _meta.get("benchmark")
        except (json.JSONDecodeError, OSError):
            benchmark_name = None
    _load_benchmark_env(benchmark_name or "default")

    policies_dir = Path(args.policies_dir) if getattr(args, "policies_dir", None) else None

    if args.command == "assemble":
        traj_dir = Path(args.trajectory_dir) if args.trajectory_dir else None
        report_content = None
        if args.report:
            rp = Path(args.report)
            if rp.exists():
                report_content = rp.read_text()
        bundle_dir = assemble_bundle(
            result_files=args.result_files,
            task_files=args.task_files,
            args={
                "no_policies": args.no_policies,
                "task_ids": getattr(args, "task_ids", None),
                "eval_key": getattr(args, "eval_key", None),
            },
            benchmark_name=args.benchmark,
            model_profile=args.model_profile,
            policies_dir=policies_dir,
            trajectory_dir=traj_dir,
            log_files=args.log_files,
            fetch_langfuse=args.fetch_langfuse,
            report_content=report_content,
            cuga_git_info=json.loads(args.cuga_git_info) if args.cuga_git_info else None,
        )
        print(f"Bundle created: {bundle_dir}")
        if args.zip:
            print(f"Bundle zipped: {zip_bundle(bundle_dir)}")

    elif args.command == "assemble-compare":
        config_results = json.loads(args.config_results)
        report_content = ""
        if args.report:
            report_path = Path(args.report)
            report_content = report_path.read_text() if report_path.exists() else ""
        task_file_paths = [Path(f) for f in args.task_files] if args.task_files else None
        model_envs = json.loads(args.model_envs) if args.model_envs else None
        traj_dirs = None
        if args.trajectory_dirs:
            raw = json.loads(args.trajectory_dirs)
            # Accept two shapes:
            #   grouped (preferred): {config: [[dir, ...run1], [dir, ...run2]]}
            #   legacy flat:         {config: [dir, dir, ...]}  -> each dir = 1 run
            traj_dirs = {}
            for k, v in raw.items():
                if v and isinstance(v[0], list):
                    traj_dirs[k] = [[Path(p) for p in group] for group in v]
                else:
                    traj_dirs[k] = [[Path(p)] for p in v]
        log_file_map = None
        if args.log_files:
            log_file_map = json.loads(args.log_files)
        bundle_dir = assemble_compare_bundle(
            report_content=report_content,
            config_results=config_results,
            benchmark_name=args.benchmark,
            task_files=task_file_paths,
            policies_dir=policies_dir,
            model_envs=model_envs,
            trajectory_dirs=traj_dirs,
            log_files=log_file_map,
            fetch_langfuse=args.fetch_langfuse,
            eval_key=getattr(args, "eval_key", None),
            cuga_git_info=json.loads(args.cuga_git_info) if args.cuga_git_info else None,
            bundle_dir_override=Path(args.bundle_dir) if getattr(args, "bundle_dir", None) else None,
        )
        print(f"Bundle created: {bundle_dir}")
        if args.zip:
            print(f"Bundle zipped: {zip_bundle(bundle_dir)}")

    elif args.command == "retry-langfuse":
        bundle_dir = Path(args.bundle_dir)
        result_files = sorted(str(p) for p in (bundle_dir / "results").glob("*.json"))
        if not result_files:
            print(f"No merged result files under {bundle_dir / 'results'}")
            return
        ok = _download_langfuse_traces(bundle_dir, result_files, skip_existing=True)
        print("Langfuse retry complete." if ok else "No new traces downloaded.")

    elif args.command == "regenerate-report":
        bundle_dir = Path(args.bundle_dir)
        result_files = sorted(str(p) for p in (bundle_dir / "results").glob("*.json"))
        if not result_files:
            print(f"No merged result files under {bundle_dir / 'results'}")
            return
        from benchmarks.helpers.compare_report import generate_eval_report

        report = generate_eval_report(result_files[0])
        (bundle_dir / "report.md").write_text(report)
        print(f"Report regenerated: {bundle_dir / 'report.md'}")

    elif args.command == "replay":
        from benchmarks.helpers.replay import cli_args_from_metadata, format_replay_command

        bundle_dir = Path(args.bundle_dir)
        meta_path = bundle_dir / "metadata.json"
        metadata = json.loads(meta_path.read_text())
        if args.format == "json":
            print(json.dumps({"argv": cli_args_from_metadata(metadata)}, indent=2))
        elif args.format == "argv":
            print(" ".join(cli_args_from_metadata(metadata)), end="")
        else:
            print(format_replay_command(metadata))


if __name__ == "__main__":
    cli()
