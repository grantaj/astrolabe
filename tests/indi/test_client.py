from unittest.mock import patch

from astrolabe.indi.client import IndiClient


def _make_client() -> IndiClient:
    return IndiClient(host="127.0.0.1", port=7624)


class TestSnapshot:
    def test_parses_multiline_output(self):
        stdout = (
            "Telescope Simulator.EQUATORIAL_EOD_COORD.RA=6.0\n"
            "Telescope Simulator.EQUATORIAL_EOD_COORD.DEC=45.0\n"
            "Telescope Simulator.EQUATORIAL_EOD_COORD._STATE=Ok\n"
            "Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON=On\n"
            "Telescope Simulator.TELESCOPE_TRACK_STATE._STATE=Idle\n"
        )
        client = _make_client()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            result = client.snapshot("Telescope Simulator")

        assert result == {
            "Telescope Simulator.EQUATORIAL_EOD_COORD.RA": "6.0",
            "Telescope Simulator.EQUATORIAL_EOD_COORD.DEC": "45.0",
            "Telescope Simulator.EQUATORIAL_EOD_COORD._STATE": "Ok",
            "Telescope Simulator.TELESCOPE_TRACK_STATE.TRACK_ON": "On",
            "Telescope Simulator.TELESCOPE_TRACK_STATE._STATE": "Idle",
        }

    def test_returns_empty_dict_on_no_output(self):
        client = _make_client()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.returncode = 1

            result = client.snapshot("Telescope Simulator")

        assert result == {}

    def test_skips_malformed_lines(self):
        stdout = (
            "Telescope Simulator.FOO.BAR=baz\n"
            "garbage line with no equals\n"
            "Telescope Simulator.X.Y=z\n"
        )
        client = _make_client()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            result = client.snapshot("Telescope Simulator")

        assert result == {
            "Telescope Simulator.FOO.BAR": "baz",
            "Telescope Simulator.X.Y": "z",
        }

    def test_value_containing_equals_sign(self):
        stdout = "Device.PROP.ELEM=val=ue\n"
        client = _make_client()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = stdout
            mock_run.return_value.returncode = 0

            result = client.snapshot("Device")

        assert result == {"Device.PROP.ELEM": "val=ue"}

    def test_passes_correct_args_to_subprocess(self):
        client = IndiClient(host="10.0.0.1", port=9999)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = ""
            mock_run.return_value.returncode = 0

            client.snapshot("MyMount", timeout_s=5.0)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == [
            "indi_getprop",
            "-h",
            "10.0.0.1",
            "-p",
            "9999",
            "-t",
            "5.0",
            "MyMount.*.*",
            "MyMount.*._STATE",
        ]
