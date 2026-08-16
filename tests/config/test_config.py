import pytest
from pathlib import Path

import astrolabe.config
from astrolabe.config import Config, load_config


def test_empty_config():
    config = Config({})
    assert config.indi_host == "127.0.0.1"
    assert config.indi_port == 7624
    assert config.solver_name == "astap"
    assert config.solver_binary == "astap"
    assert config.solver_database_path is None
    assert config.solver_search_radius_deg is None
    assert config.camera_backend == "indi"
    assert config.camera_device == "CCD Simulator"
    assert config.camera_output_dir is None
    assert config.camera_output_prefix == "astrolabe_capture_"
    assert config.camera_use_guider_exposure is False
    assert config.camera_default_exposure_s is None
    assert config.mount_backend == "indi"
    assert config.mount_device == "Telescope Simulator"
    assert config.mount_site_latitude_deg is None
    assert config.mount_site_longitude_deg is None
    assert config.mount_site_elevation_m is None
    assert config.mount_site_bortle is None
    assert config.mount_site_sqm is None
    assert config.planner_aperture_mm is None


def test_config_parsing(tmp_path):
    toml_content = """
[indi]
host = "192.168.1.100"
port = 8000

[solver]
name = "nova"
binary = "/opt/nova/bin"
database_path = "~/.astap"
search_radius_deg = 15.5

[camera]
backend = "mock"
device = "Test Camera"
output_dir = "~/captures"
output_prefix = "img_"
use_guider_exposure = true
default_exposure_s = 2.5

[mount]
backend = "mock"
device = "Test Mount"

[site]
latitude_deg = 45.0
longitude_deg = -120.0
elevation_m = 1500.0
bortle = 4
sqm = 21.5

[planner]
aperture_mm = 200.0
    """
    config_file = tmp_path / "test_config.toml"
    config_file.write_text(toml_content)

    config = load_config(config_file)
    assert config.indi_host == "192.168.1.100"
    assert config.indi_port == 8000

    assert config.solver_name == "nova"
    assert config.solver_binary == "/opt/nova/bin"
    assert config.solver_database_path == str(Path("~/.astap").expanduser())
    assert isinstance(config.solver_database_path, str)
    assert config.solver_search_radius_deg == 15.5

    assert config.camera_backend == "mock"
    assert config.camera_device == "Test Camera"
    assert config.camera_output_dir == Path("~/captures").expanduser()
    assert isinstance(config.camera_output_dir, Path)
    assert config.camera_output_prefix == "img_"
    assert config.camera_use_guider_exposure is True
    assert config.camera_default_exposure_s == 2.5

    assert config.mount_backend == "mock"
    assert config.mount_device == "Test Mount"

    assert config.mount_site_latitude_deg == 45.0
    assert config.mount_site_longitude_deg == -120.0
    assert config.mount_site_elevation_m == 1500.0
    assert config.mount_site_bortle == 4
    assert config.mount_site_sqm == 21.5

    assert config.planner_aperture_mm == 200.0


def test_mount_site_override(tmp_path):
    toml_content = """
[site]
latitude_deg = 45.0
longitude_deg = -120.0
elevation_m = 1500.0

[mount.site]
latitude_deg = 46.0
longitude_deg = -121.0
elevation_m = 1600.0
    """
    config_file = tmp_path / "test_override.toml"
    config_file.write_text(toml_content)

    config = load_config(config_file)
    # mount.site should override root site
    assert config.mount_site_latitude_deg == 46.0
    assert config.mount_site_longitude_deg == -121.0
    assert config.mount_site_elevation_m == 1600.0


def test_load_config_missing_default_returns_empty(tmp_path, monkeypatch):
    # Pass a path that doesn't exist, but don't pass it explicitly (simulate default)
    # We can mock DEFAULT_CONFIG_PATH
    monkeypatch.setattr(
        astrolabe.config, "DEFAULT_CONFIG_PATH", tmp_path / "does_not_exist.toml"
    )
    config = load_config()
    assert config.indi_host == "127.0.0.1"  # Defaults work


def test_load_config_explicit_missing_raises_error(tmp_path):
    missing_file = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(missing_file)


def test_empty_string_paths_return_none():
    config = Config(
        {
            "solver": {"database_path": ""},
            "camera": {"output_dir": ""},
        }
    )
    assert config.solver_database_path is None
    assert config.camera_output_dir is None


def test_mount_site_without_top_level_site(tmp_path):
    toml_content = """
[mount.site]
latitude_deg = 50.0
longitude_deg = -110.0
elevation_m = 2000.0
bortle = 3
sqm = 22.0
    """
    config_file = tmp_path / "test_mount_only.toml"
    config_file.write_text(toml_content)

    config = load_config(config_file)
    assert config.mount_site_latitude_deg == 50.0
    assert config.mount_site_longitude_deg == -110.0
    assert config.mount_site_elevation_m == 2000.0
    assert config.mount_site_bortle == 3
    assert config.mount_site_sqm == 22.0


def test_load_config_default_path_exists(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[indi]\nhost = "10.0.0.1"\n')

    monkeypatch.setattr(astrolabe.config, "DEFAULT_CONFIG_PATH", config_file)
    config = load_config()
    assert config.indi_host == "10.0.0.1"
