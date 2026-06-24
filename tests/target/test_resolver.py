from pathlib import Path

from astrolabe.services.target.index import (
    TargetIndex,
    load_alias_csv,
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


def test_repo_canopus_alias_has_backing_hip_record():
    resolver = TargetResolver.from_catalog_paths(
        core_dso_path=_data_path("catalog_curated.csv"),
        hip_subset_path=_data_path("hip_subset.csv"),
        star_aliases_path=_data_path("star_aliases.csv"),
        bayer_flamsteed_path=_data_path("bayer_flamsteed.csv"),
        bsc_crosswalk_path=_data_path("bsc_crosswalk.csv"),
        min_score=0.95,
    )

    results = resolver.resolve("canopus")

    assert results
    assert results[0].record.id == "HIP 30438"
    assert results[0].match_reason == "alias"


def test_repo_acrux_alias_has_no_backing_hip_record():
    aliases = load_alias_csv(_data_path("star_aliases.csv"))
    hip_records = {
        record.id.removeprefix("HIP ")
        for record in load_hip_subset_csv(_data_path("hip_subset.csv"))
    }

    assert aliases["Acrux"] == "60718"
    assert aliases["Acrux"] not in hip_records


def test_resolver_fuzzy():
    index = TargetIndex()
    for record in load_hip_subset_csv(_data_path("hip_subset.csv")):
        index.add_record(record)

    resolver = TargetResolver(index, min_score=0.6)
    results = resolver.resolve("Siriuss")
    assert results
    assert results[0].match_reason == "fuzzy"
