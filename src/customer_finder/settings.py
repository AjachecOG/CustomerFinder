"""Settings and built-in / override YAML configuration loading."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from customer_finder.errors import ConfigError
from customer_finder.models import (
    CategoriesConfig,
    CategoryMapping,
    ChainDenylistConfig,
    DomainRulesConfig,
    TaxonomySnapshotConfig,
)

CONFIG_FILENAMES: tuple[str, ...] = (
    "categories.yml",
    "domain_rules.yml",
    "chain_denylist.yml",
    "taxonomy_snapshot.yml",
)

_HOST_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Validated in-memory configuration set."""

    categories: CategoriesConfig
    domain_rules: DomainRulesConfig
    chain_denylist: ChainDenylistConfig
    taxonomy_snapshot: TaxonomySnapshotConfig
    source_dir: Path | None
    """None means built-in package resources; otherwise the override directory."""

    def category_aliases(self) -> list[str]:
        return sorted(self.categories.categories.keys())

    def resolve_category_alias(
        self,
        *,
        basic_category: str | None,
        taxonomy_primary: str | None,
        taxonomy_hierarchy: list[str],
        taxonomy_alternates: list[str],
    ) -> str | None:
        """Pick highest score_weight alias; alphabetical on ties."""
        codes = {
            c
            for c in (
                basic_category,
                taxonomy_primary,
                *taxonomy_hierarchy,
                *taxonomy_alternates,
            )
            if c
        }
        matches: list[tuple[int, str]] = []
        for alias, mapping in self.categories.categories.items():
            mapped = set(mapping.overture_basic) | set(mapping.overture_taxonomy)
            if codes & mapped:
                matches.append((mapping.score_weight, alias))
        if not matches:
            return None
        # Highest weight first; alphabetical alias on tie.
        matches.sort(key=lambda item: (-item[0], item[1]))
        return matches[0][1]

    def mapping_for(self, alias: str) -> CategoryMapping:
        try:
            return self.categories.categories[alias]
        except KeyError as exc:
            raise ConfigError(
                f"Unknown category alias '{alias}'",
                field="categories",
            ) from exc


def _package_config_text(filename: str) -> str:
    root = resources.files("customer_finder.config")
    path = root.joinpath(filename)
    if not path.is_file():
        raise ConfigError(
            f"Built-in config file missing: {filename}",
            path=f"customer_finder.config/{filename}",
        )
    return path.read_text(encoding="utf-8")


