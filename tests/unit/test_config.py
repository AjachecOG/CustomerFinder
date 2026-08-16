"""Unit tests for YAML configuration loading (Milestone 1)."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from typer.testing import CliRunner

from customer_finder.cli import app
from customer_finder.errors import ConfigError, ExitCode
from customer_finder.settings import (
    CONFIG_FILENAMES,
    load_builtin_config,
    load_config,
    validate_category_aliases,
)

runner = CliRunner()


def _write_full_config(directory: Path, **overrides: str) -> None:
    builtin = load_builtin_config()
    # Start from built-in files via package resources by dumping validated models.
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        text = overrides.get(name) or root.joinpath(name).read_text(encoding="utf-8")
        (directory / name).write_text(text, encoding="utf-8")
    _ = builtin


def test_builtin_config_loads_and_matches_snapshot() -> None:
    cfg = load_builtin_config()
    assert cfg.categories.validated_against_schema == cfg.taxonomy_snapshot.schema_version
    assert set(cfg.categories.categories) >= {"cafe", "bakery", "pastry", "ice_cream"}
    for mapping in cfg.categories.categories.values():
        for code in mapping.overture_basic:
            assert code in cfg.taxonomy_snapshot.approved_basic
        for code in mapping.overture_taxonomy:
            assert code in cfg.taxonomy_snapshot.approved_taxonomy


def test_resolve_category_alias_prefers_higher_weight_then_alpha() -> None:
    cfg = load_builtin_config()
    # pastry weight 25 beats cafe weight 20 if both somehow matched; bakery 18.
    alias = cfg.resolve_category_alias(
        basic_category=None,
        taxonomy_primary="bakery",
        taxonomy_hierarchy=["food_and_drink", "casual_eatery", "bakery"],
        taxonomy_alternates=[],
    )
    assert alias == "bakery"


def test_resolve_category_alias_tie_breaks_alphabetically(tmp_path: Path) -> None:
    categories = dedent(
        """\
        version: 1
        validated_against_schema: "1.18.0"
        categories:
          zeta:
            display_name: Z
            overture_basic: []
            overture_taxonomy: [shared_code]
            score_weight: 10
          alpha:
            display_name: A
            overture_basic: []
            overture_taxonomy: [shared_code]
            score_weight: 10
        """
    )
    snapshot = dedent(
        """\
        schema_version: "1.18.0"
        reviewed_at: "2026-08-11"
        evidence_urls: ["https://docs.overturemaps.org/guides/places/taxonomy/"]
        approved_basic: []
        approved_taxonomy: [shared_code]
        """
    )
    _write_full_config(
        tmp_path,
        **{"categories.yml": categories, "taxonomy_snapshot.yml": snapshot},
    )
    cfg = load_config(tmp_path)
    assert (
        cfg.resolve_category_alias(
            basic_category=None,
            taxonomy_primary="shared_code",
            taxonomy_hierarchy=[],
            taxonomy_alternates=[],
        )
        == "alpha"
    )


def test_config_dir_missing_file_is_error(tmp_path: Path) -> None:
    (tmp_path / "categories.yml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.exit_code == ExitCode.CONFIG
    assert "missing" in exc.value.message.lower()
    assert str(tmp_path) in exc.value.message


def test_unknown_yaml_field_reports_path_and_field(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    data = yaml.safe_load((tmp_path / "categories.yml").read_text(encoding="utf-8"))
    data["unexpected_top_level"] = True
    (tmp_path / "categories.yml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.path == str(tmp_path / "categories.yml")
    assert exc.value.field == "unexpected_top_level"


def test_duplicate_host_across_lists_rejected(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    bad = dedent(
        """\
        social_hosts: [facebook.com]
        aggregator_hosts: [facebook.com]
        ignored_hosts: [localhost]
        """
    )
    (tmp_path / "domain_rules.yml").write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert "facebook.com" in exc.value.message
    assert exc.value.path == str(tmp_path / "domain_rules.yml")


@pytest.mark.parametrize(
    "host",
    ["Facebook.com", "www.facebook.com", "facebook.com."],
)
def test_unnormalized_host_rejected(tmp_path: Path, host: str) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    bad = f"social_hosts:\n  - {host}\naggregator_hosts: []\nignored_hosts:\n  - localhost\n"
    (tmp_path / "domain_rules.yml").write_text(bad, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.path == str(tmp_path / "domain_rules.yml")


def test_duplicate_chain_after_normalization_rejected(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (tmp_path / "chain_denylist.yml").write_text(
        "chains:\n  - Starbucks\n  - starbucks!\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.path == str(tmp_path / "chain_denylist.yml")
    assert exc.value.field == "chains"


def test_schema_mismatch_between_categories_and_snapshot(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        text = root.joinpath(name).read_text(encoding="utf-8")
        (tmp_path / name).write_text(text, encoding="utf-8")
    snap = yaml.safe_load((tmp_path / "taxonomy_snapshot.yml").read_text(encoding="utf-8"))
    snap["schema_version"] = "0.0.0"
    (tmp_path / "taxonomy_snapshot.yml").write_text(
        yaml.safe_dump(snap, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.field == "validated_against_schema"


def test_code_missing_from_snapshot_rejected(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    cats = yaml.safe_load((tmp_path / "categories.yml").read_text(encoding="utf-8"))
    cats["categories"]["cafe"]["overture_taxonomy"].append("not_a_real_code")
    (tmp_path / "categories.yml").write_text(
        yaml.safe_dump(cats, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert "not_a_real_code" in exc.value.message
    assert "overture_taxonomy" in (exc.value.field or "")


def test_score_weight_out_of_range_rejected(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    cats = yaml.safe_load((tmp_path / "categories.yml").read_text(encoding="utf-8"))
    cats["categories"]["cafe"]["score_weight"] = 99
    (tmp_path / "categories.yml").write_text(
        yaml.safe_dump(cats, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert exc.value.path == str(tmp_path / "categories.yml")
    assert "score_weight" in (exc.value.field or "")


def test_validate_category_aliases_unknown() -> None:
    cfg = load_builtin_config()
    with pytest.raises(ConfigError):
        validate_category_aliases(["cafe", "not-real"], cfg)


def test_builtin_target_categories_exclude_tea_rooms() -> None:
    config = load_builtin_config()

    assert (
        config.resolve_category_alias(
            basic_category=None,
            taxonomy_primary="tea_room",
            taxonomy_hierarchy=[],
            taxonomy_alternates=[],
        )
        is None
    )


def test_cli_config_validate_builtin_ok() -> None:
    result = runner.invoke(app, ["config", "validate"])
    assert result.exit_code == 0
    assert "OK" in result.stdout
    assert "1.18.0" in result.stdout


def test_cli_config_validate_reports_path_on_error(tmp_path: Path) -> None:
    from importlib import resources

    root = resources.files("customer_finder.config")
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(
            root.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (tmp_path / "domain_rules.yml").write_text(
        "social_hosts: [Not A Host]\naggregator_hosts: []\nignored_hosts: [localhost]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["config", "validate", "--config-dir", str(tmp_path)])
    assert result.exit_code == ExitCode.CONFIG
    assert str(tmp_path / "domain_rules.yml") in result.output
