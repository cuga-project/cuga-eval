"""Sanity: mcp_servers_appworld.yaml api_overrides must match real AppWorld ops.

Overrides that miss an operation_id or mis-classify query vs body fail silently
upstream (get_operation_override_parameters returns None), so the agent is asked
for file_system_access_token again with no obvious cause. This test pins the
yaml against the FastAPI-generated ids in the vendored appworld package.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Literal, Set, Tuple

import pytest
import yaml

pytestmark = pytest.mark.sanity

_TOKEN = "file_system_access_token"
_YAML = Path(__file__).parent.parent / "mcp_servers_appworld.yaml"
_APPS_ROOT = Path(__file__).parent.parent / "appworld" / "src" / "appworld" / "apps"

ParamKind = Literal["query", "body"]


def _operation_id(route_name: str, path: str, method: str) -> str:
    return route_name + re.sub(r"[^0-9a-zA-Z_]", "_", path) + "_" + method


def _decorator_route(decorator: ast.AST) -> Tuple[str, str] | None:
    """Return (http_method, path) for @app.get/post/... decorators."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "app"):
        return None
    method = func.attr.lower()
    if method not in {"get", "post", "put", "delete", "patch"}:
        return None
    if not decorator.args:
        return None
    path_node = decorator.args[0]
    if not isinstance(path_node, ast.Constant) or not isinstance(path_node.value, str):
        return None
    return method, path_node.value


def _param_kind(default: ast.AST | None) -> ParamKind | None:
    if default is None:
        return None
    call = default
    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
        name = call.func.id
        if name == "Query":
            return "query"
        if name == "Body":
            return "body"
    return None


def _fs_token_endpoints(apis_py: Path) -> Dict[str, ParamKind]:
    """Map FastAPI operation_id -> query|body for file_system_access_token params."""
    tree = ast.parse(apis_py.read_text())
    found: Dict[str, ParamKind] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        route = None
        for dec in node.decorator_list:
            route = _decorator_route(dec)
            if route:
                break
        if route is None:
            continue
        method, path = route
        for arg in node.args.args:
            if arg.arg != _TOKEN:
                continue
            # Match default to this arg by position among args (no kwonly here).
            # Defaults align to the end of args.
            positional = node.args.args
            defaults = node.args.defaults
            idx = positional.index(arg)
            default_offset = len(positional) - len(defaults)
            default = defaults[idx - default_offset] if idx >= default_offset else None
            kind = _param_kind(default)
            if kind is None:
                raise AssertionError(
                    f"{apis_py}: {_TOKEN} on {node.name} is neither Query(...) nor Body(...)"
                )
            op_id = _operation_id(node.name, path, method)
            found[op_id] = kind
    return found


def _all_fs_token_endpoints() -> Dict[str, Tuple[str, ParamKind]]:
    """operation_id -> (app_name, kind), skipping apps without apis.py."""
    if not _APPS_ROOT.is_dir():
        pytest.skip(
            f"AppWorld sources missing at {_APPS_ROOT}; run ./setup_appworld.sh first"
        )
    out: Dict[str, Tuple[str, ParamKind]] = {}
    for app_dir in sorted(_APPS_ROOT.iterdir()):
        apis_py = app_dir / "apis.py"
        if not apis_py.is_file():
            continue
        for op_id, kind in _fs_token_endpoints(apis_py).items():
            out[op_id] = (app_dir.name, kind)
    return out


def _yaml_overrides() -> Dict[str, Tuple[str, Set[str], Set[str]]]:
    """operation_id -> (app_name, drop_query, drop_body)."""
    data = yaml.safe_load(_YAML.read_text())
    out: Dict[str, Tuple[str, Set[str], Set[str]]] = {}
    for entry in data.get("services") or []:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        app_name, cfg = next(iter(entry.items()))
        if not isinstance(cfg, dict):
            continue
        for override in cfg.get("api_overrides") or []:
            op_id = override.get("operation_id")
            if not op_id:
                continue
            out[op_id] = (
                app_name,
                set(override.get("drop_query_parameters") or []),
                set(override.get("drop_request_body_parameters") or []),
            )
    return out


@pytest.fixture(scope="module")
def endpoints():
    return _all_fs_token_endpoints()


@pytest.fixture(scope="module")
def overrides():
    return _yaml_overrides()


def test_every_override_resolves_to_a_real_operation(endpoints, overrides):
    unknown = sorted(op for op in overrides if op not in endpoints)
    assert not unknown, (
        "api_overrides operation_ids that match no AppWorld route "
        f"(silent no-op at runtime): {unknown}"
    )


def test_override_drop_kind_matches_param_declaration(endpoints, overrides):
    mismatches = []
    for op_id, (app_name, drop_query, drop_body) in overrides.items():
        if op_id not in endpoints:
            continue
        _app, kind = endpoints[op_id]
        drops_token_query = _TOKEN in drop_query
        drops_token_body = _TOKEN in drop_body
        if kind == "query" and not drops_token_query:
            mismatches.append(f"{app_name}/{op_id}: param is Query but not in drop_query_parameters")
        if kind == "query" and drops_token_body:
            mismatches.append(f"{app_name}/{op_id}: param is Query but listed in drop_request_body_parameters")
        if kind == "body" and not drops_token_body:
            mismatches.append(f"{app_name}/{op_id}: param is Body but not in drop_request_body_parameters")
        if kind == "body" and drops_token_query:
            mismatches.append(f"{app_name}/{op_id}: param is Body but listed in drop_query_parameters")
    assert not mismatches, "Mis-classified drop_* for file_system_access_token:\n" + "\n".join(mismatches)


def test_every_fs_token_endpoint_has_an_override(endpoints, overrides):
    missing = sorted(
        f"{app}/{op_id} ({kind})"
        for op_id, (app, kind) in endpoints.items()
        if op_id not in overrides
    )
    assert not missing, (
        "AppWorld endpoints declaring file_system_access_token without an "
        f"api_overrides entry: {missing}"
    )
