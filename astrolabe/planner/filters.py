from dataclasses import dataclass


@dataclass
class Feasibility:
    max_alt_deg: float
    time_above_min_alt_min: float
    sun_alt_deg: float


def apply_feasibility_constraints(feat: Feasibility, constraints) -> bool:
    if feat.max_alt_deg < constraints.min_altitude_deg:
        return False
    if feat.time_above_min_alt_min < constraints.min_duration_min:
        return False
    if feat.sun_alt_deg > constraints.sun_altitude_max_deg:
        return False
    return True
