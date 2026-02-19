import datetime

from astrolabe.config import Config
from astrolabe.planner import Planner, ObserverLocation


def test_planner_smoke():
    config = Config(
        {
            "mount": {
                "site": {
                    "latitude_deg": -34.93,
                    "longitude_deg": 138.60,
                    "elevation_m": 50,
                }
            }
        }
    )
    planner = Planner(config)
    window_start = datetime.datetime(2024, 7, 1, 14, 0, tzinfo=datetime.timezone.utc)
    window_end = window_start + datetime.timedelta(hours=2)
    result = planner.plan(
        window_start_utc=window_start,
        window_end_utc=window_end,
        location=ObserverLocation(latitude_deg=-34.93, longitude_deg=138.60, elevation_m=50),
        mode="visual",
    )
    assert result.sections
    for section in result.sections:
        scores = [entry.score for entry in section.entries]
        assert scores == sorted(scores, reverse=True)
        for entry in section.entries:
            assert 0.0 <= entry.score <= 100.0
            assert len(entry.notes) <= 2