def _read_yaml(text: str, *, path_label: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML: {exc}", path=path_label) from exc
    if data is None:
        raise ConfigError("YAML document is empty", path=path_label)
    if not isinstance(data, dict):
        raise ConfigError("YAML root must be a mapping", path=path_label)
    return data


def _validation_error(exc: ValidationError, *, path_label: str) -> ConfigError:
    first = exc.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", ())) or None
    msg = first.get("msg", "validation failed")
    return ConfigError(msg, path=path_label, field=loc)


def _normalize_host(raw: str, *, path_label: str, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError("Host entry must be a non-empty string", path=path_label, field=field)
    host = raw.strip().lower().rstrip(".")
    if host.startswith("www."):
        raise ConfigError(
            "Host must be normalized without www. prefix",
            path=path_label,
            field=field,
        )
    if any(ch.isupper() for ch in raw.strip().rstrip(".")):
        raise ConfigError(
            "Host must be lowercase",
            path=path_label,
            field=field,
        )
    if raw.strip().endswith("."):
        raise ConfigError(
            "Host must not end with a trailing dot",
            path=path_label,
            field=field,
        )
    if not _HOST_RE.match(host) and host != "localhost":
        raise ConfigError(
            f"Host is not a valid hostname: {raw!r}",
            path=path_label,
            field=field,
        )
    return host


def _load_categories(data: dict[str, Any], *, path_label: str) -> CategoriesConfig:
    if "version" not in data:
        raise ConfigError("Missing version", path=path_label, field="version")
    try:
        cfg = CategoriesConfig.model_validate(data)
    except ValidationError as exc:
        raise _validation_error(exc, path_label=path_label) from exc
    return cfg


def _load_domain_rules(data: dict[str, Any], *, path_label: str) -> DomainRulesConfig:
    try:
        cfg = DomainRulesConfig.model_validate(data)
    except ValidationError as exc:
        raise _validation_error(exc, path_label=path_label) from exc

    lists: dict[str, list[str]] = {
        "social_hosts": cfg.social_hosts,
        "aggregator_hosts": cfg.aggregator_hosts,
        "ignored_hosts": cfg.ignored_hosts,
    }
    normalized: dict[str, list[str]] = {}
    seen_host_owner: dict[str, str] = {}
    for field_name, hosts in lists.items():
        out: list[str] = []
        for host in hosts:
            norm = _normalize_host(host, path_label=path_label, field=field_name)
            if norm in seen_host_owner:
                raise ConfigError(
                    f"Host '{norm}' appears in both {seen_host_owner[norm]} and {field_name}",
                    path=path_label,
                    field=field_name,
                )
            seen_host_owner[norm] = field_name
            out.append(norm)
        normalized[field_name] = out
    return DomainRulesConfig.model_validate(normalized)


def _load_chain_denylist(data: dict[str, Any], *, path_label: str) -> ChainDenylistConfig:
    try:
        cfg = ChainDenylistConfig.model_validate(data)
    except ValidationError as exc:
        raise _validation_error(exc, path_label=path_label) from exc

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in cfg.chains:
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigError(
                "Chain name must be a non-empty string",
                path=path_label,
                field="chains",
            )
        # Same name normalization used later for matching (NFKC + lower + punct).
        name = " ".join(
            "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in raw).split()
        )
        if not name:
            raise ConfigError(
                "Chain name normalizes to empty",
                path=path_label,
                field="chains",
            )
        if name in seen:
            raise ConfigError(
                f"Duplicate chain name after normalization: {raw!r}",
                path=path_label,
                field="chains",
            )
        seen.add(name)
        normalized.append(raw.strip())
    return ChainDenylistConfig(chains=normalized)


def _load_taxonomy_snapshot(data: dict[str, Any], *, path_label: str) -> TaxonomySnapshotConfig:
    try:
        return TaxonomySnapshotConfig.model_validate(data)
    except ValidationError as exc:
        raise _validation_error(exc, path_label=path_label) from exc


def _cross_check_categories_against_snapshot(
    categories: CategoriesConfig,
    snapshot: TaxonomySnapshotConfig,
    *,
    categories_path: str,
    snapshot_path: str,
) -> None:
    if categories.validated_against_schema != snapshot.schema_version:
        raise ConfigError(
            "validated_against_schema must equal taxonomy snapshot schema_version",
            path=categories_path,
            field="validated_against_schema",
        )

    approved_basic = set(snapshot.approved_basic)
    approved_taxonomy = set(snapshot.approved_taxonomy)

    for alias, mapping in categories.categories.items():
        for code in mapping.overture_basic:
            if code not in approved_basic:
                raise ConfigError(
                    f"Category '{alias}' uses basic code '{code}' missing from taxonomy snapshot",
                    path=categories_path,
                    field=f"categories.{alias}.overture_basic",
                )
        for code in mapping.overture_taxonomy:
            if code not in approved_taxonomy:
                raise ConfigError(
                    f"Category '{alias}' uses taxonomy code '{code}' "
                    f"missing from taxonomy snapshot",
                    path=categories_path,
                    field=f"categories.{alias}.overture_taxonomy",
                )

    # Snapshot should not claim unused review without categories reference,
    # but extra approved codes are allowed as evidence buffer.
    _ = snapshot_path


def _load_from_texts(
    texts: dict[str, str],
    *,
    path_labels: dict[str, str],
    source_dir: Path | None,
) -> AppConfig:
    categories = _load_categories(
        _read_yaml(texts["categories.yml"], path_label=path_labels["categories.yml"]),
        path_label=path_labels["categories.yml"],
    )
    domain_rules = _load_domain_rules(
        _read_yaml(texts["domain_rules.yml"], path_label=path_labels["domain_rules.yml"]),
        path_label=path_labels["domain_rules.yml"],
    )
    chain_denylist = _load_chain_denylist(
        _read_yaml(texts["chain_denylist.yml"], path_label=path_labels["chain_denylist.yml"]),
        path_label=path_labels["chain_denylist.yml"],
    )
    taxonomy_snapshot = _load_taxonomy_snapshot(
        _read_yaml(
            texts["taxonomy_snapshot.yml"],
            path_label=path_labels["taxonomy_snapshot.yml"],
        ),
        path_label=path_labels["taxonomy_snapshot.yml"],
    )
    _cross_check_categories_against_snapshot(
        categories,
        taxonomy_snapshot,
        categories_path=path_labels["categories.yml"],
        snapshot_path=path_labels["taxonomy_snapshot.yml"],
    )
    return AppConfig(
        categories=categories,
        domain_rules=domain_rules,
        chain_denylist=chain_denylist,
        taxonomy_snapshot=taxonomy_snapshot,
        source_dir=source_dir,
    )


@lru_cache(maxsize=1)
def load_builtin_config() -> AppConfig:
    """Load the four packaged YAML files and cross-validate them."""
    texts = {name: _package_config_text(name) for name in CONFIG_FILENAMES}
    labels = {name: f"customer_finder.config/{name}" for name in CONFIG_FILENAMES}
    return _load_from_texts(texts, path_labels=labels, source_dir=None)


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Load built-in config or a complete override directory (no mixing)."""
    if config_dir is None:
        return load_builtin_config()

    directory = config_dir.expanduser().resolve()
    if not directory.is_dir():
        raise ConfigError(
            "config_dir must be an existing directory",
            path=str(directory),
        )

    texts: dict[str, str] = {}
    labels: dict[str, str] = {}
    missing: list[str] = []
    for name in CONFIG_FILENAMES:
        path = directory / name
        labels[name] = str(path)
        if not path.is_file():
            missing.append(name)
            continue
        texts[name] = path.read_text(encoding="utf-8")
    if missing:
        raise ConfigError(
            "config_dir must contain the complete YAML set; missing: " + ", ".join(missing),
            path=str(directory),
        )
    return _load_from_texts(texts, path_labels=labels, source_dir=directory)


def validate_category_aliases(
    aliases: list[str], config: AppConfig, *, path: str | None = None
) -> list[str]:
    """Ensure every alias exists in categories.yml; return aliases unchanged."""
    known = set(config.categories.categories)
    for alias in aliases:
        if alias not in known:
            raise ConfigError(
                f"Unknown category alias '{alias}'",
                path=path,
                field="categories",
            )
    return aliases
