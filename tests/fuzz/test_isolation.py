"""Verify one anchor and one independent Python model per machine instance."""
import boa
import pytest

from tests.mocks.deployers import MOCK_ERC20
from tests.utils.protocol import ONE, RATE_LOW, open_position
from .machine import ProtocolMachine


def test_consecutive_machine_instances_reset_chain_and_model(fyzz_config, fyzz_deploy):
    first = ProtocolMachine(fyzz_config, fyzz_deploy)
    try:
        first_model = first.model
        first_protocol = first.protocol
        first_model.approved_merchants.add(first_model.merchants[0])
        open_position(first_protocol.engine, 1_430 * ONE, RATE_LOW, first_model.borrowers[0])
        assert first_protocol.engine.total_debt() > 0
    finally:
        first.teardown()

    second = ProtocolMachine(fyzz_config, fyzz_deploy)
    try:
        assert second.model is not first_model
        assert second.model.approved_merchants == set()
        assert second.protocol.engine.total_debt() == 0
        assert second.protocol.engine.total_shares() == 0
        assert second.protocol.bobc.totalSupply() == 0
        assert second.protocol.bobc.balanceOf(second.protocol.engine.address) == 0
        assert second.protocol.asset.balanceOf(second.protocol.engine.address) == 0
        assert second.protocol.oracle.latest()[1] == boa.env.timestamp
    finally:
        second.teardown()


def test_machine_closes_anchor_when_deployment_raises(fyzz_config):
    before_timestamp = boa.env.timestamp
    deployed_addresses = []

    def fail_after_partial_deployment():
        contract = MOCK_ERC20.deploy("Partial", "PART")
        deployed_addresses.append(contract.address)
        raise RuntimeError("intentional setup failure")

    with pytest.raises(RuntimeError, match="intentional setup failure"):
        ProtocolMachine(fyzz_config, fail_after_partial_deployment)

    assert boa.env.timestamp == before_timestamp
    address = bytes.fromhex(deployed_addresses[0][2:])
    assert boa.env.evm.vm.state.get_code(address) == b""
