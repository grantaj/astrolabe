import datetime
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Image:
    data: Any  # Placeholder for image data (e.g., numpy array or file path)
    width_px: int
    height_px: int
    timestamp_utc: datetime.datetime
    exposure_s: float
    metadata: Dict[str, Any]
