"""Configuration validation.

The failure that motivated this file: a `settings.yaml` containing a YAML
typo parsed to something unusable, every lookup quietly fell back to a
hard-coded default, and the daily spend cap silently became $5 while the file
plainly said $6. Exit code 0. A benchmark that spends a different amount of
money than its own configuration states, and says nothing about it, has no
standing to publish reliability numbers about anyone else.
"""
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
import yaml

from tti import config

GOOD = {
    "ladder": [300, 900, 3600],
    "daily_usd_cap": 6.0,
    "max_detection_lag_seconds": 600,
    "max_rung_slip_seconds": 600,
    "sources": ["npm"],
    "arms": [{"provider": "p", "mode": "base"}],
}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A writable copy of the shipped config, with the cache cleared."""
    d = tmp_path / "data"
    shutil.copytree(config.DATA, d)
    monkeypatch.setattr(config, "DATA", d)
    config._cache.clear()
    yield d
    config._cache.clear()


def write(data_dir, name, obj):
    p = data_dir / f"{name}.yaml"
    p.write_text(obj if isinstance(obj, str) else yaml.safe_dump(obj))


def test_the_shipped_configuration_is_valid():
    """If this fails, the repository ships something it would reject."""
    config._cache.clear()
    assert config.check_all() == []


def test_a_valid_settings_file_loads(data_dir):
    write(data_dir, "settings", GOOD)
    assert config.settings()["daily_usd_cap"] == 6.0


@pytest.mark.parametrize("mutate,fragment", [
    (lambda s: s.update(daily_usd_cap=-3), "positive number of dollars"),
    (lambda s: s.update(daily_usd_cap="5"), "positive number of dollars"),
    (lambda s: s.update(daily_usd_cap=0), "positive number of dollars"),
    (lambda s: s.update(ladder=[900, 300]), "strictly increasing"),
    (lambda s: s.update(ladder=[300, 300]), "strictly increasing"),
    (lambda s: s.update(ladder=[]), "non-empty list"),
    (lambda s: s.update(ladder=[-5]), "positive whole seconds"),
    (lambda s: s.update(max_results=0), "between 1 and 100"),
    (lambda s: s.update(arms=[{"provider": "p"}]), "needs `provider` and `mode`"),
    (lambda s: s.update(sources="npm"), "must be a list"),
])
def test_bad_settings_are_rejected(data_dir, mutate, fragment):
    s = dict(GOOD)
    mutate(s)
    write(data_dir, "settings", s)
    with pytest.raises(config.ConfigError) as e:
        config.settings()
    assert fragment in str(e.value)


def test_detection_lag_may_exceed_the_first_rung(data_dir):
    """It is not an error. A late-detected event still fires its first rung,
    and `run_due` records the true elapsed lag rather than the rung's nominal
    one, which the interval-censored estimator handles correctly. An earlier
    version of this validator rejected the shipped config over exactly this."""
    write(data_dir, "settings", {**GOOD, "max_detection_lag_seconds": 600,
                                 "ladder": [300, 900], "max_rung_slip_seconds": 600})
    assert config.settings()["max_detection_lag_seconds"] == 600


def test_detection_so_late_that_the_first_rung_can_never_fire_is_rejected(data_dir):
    """What actually breaks: the shortest measurable latency silently becomes
    the second rung."""
    write(data_dir, "settings", {**GOOD, "max_detection_lag_seconds": 5000,
                                 "ladder": [300, 900], "max_rung_slip_seconds": 600})
    with pytest.raises(config.ConfigError) as e:
        config.settings()
    assert "silently become the second rung" in str(e.value)


def test_phrasing_rungs_must_exist_in_the_ladder(data_dir):
    write(data_dir, "settings", {**GOOD,
                                 "phrasing_probe": {"enabled": True, "rungs": [7777]}})
    with pytest.raises(config.ConfigError) as e:
        config.settings()
    assert "never be scheduled" in str(e.value)


@pytest.mark.parametrize("body,fragment", [
    ("", "is empty"),
    ("a: [1,\nb: :", "not valid YAML"),
    ("just a string", "expected a mapping"),
])
def test_unusable_files_are_rejected_rather_than_defaulted(data_dir, body, fragment):
    write(data_dir, "settings", body)
    with pytest.raises(config.ConfigError) as e:
        config.settings()
    assert fragment in str(e.value)


def test_a_missing_file_is_named(data_dir):
    (data_dir / "settings.yaml").unlink()
    with pytest.raises(config.ConfigError) as e:
        config.settings()
    assert "is missing" in str(e.value)


def test_an_unpriced_arm_is_rejected(data_dir):
    """An arm with no price spends against a cap that cannot see it."""
    write(data_dir, "providers", {"providers": {"x": {"modes": {"base": {}}}}})
    with pytest.raises(config.ConfigError) as e:
        config.providers_config()
    assert "cap that cannot see it" in str(e.value)


def test_corpus_entries_must_be_absolute_urls(data_dir):
    write(data_dir, "corpus", {"docs": ["not-a-url"]})
    with pytest.raises(config.ConfigError) as e:
        config.load("corpus")
    assert "absolute http(s) URL" in str(e.value)


def test_edgar_rows_need_cik_and_name(data_dir):
    write(data_dir, "watchlist", {"edgar": [{"cik": "1"}]})
    with pytest.raises(config.ConfigError) as e:
        config.watchlist()
    assert "needs `cik` and `name`" in str(e.value)


def test_check_all_collects_every_problem(data_dir):
    write(data_dir, "settings", {**GOOD, "daily_usd_cap": -1})
    write(data_dir, "corpus", {"docs": ["nope"]})
    problems = config.check_all()
    assert len(problems) == 2
    assert any("settings" in p for p in problems)
    assert any("corpus" in p for p in problems)


def test_the_cli_reports_a_config_error_as_exit_two(data_dir, capsys):
    """Distinct from exit 1, so a cron wrapper can tell 'misconfigured' from
    'ran and found nothing'."""
    from tti.cli import main
    write(data_dir, "settings", {**GOOD, "daily_usd_cap": -1})
    assert main(["status"]) == 2
    assert "configuration error" in capsys.readouterr().err
