import pytest
from beets import config


@pytest.fixture(autouse=True)
def reset_beets_config():
    config.clear()
    yield
    config.clear()
