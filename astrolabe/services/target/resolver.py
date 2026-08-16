from difflib import SequenceMatcher
from pathlib import Path

from .index import TargetIndex, load_alias_csv, load_catalog_csv, load_hip_subset_csv
from .normalize import normalize_query
from .parser import parse_bayer_flamsteed
from .types import TargetMatch, TargetRecord


class TargetResolver:
    def __init__(self, index: TargetIndex, min_score: float = 0.7) -> None:
        self._index = index
        self._min_score = min_score

    @classmethod
    def from_catalog_paths(
        cls,
        core_dso_path: Path,
        hip_subset_path: Path,
        star_aliases_path: Path,
        bayer_flamsteed_path: Path,
        bsc_crosswalk_path: Path | None = None,
        *,
        min_score: float = 0.7,
    ) -> "TargetResolver":
        index = TargetIndex()
        for record in load_catalog_csv(core_dso_path):
            index.add_record(record)
        for record in load_hip_subset_csv(hip_subset_path):
            index.add_record(record)

        alias_map: dict[str, str] = {}
        for alias, hip_id in load_alias_csv(star_aliases_path).items():
            alias_map[alias] = hip_id
        for alias, hip_id in load_alias_csv(bayer_flamsteed_path).items():
            alias_map[alias] = hip_id
        if bsc_crosswalk_path and bsc_crosswalk_path.exists():
            for alias, hip_id in load_alias_csv(bsc_crosswalk_path).items():
                alias_map[alias] = hip_id

        for alias, hip_id in alias_map.items():
            record = index.get_by_id(f"HIP {hip_id}")
            if record:
                index.add_record(
                    TargetRecord(
                        id=record.id,
                        name=record.name,
                        ra_deg=record.ra_deg,
                        dec_deg=record.dec_deg,
                        target_type=record.target_type,
                        mag=record.mag,
                        aliases=[alias],
                    )
                )

        return cls(index=index, min_score=min_score)

    @classmethod
    def from_repo_data(
        cls,
        *,
        min_score: float = 0.7,
    ) -> "TargetResolver":
        repo_root = Path(__file__).resolve().parents[3]
        repo_data = repo_root / "data"
        user_data = Path.home() / ".astrolabe" / "data"

        def pick(path: str) -> Path:
            user_path = user_data / path
            repo_path = repo_data / path
            if user_path.exists():
                return user_path
            return repo_path

        core_path = pick("catalog_curated.csv")
        hip_path = pick("hip_subset.csv")
        star_aliases_path = pick("star_aliases.csv")
        bayer_path = pick("bayer_flamsteed.csv")

        if not core_path.exists():
            raise FileNotFoundError(
                "Catalog not found. Expected catalog_curated.csv in "
                f"{user_data} or {repo_data}"
            )
        return cls.from_catalog_paths(
            core_dso_path=core_path,
            hip_subset_path=hip_path,
            star_aliases_path=star_aliases_path,
            bayer_flamsteed_path=bayer_path,
            bsc_crosswalk_path=pick("bsc_crosswalk.csv"),
            min_score=min_score,
        )

    def resolve(self, query: str, limit: int = 5) -> list[TargetMatch]:
        normalized = normalize_query(query)

        record = self._index.get_by_id(normalized)
        if record:
            return [TargetMatch(record=record, match_score=1.0, match_reason="id")]

        record = self._index.get_by_alias(normalized)
        if record:
            return [TargetMatch(record=record, match_score=0.95, match_reason="alias")]

        parsed = parse_bayer_flamsteed(normalized)
        if parsed:
            record = self._index.get_by_alias(parsed)
            if record:
                return [
                    TargetMatch(
                        record=record, match_score=0.9, match_reason="bayer_flamsteed"
                    )
                ]

        return self._fuzzy_matches(normalized, limit)

    def _fuzzy_matches(self, normalized: str, limit: int) -> list[TargetMatch]:
        matches: list[TargetMatch] = []
        for alias, record in self._index.iter_aliases():
            score = SequenceMatcher(None, normalized, alias).ratio()
            if score < self._min_score:
                continue
            matches.append(
                TargetMatch(record=record, match_score=score, match_reason="fuzzy")
            )

        matches.sort(key=lambda m: m.match_score, reverse=True)
        return matches[:limit]
