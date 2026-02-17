import json
from dataclasses import asdict
from .types import PlannerResult


def format_json(result: PlannerResult) -> str:
    return json.dumps(asdict(result), indent=2, default=str)
