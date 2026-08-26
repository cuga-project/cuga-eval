"""Regression tests for issue #134: collect_cuga_info() used to guess a fixed
CUGA_REPO_PATH/~/workspace/cuga-agent path and silently return no git info at
all when the real checkout lived anywhere else — even though the live 'cuga'
package (once imported) already knows exactly where it is.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from benchmarks.helpers import bundle

pytestmark = pytest.mark.sanity


def _fake_cuga_module(file_path: str) -> types.ModuleType:
    mod = types.ModuleType("cuga")
    mod.__version__ = "0.9.9-test"
    mod.__file__ = file_path
    return mod


@pytest.fixture
def fake_cuga(monkeypatch):
    """Install a fake 'cuga' module and remove it afterward, regardless of
    outcome, so this test can't leak a stub into other tests' `import cuga`."""

    def _install(file_path: str):
        mod = _fake_cuga_module(file_path)
        monkeypatch.setitem(sys.modules, "cuga", mod)
        return mod

    yield _install


def test_git_info_passed_explicitly_is_used_as_is(monkeypatch):
    monkeypatch.setattr(
        bundle, "_run_git", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not shell out"))
    )
    info = bundle.collect_cuga_info(
        git_info={"git_commit": "abc123", "git_branch": "main", "git_dirty": False}
    )
    assert info["git_commit"] == "abc123"
    assert info["git_branch"] == "main"
    assert info["git_dirty"] is False


def test_resolves_via_live_checkout_not_the_guessed_path(monkeypatch, fake_cuga, tmp_path):
    live_repo = tmp_path / "not_workspace" / "cuga-agent"
    (live_repo / "src" / "cuga").mkdir(parents=True)
    fake_cuga(str(live_repo / "src" / "cuga" / "__init__.py"))

    guessed_repo = tmp_path / "workspace" / "cuga-agent"
    guessed_repo.mkdir(parents=True)
    monkeypatch.setenv("CUGA_REPO_PATH", str(guessed_repo))

    def fake_run_git(args, cwd=None):
        if args == ["rev-parse", "--show-toplevel"]:
            assert Path(cwd) == live_repo / "src" / "cuga"
            return str(live_repo)
        assert Path(cwd) == live_repo, f"expected git ops against the live repo, got {cwd}"
        if args == ["rev-parse", "--short", "HEAD"]:
            return "deadbee"
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "feature/live"
        if args == ["status", "--short"]:
            return ""
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(bundle, "_run_git", fake_run_git)

    info = bundle.collect_cuga_info()

    assert info["git_commit"] == "deadbee"
    assert info["git_branch"] == "feature/live"
    assert info["git_dirty"] is False
    assert info["version"] == "0.9.9-test"


def test_falls_back_to_cuga_repo_path_when_live_checkout_has_no_git_root(monkeypatch, fake_cuga, tmp_path):
    live_dir = tmp_path / "site-packages" / "cuga"  # non-editable install, no .git
    live_dir.mkdir(parents=True)
    fake_cuga(str(live_dir / "__init__.py"))

    guessed_repo = tmp_path / "workspace" / "cuga-agent"
    guessed_repo.mkdir(parents=True)
    monkeypatch.setenv("CUGA_REPO_PATH", str(guessed_repo))

    def fake_run_git(args, cwd=None):
        if args == ["rev-parse", "--show-toplevel"]:
            return None  # not inside a git repo
        assert Path(cwd) == guessed_repo
        if args == ["rev-parse", "--short", "HEAD"]:
            return "f00d123"
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "main"
        if args == ["status", "--short"]:
            return ""
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(bundle, "_run_git", fake_run_git)

    info = bundle.collect_cuga_info()

    assert info["git_commit"] == "f00d123"
    assert info["git_branch"] == "main"


def test_warns_and_leaves_git_fields_absent_when_nothing_resolves(monkeypatch, fake_cuga, tmp_path, caplog):
    live_dir = tmp_path / "site-packages" / "cuga"
    live_dir.mkdir(parents=True)
    fake_cuga(str(live_dir / "__init__.py"))
    monkeypatch.setenv("CUGA_REPO_PATH", str(tmp_path / "does_not_exist"))
    monkeypatch.setattr(bundle, "_run_git", lambda args, cwd=None: None)

    warnings = []
    monkeypatch.setattr(bundle.logger, "warning", lambda msg: warnings.append(msg))

    info = bundle.collect_cuga_info()

    assert "git_commit" not in info
    assert "git_branch" not in info
    assert warnings, "expected a warning when cuga git info could not be resolved"
    assert "could not resolve cuga-agent's git info" in warnings[0]


def test_import_error_falls_back_to_guessed_path_only(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "cuga", None)  # forces ImportError on `import cuga`

    guessed_repo = tmp_path / "workspace" / "cuga-agent"
    guessed_repo.mkdir(parents=True)
    monkeypatch.setenv("CUGA_REPO_PATH", str(guessed_repo))

    calls = []

    def fake_run_git(args, cwd=None):
        calls.append((tuple(args), cwd))
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc0000"
        return ""

    monkeypatch.setattr(bundle, "_run_git", fake_run_git)

    info = bundle.collect_cuga_info()

    assert info["version"] is None
    assert info["git_commit"] == "abc0000"
    # Never asked git for a --show-toplevel, since there's no live module path to ask from.
    assert all(args != ("rev-parse", "--show-toplevel") for args, _cwd in calls)
