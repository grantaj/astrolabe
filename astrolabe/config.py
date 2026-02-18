from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tomli as tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        import tomli as tomllib

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "astrolabe" / "config.toml"


class Config:
    def __init__(self, data: dict):
        self._data = data

    @property
    def indi_host(self):
        return self._data.get("indi", {}).get("host", "127.0.0.1")

    @property
    def indi_port(self):
        return self._data.get("indi", {}).get("port", 7624)

    @property
    def solver_name(self):
        return self._data.get("solver", {}).get("name", "astap")

    @property
    def solver_binary(self):
        return self._data.get("solver", {}).get("binary", "astap")

    @property
    def solver_database_path(self):
        path = self._data.get("solver", {}).get("database_path", None)
        if not path:
            return None
        return str(Path(path).expanduser())

    @property
    def solver_search_radius_deg(self):
        return self._data.get("solver", {}).get("search_radius_deg", None)

    @property
    def camera_backend(self):
        return self._data.get("camera", {}).get("backend", "indi")

    @property
    def camera_device(self):
        return self._data.get("camera", {}).get("device", "CCD Simulator")

    @property
    def camera_output_dir(self):
        path = self._data.get("camera", {}).get("output_dir", None)
        if not path:
            return None
        return Path(path).expanduser()

    @property
    def camera_output_prefix(self):
        return self._data.get("camera", {}).get("output_prefix", "astrolabe_capture_")

    @property
    def camera_use_guider_exposure(self):
        return self._data.get("camera", {}).get("use_guider_exposure", False)

    @property
    def camera_default_exposure_s(self):
        return self._data.get("camera", {}).get("default_exposure_s", None)


def load_config(path: Path | None = None) -> Config:
    explicit_path = path
    path = path or DEFAULT_CONFIG_PATH

    if not path.exists():
        if explicit_path is not None:
            raise FileNotFoundError(f"Config file not found: {path}")
        # Return default config if default file missing
        return Config({})

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return Config(data)
