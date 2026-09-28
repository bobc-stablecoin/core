"""Run with the project's native test runner and FYZZ_PROFILE=smoke initially."""
from hypothesis.stateful import run_state_machine_as_test
from .machine import ProtocolMachine
from .runtime import campaign_settings


def test_stateful(fyzz_config, fyzz_deploy):
    run_state_machine_as_test(
        lambda: ProtocolMachine(fyzz_config, fyzz_deploy),
        settings=campaign_settings(fyzz_config),
    )
