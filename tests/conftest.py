import pytest
from pathlib import Path
import sys

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def project_root():
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def metadata_store():
    """Load metadata once per test session."""
    from backend.metadata.parser import load_metadata
    return load_metadata()
