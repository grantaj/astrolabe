from pathlib import Path

from astrolabe.services.target.index import (
    TargetIndex,
    load_alias_csv,
    load_catalog_csv,
    load_hip_subset_csv,
)
from astrolabe.services.target.resolver import TargetResolver
from astrolabe.services.target.types import TargetRecord


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


def test_missing_alias_backing_record_is_terminal_miss():
    aliases = load_alias_csv(_data_path("star_aliases.csv"))
    hip_records = {
        record.id.removeprefix("HIP ")
        for record in load_hip_subset_csv(_data_path("hip_subset.csv"))
    }
    assert aliases["Acrux"] == "60718"
    assert aliases["Acrux"] not in hip_records

    resolver = TargetResolver.from_catalog_paths(
        core_dso_path=_data_path("catalog_curated.csv"),
        hip_subset_path=_data_path("hip_subset.csv"),
        star_aliases_path=_data_path("star_aliases.csv"),
        bayer_flamsteed_path=_data_path("bayer_flamsteed.csv"),
        min_score=0.0,
    )

    assert resolver.resolve("Acrux") == []
    assert resolver.resolve("alpha cen") == []


def test_repo_bayer_alias_resolves_deterministically():
    resolver = TargetResolver.from_catalog_paths(
        core_dso_path=_data_path("catalog_curated.csv"),
        hip_subset_path=_data_path("hip_subset.csv"),
        star_aliases_path=_data_path("star_aliases.csv"),
        bayer_flamsteed_path=_data_path("bayer_flamsteed.csv"),
    )

    results = resolver.resolve("beta ori")

    assert results
    assert results[0].record.id == "HIP 24436"
    assert results[0].match_reason == "alias"


def test_missing_lower_priority_alias_does_not_mask_core_name(tmp_path):
    core = tmp_path / "core.csv"
    core.write_text(
        "id,name,ra_deg,dec_deg,type,mag\nDSO1,Shared,1.0,2.0,galaxy,\n",
        encoding="utf-8",
    )
    hip = tmp_path / "hip.csv"
    hip.write_text("hip_id,ra_deg,dec_deg,mag,name\n", encoding="utf-8")
    common = tmp_path / "common.csv"
    common.write_text("alias,hip_id\nShared,999\n", encoding="utf-8")
    bayer = tmp_path / "bayer.csv"
    bayer.write_text("alias,hip_id\n", encoding="utf-8")

    resolver = TargetResolver.from_catalog_paths(
        core_dso_path=core,
        hip_subset_path=hip,
        star_aliases_path=common,
        bayer_flamsteed_path=bayer,
        min_score=0.0,
    )

    results = resolver.resolve("Shared")
    assert results[0].record.id == "DSO1"
    assert results[0].match_reason == "alias"


def test_required_alias_sources_have_deterministic_priority(tmp_path):
    core = tmp_path / "core.csv"
    core.write_text("id,name,ra_deg,dec_deg,type,mag\n", encoding="utf-8")
    hip = tmp_path / "hip.csv"
    hip.write_text(
        "hip_id,ra_deg,dec_deg,mag,name\n1,1.0,2.0,1.0,HIP 1\n2,3.0,4.0,1.0,HIP 2\n",
        encoding="utf-8",
    )
    common = tmp_path / "common.csv"
    common.write_text("alias,hip_id\nShared,1\n", encoding="utf-8")
    bayer = tmp_path / "bayer.csv"
    bayer.write_text("alias,hip_id\nalpha aaa,1\n", encoding="utf-8")
    optional = tmp_path / "optional.csv"
    optional.write_text("alias,hip_id\nShared,2\n", encoding="utf-8")

    resolver = TargetResolver.from_catalog_paths(
        core_dso_path=core,
        hip_subset_path=hip,
        star_aliases_path=common,
        bayer_flamsteed_path=bayer,
        bsc_crosswalk_path=optional,
    )

    results = resolver.resolve("Shared")
    assert results[0].record.id == "HIP 1"
    assert results[0].match_reason == "alias"


def test_conflicting_required_alias_sources_fail_closed(tmp_path):
    core = tmp_path / "core.csv"
    core.write_text("id,name,ra_deg,dec_deg,type,mag\n", encoding="utf-8")
    hip = tmp_path / "hip.csv"
    hip.write_text(
        "hip_id,ra_deg,dec_deg,mag,name\n1,1.0,2.0,1.0,HIP 1\n2,3.0,4.0,1.0,HIP 2\n",
        encoding="utf-8",
    )
    common = tmp_path / "common.csv"
    common.write_text("alias,hip_id\nShared,1\n", encoding="utf-8")
    bayer = tmp_path / "bayer.csv"
    bayer.write_text("alias,hip_id\nshared,2\n", encoding="utf-8")

    try:
        TargetResolver.from_catalog_paths(
            core_dso_path=core,
            hip_subset_path=hip,
            star_aliases_path=common,
            bayer_flamsteed_path=bayer,
        )
    except ValueError as exc:
        assert "Conflicting alias" in str(exc)
    else:
        raise AssertionError("conflicting required aliases must fail closed")


def test_resolver_fuzzy():
    index = TargetIndex()
    for record in load_hip_subset_csv(_data_path("hip_subset.csv")):
        index.add_record(record)

    resolver = TargetResolver(index, min_score=0.6)
    results = resolver.resolve("Siriuss")
    assert results
    assert results[0].match_reason == "fuzzy"


def test_fuzzy_ties_are_sorted_by_alias_then_id():
    index = TargetIndex()
    first = TargetRecord(id="HIP 2", name="abcy", ra_deg=0.0, dec_deg=0.0)
    second = TargetRecord(id="HIP 1", name="abcx", ra_deg=0.0, dec_deg=0.0)
    index.add_record(first)
    index.add_record(second)

    results = TargetResolver(index, min_score=0.0).resolve("abcz", limit=2)

    assert [match.record.name for match in results] == ["abcx", "abcy"]
