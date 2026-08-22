from collections.abc import Iterable
from difflib import SequenceMatcher
from pathlib import Path

from .index import TargetIndex, load_alias_csv, load_catalog_csv, load_hip_subset_csv
from .normalize import normalize_query
from .parser import parse_bayer_flamsteed
from .types import TargetMatch, TargetRecord


class TargetResolver:
    def __init__(
        self,
        index: TargetIndex,
        min_score: float = 0.7,
        *,
        missing_aliases: Iterable[str] = (),
    ) -> None:
        self._index = index
        self._min_score = min_score
        self._missing_aliases = {normalize_query(alias) for alias in missing_aliases}

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

        # Resolver catalogue order is fixed policy. Core catalogue aliases/names win,
        # followed by curated common names, checked-in Bayer/Flamsteed aliases, then
        # the optional generated BSC crosswalk. Lower-priority sources never override
        # a higher-priority alias.
        alias_targets: dict[str, tuple[str, str]] = {}
        _merge_aliases(alias_targets, load_alias_csv(star_aliases_path))
        _merge_aliases(alias_targets, load_alias_csv(bayer_flamsteed_path))
        if bsc_crosswalk_path and bsc_crosswalk_path.exists():
            _merge_aliases(
                alias_targets,
                load_alias_csv(bsc_crosswalk_path),
                allow_conflicts=True,
            )

        missing_aliases: set[str] = set()
        for normalized, (alias, hip_id) in sorted(alias_targets.items()):
            record = index.get_by_id(f"HIP {hip_id}")
            if record is None:
                missing_aliases.add(normalized)
                continue

            existing = index.get_by_alias(alias)
            if existing is not None and existing.id != record.id:
                continue
            index.add_alias(alias, record)

        return cls(
            index=index,
            min_score=min_score,
            missing_aliases=missing_aliases,
        )

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

        # An exact known alias whose backing HIP record is unavailable is a terminal
        # miss. Falling through to fuzzy search can silently select a different star.
        if normalized in self._missing_aliases:
            return []

        record = self._index.get_by_alias(normalized)
        if record:
            return [TargetMatch(record=record, match_score=0.95, match_reason="alias")]

        parsed = parse_bayer_flamsteed(normalized)
        if parsed:
            if normalize_query(parsed) in self._missing_aliases:
                return []
            record = self._index.get_by_alias(parsed)
            if record:
                return [
                    TargetMatch(
                        record=record, match_score=0.9, match_reason="bayer_flamsteed"
                    )
                ]

        return self._fuzzy_matches(normalized, limit)

    def _fuzzy_matches(self, normalized: str, limit: int) -> list[TargetMatch]:
        matches: list[tuple[float, str, TargetRecord]] = []
        for alias, record in self._index.iter_aliases():
            score = SequenceMatcher(None, normalized, alias).ratio()
            if score < self._min_score:
                continue
            matches.append((score, alias, record))

        matches.sort(key=lambda item: (-item[0], item[1], normalize_query(item[2].id)))
        return [
            TargetMatch(record=record, match_score=score, match_reason="fuzzy")
            for score, _, record in matches[:limit]
        ]


def _merge_aliases(
    target: dict[str, tuple[str, str]],
    aliases: dict[str, str],
    *,
    allow_conflicts: bool = False,
) -> None:
    for alias, hip_id in sorted(
        aliases.items(), key=lambda item: (normalize_query(item[0]), item[0], item[1])
    ):
        normalized = normalize_query(alias)
        existing = target.get(normalized)
        if existing is None:
            target[normalized] = (alias, hip_id)
            continue
        if existing[1] == hip_id:
            continue
        if allow_conflicts:
            continue
        raise ValueError(
            f"Conflicting alias {alias!r}: HIP {existing[1]} and HIP {hip_id}"
        )
