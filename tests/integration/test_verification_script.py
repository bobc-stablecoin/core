from types import SimpleNamespace

import pytest

from script import verify as verification


@pytest.mark.parametrize("failed_address", [None, verification.VAULT])
def test_verification_skips_verified_contracts_and_continues_after_failure(monkeypatch, failed_address):
    attached = []
    submitted = []
    confirmed = []

    def attach(address):
        attached.append(address)
        return SimpleNamespace(address=address)

    def submit(contract, verifier):
        submitted.append(contract.address)
        if contract.address == failed_address:
            raise RuntimeError("Blockscout rejected the source")
        return SimpleNamespace(wait_for_verification=lambda: confirmed.append(contract.address))

    verifier = SimpleNamespace(is_verified=lambda address: address == verification.CRVUSD)
    network = SimpleNamespace(
        chain_id=421614,
        explorer_type="blockscout",
        explorer_uri="https://arbitrum-sepolia.blockscout.com",
        explorer_api_key="test-blockscout-key",
        is_local_or_forked_network=lambda: False,
        get_verifier_class=lambda: lambda uri, key: verifier,
    )
    deployer = SimpleNamespace(at=attach)
    monkeypatch.setattr(verification, "get_active_network", lambda: network)
    monkeypatch.setattr(verification.boa, "load_partial", lambda path: deployer)
    monkeypatch.setattr(verification.boa, "verify", submit)
    for module in ("bobc", "cashback", "vault_engine"):
        monkeypatch.setattr(verification, module, deployer)

    if failed_address:
        with pytest.raises(RuntimeError, match="Verification failed for: VAULT"):
            verification.moccasin_main()
    else:
        verification.moccasin_main()

    expected = [
        verification.VAULT, verification.PEG_ORACLE, verification.BOBC,
        verification.CASHBACK, verification.VAULT_ENGINE,
    ]
    assert attached == submitted == expected
    assert confirmed == [address for address in expected if address != failed_address]
