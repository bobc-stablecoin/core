import pytest

from tests.utils.protocol import Protocol, deploy_protocol


@pytest.fixture
def protocol() -> Protocol:
    """Deploy a fresh local protocol with funded borrower and reserve roles."""
    return deploy_protocol()
