from pathlib import Path
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
        return self._data.get("solver", {}).get("database_path", None)

def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH

    if not path.exists():
        # Return default config if file missing
        return Config({})

    with open(path, "rb") as f:
        data = tomllib.load(f)

    return Config(data)
