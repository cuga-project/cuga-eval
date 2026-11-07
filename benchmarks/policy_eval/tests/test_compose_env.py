import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "envs"))
import compose_env  # noqa: E402


def make_envs(tmp_path, **files):
    for name, text in files.items():
        (tmp_path / name.replace("__", ".")).write_text(text)
    return tmp_path


def parsed(path):
    return compose_env.parse_runner(Path(path).read_text())


def test_layers_apply_in_order_and_extra_wins(tmp_path):
    envs = make_envs(
        tmp_path,
        base__env="A=base\nB=base\nC=base\nD=base\nE=base\n",
        model__m__env="B=model\nC=model\nD=model\nE=model\n",
        bench__b__env="C=bench\nD=bench\nE=bench\n",
        pair__m__b__env="D=pair\nE=pair\n",
    )
    path = compose_env.compose("m", "b", {"E": "extra"}, envs_dir=envs, out_dir=tmp_path / "out")
    assert parsed(path) == {"A": "base", "B": "model", "C": "bench", "D": "pair", "E": "extra"}


def test_extra_none_removes_a_key_and_bool_is_lower_case(tmp_path):
    envs = make_envs(tmp_path, base__env="A=1\nB=2\n", model__m__env="C=3\n", bench__b__env="\n")
    path = compose_env.compose("m", "b", {"A": None, "FLAG": True}, envs_dir=envs, out_dir=tmp_path / "out")
    assert parsed(path) == {"B": "2", "C": "3", "FLAG": "true"}


def test_comments_are_ignored_like_the_runner(tmp_path):
    assert compose_env.parse_runner("# A=1\n  # B=2\nC = 3 \n\nD=x=y\n") == {"C": "3", "D": "x=y"}


def test_same_settings_give_the_same_file_and_other_settings_another(tmp_path):
    envs = make_envs(tmp_path, base__env="A=1\n", model__m__env="B=2\n", bench__b__env="\n")
    one = compose_env.compose("m", "b", None, envs_dir=envs, out_dir=tmp_path / "out")
    assert one == compose_env.compose("m", "b", {}, envs_dir=envs, out_dir=tmp_path / "out")
    assert one != compose_env.compose("m", "b", {"A": "2"}, envs_dir=envs, out_dir=tmp_path / "out")


def test_unknown_model_names_the_known_ones_and_secrets_are_refused(tmp_path):
    envs = make_envs(tmp_path, base__env="A=1\n", model__m__env="B=2\n", bench__b__env="\n")
    with pytest.raises(FileNotFoundError, match="known models: m"):
        compose_env.compose("nope", "b", None, envs_dir=envs, out_dir=tmp_path / "out")
    with pytest.raises(ValueError, match="looks like a secret"):
        compose_env.compose("m", "b", {"OPENAI_API_KEY": "x"}, envs_dir=envs, out_dir=tmp_path / "out")
    with pytest.raises(ValueError, match="bad model name"):
        compose_env.compose("../m", "b", None, envs_dir=envs, out_dir=tmp_path / "out")
