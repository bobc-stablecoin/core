"""Override fyzz_deploy to reuse project fixtures as a per-example factory."""
import json
from pathlib import Path
import pytest
from .setup import deploy


@pytest.fixture
def fyzz_config():
    metadata = (Path(__file__).parent / "../../fuzz_data").resolve()
    config = json.loads((metadata / "fyzz.json").read_text())
    config["meta_dir"] = str(metadata)
    return config


@pytest.fixture
def fyzz_deploy(fyzz_config):
    return lambda: deploy(fyzz_config)
