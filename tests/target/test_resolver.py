from pathlib import Path

from astrolabe.services.target.index import (
    TargetIndex,
    load_catalog_csv,
    load_hip_subset_csv,
)
from astrolabe.services.target.resolver import TargetResolver


def _data_path(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "data" / name


def test_resolver_exact_id_from_core_dso():
    index = TargetIndex()
    for record in load_catalog_csv(_data_path("catalog_curated.csv")):
        index.add_record(record)

    resolver = TargetResolver(index)
    results = resolver.resolve("IC0010")
    assert results
    assert results[0].record.id == "IC0010"
    assert results[0].match_reason == "id"


def test_resolver_alias_from_core_dso():
    index = TargetIndex()
    for record in load_catalog_csv(_data_path("catalog_curated.csv")):
        index.add_record(record)

    resolver = TargetResolver(index)
    results = resolver.resolve("M110")
    assert results
    assert results[0].match_reason in {"alias", "id"}


def test_resolver_hip_exact():
    index = TargetIndex()
    for record in load_hip_subset_csv(_data_path("hip_subset.csv")):
        index.add_record(record)

    resolver = TargetResolver(index)
    results = resolver.resolve("HIP 32349")
    assert results
    assert results[0].record.id == "HIP 32349"


def test_resolver_fuzzy():
    index = TargetIndex()
    for record in load_hip_subset_csv(_data_path("hip_subset.csv")):
        index.add_record(record)

    resolver = TargetResolver(index, min_score=0.6)
    results = resolver.resolve("Siriuss")
    assert results
    assert results[0].match_reason == "fuzzy"
