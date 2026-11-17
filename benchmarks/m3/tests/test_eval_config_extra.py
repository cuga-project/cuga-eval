"""--eval-key falls back to M3_EVAL_CONFIG_EXTRA for keys the main eval_config.toml lacks."""

import pytest

from benchmarks.m3.eval_config_loader import EXTRA_CONFIG_ENV, load_eval_key_ids

pytestmark = pytest.mark.sanity


def test_extra_config_serves_only_keys_the_main_config_lacks(tmp_path, monkeypatch):
    main = tmp_path / "eval_config.toml"
    main.write_text('train = ["a", "b"]\n')
    extra = tmp_path / "extra.toml"
    extra.write_text('zz_recover_x = ["c"]\ntrain = ["z"]\n')
    monkeypatch.delenv(EXTRA_CONFIG_ENV, raising=False)
    with pytest.raises(KeyError):
        load_eval_key_ids("zz_recover_x", main)
    monkeypatch.setenv(EXTRA_CONFIG_ENV, str(extra))
    assert load_eval_key_ids("zz_recover_x", main) == ["c"]
    assert load_eval_key_ids("train", main) == ["a", "b"]  # the main config wins
