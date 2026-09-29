from pathlib import Path

import pytest

# backend/tests/conftest.py -> repo root
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture
def sample_data_dir() -> Path:
    return SAMPLE_DATA_DIR
