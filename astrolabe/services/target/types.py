from dataclasses import dataclass


@dataclass(frozen=True)
class TargetRecord:
    id: str
    name: str
    ra_deg: float
    dec_deg: float
    target_type: str | None = None
    mag: float | None = None
    aliases: list[str] | None = None


@dataclass(frozen=True)
class TargetMatch:
    record: TargetRecord
    match_score: float
    match_reason: str
