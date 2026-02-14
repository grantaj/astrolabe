import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run tests marked as integration",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--integration"):
        return

    for item in items:
        if "integration" in item.keywords:
            item.add_marker(
                pytest.mark.skip(
                    reason="need --integration option to run integration tests"
                )
            )
