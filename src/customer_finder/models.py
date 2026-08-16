"""Pydantic v2 data contracts for Customer Finder."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# Poland MVP bounds (implementation plan §6.1).
_PL_LAT_MIN = 48.8
_PL_LAT_MAX = 55.1
_PL_LON_MIN = 13.8
_PL_LON_MAX = 24.5
_RADIUS_KM_MAX = 10.0


class CandidateBucket(StrEnum):
    """Classification buckets in priority order for documentation."""

    HAS_OWNED_SITE = "has_owned_site"
    UNKNOWN = "unknown"
    SOCIAL_ONLY = "social_only"
    AGGREGATOR_ONLY = "aggregator_only"
    LIKELY_NO_SITE = "likely_no_site"


class SourceRef(BaseModel):
    """Paired dataset / license attribution for an Overture field."""

    model_config = ConfigDict(extra="forbid")

    dataset: str
    license: str | None = None
    property_path: str | None = None
    update_time: datetime | None = None


class RawOverturePlace(BaseModel):
    """Normalized row mapped from an Overture Places record."""

    model_config = ConfigDict(extra="forbid")

    overture_id: str
    version: int
    name: str | None = None
    lat: float
    lon: float
    basic_category: str | None = None
    taxonomy_primary: str | None = None
    taxonomy_hierarchy: list[str] = Field(default_factory=list)
    taxonomy_alternates: list[str] = Field(default_factory=list)
    confidence: float | None = None
    operating_status: str | None = None
    websites: list[str] = Field(default_factory=list)
    socials: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    brand_name: str | None = None
    address_freeform: str | None = None
    locality: str | None = None
    postcode: str | None = None
    country: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)

    @field_validator(
        "taxonomy_hierarchy",
        "taxonomy_alternates",
        "websites",
        "socials",
        "emails",
        "phones",
        "source_refs",
        mode="before",
    )
    @classmethod
    def _none_list_to_empty(cls, value: object) -> object:
        return [] if value is None else value


class Candidate(BaseModel):
    """Place candidate after normalization, classification, and scoring."""

    model_config = ConfigDict(extra="forbid")

    raw: RawOverturePlace
    distance_m: int
    normalized_name: str
    category_alias: str
    owned_domains: list[str] = Field(default_factory=list)
    social_urls: list[str] = Field(default_factory=list)
    aggregator_urls: list[str] = Field(default_factory=list)
    other_urls: list[str] = Field(default_factory=list)
    normalized_phones: list[str] = Field(default_factory=list)
    is_chain: bool = False
    chain_reason: str | None = None
    bucket: CandidateBucket
    score: int = Field(ge=0, le=100)
    score_reasons: list[str] = Field(default_factory=list)


class CalibrationReview(BaseModel):
    """Independent human review dimensions for calibration rows."""

    model_config = ConfigDict(extra="forbid")

    entity_status: Literal["valid", "wrong_entity", "uncertain"] | None = None
    target_category: Literal["yes", "no", "uncertain"] | None = None
    operating_status_review: Literal["open", "closed", "uncertain"] | None = None
    independence: Literal["independent", "chain", "uncertain"] | None = None
    site_status: Literal["no_owned_site", "owned_site", "social_only", "uncertain"] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _all_or_none_review_fields(self) -> Self:
        review_fields = (
            self.entity_status,
            self.target_category,
            self.operating_status_review,
            self.independence,
            self.site_status,
        )
        filled = sum(value is not None for value in review_fields)
        if filled not in (0, 5):
            raise ValueError("CalibrationReview requires all five review fields when any is set")
        return self


class SearchRequest(BaseModel):
    """Validated search parameters; network access must not precede validation."""

    model_config = ConfigDict(extra="forbid")

    lat: float
    lon: float
    radius_km: float
    categories: list[str] = Field(min_length=1)
    output_path: Path
    min_score: int = Field(default=0, ge=0, le=100)
    top: int | None = Field(default=None, gt=0)
    include_has_site: bool = False
    overture_release: str = "latest"
    config_dir: Path | None = None
    overwrite: bool = False

    @field_validator("lat")
    @classmethod
    def _lat_in_poland(cls, value: float) -> float:
        if not _PL_LAT_MIN <= value <= _PL_LAT_MAX:
            raise ValueError(
                f"lat must be within Poland MVP bounds [{_PL_LAT_MIN}, {_PL_LAT_MAX}], got {value}"
            )
        return value

    @field_validator("lon")
    @classmethod
    def _lon_in_poland(cls, value: float) -> float:
        if not _PL_LON_MIN <= value <= _PL_LON_MAX:
            raise ValueError(
                f"lon must be within Poland MVP bounds [{_PL_LON_MIN}, {_PL_LON_MAX}], got {value}"
            )
        return value

    @field_validator("radius_km")
    @classmethod
    def _radius_ok(cls, value: float) -> float:
        if not 0 < value <= _RADIUS_KM_MAX:
            raise ValueError(f"radius_km must be > 0 and <= {_RADIUS_KM_MAX}, got {value}")
        return value

    @field_validator("categories", mode="before")
    @classmethod
    def _normalize_categories(cls, value: object) -> object:
        if isinstance(value, str):
            parts = value.split(",")
        elif isinstance(value, list):
            parts = value
        else:
            raise ValueError("categories must be a list or comma-separated string")

        normalized: list[str] = []
        seen: set[str] = set()
        for raw in parts:
            if not isinstance(raw, str):
                raise ValueError("category aliases must be strings")
            alias = raw.strip().lower()
            if not alias:
                raise ValueError("categories must not contain empty aliases")
            if alias in seen:
                continue
            seen.add(alias)
            normalized.append(alias)
        if not normalized:
            raise ValueError("categories must contain at least one alias")
        return normalized

    @field_validator("output_path")
    @classmethod
    def _output_csv(cls, value: Path) -> Path:
        path = value.expanduser()
        if path.suffix.lower() != ".csv":
            raise ValueError("output_path must have a .csv extension")
        if path.exists() and path.is_dir():
            raise ValueError("output_path must not be a directory")
        if not path.stem:
            raise ValueError("output_path must have a non-empty stem")
        return path


class CategoryMapping(BaseModel):
    """Single user-facing category alias mapped to Overture codes."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    overture_basic: list[str] = Field(default_factory=list)
    overture_taxonomy: list[str] = Field(default_factory=list)
    score_weight: Annotated[int, Field(ge=0, le=30)]

    @model_validator(mode="after")
    def _require_some_mapping(self) -> Self:
        if not self.overture_basic and not self.overture_taxonomy:
            raise ValueError(
                "at least one of overture_basic or overture_taxonomy must be non-empty"
            )
        return self


class CategoriesConfig(BaseModel):
    """Root document for categories.yml."""

    model_config = ConfigDict(extra="forbid")

    version: int
    validated_against_schema: str
    categories: dict[str, CategoryMapping]

    @model_validator(mode="after")
    def _require_categories(self) -> Self:
        if not self.categories:
            raise ValueError("categories must not be empty")
        return self


class DomainRulesConfig(BaseModel):
    """Root document for domain_rules.yml."""

    model_config = ConfigDict(extra="forbid")

    social_hosts: list[str]
    aggregator_hosts: list[str]
    ignored_hosts: list[str]


class ChainDenylistConfig(BaseModel):
    """Root document for chain_denylist.yml."""

    model_config = ConfigDict(extra="forbid")

    chains: list[str]


class TaxonomySnapshotConfig(BaseModel):
    """Root document for taxonomy_snapshot.yml (codes used by the app only)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    reviewed_at: str
    evidence_urls: list[str] = Field(min_length=1)
    approved_basic: list[str]
    approved_taxonomy: list[str]
