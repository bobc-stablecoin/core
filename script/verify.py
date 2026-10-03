from pathlib import Path

import boa
from moccasin.config import get_active_network
from src import bobc, cashback, vault_engine


CRVUSD = "0x1594f9C38aCB4CBFf721a375210920cd77F54A62"
VAULT = "0x8525a2d92A0F2A81463E6d7e83f8607Cf4F68039"
PEG_ORACLE = "0xB1dB81db766Bd3aB894d0f75DfA3C6252234D4FC"
BOBC = "0x390C1f61Ac83cf3809283DfDfFCba338E70F6438"
CASHBACK = "0x06cFeb1F8fd16181321637c61a714bB5EfeF56cf"
VAULT_ENGINE = "0xe6E9A7D1607Ef88d32a6115744CEaB61f517c674"
MOCKS_DIR = Path(__file__).resolve().parents[1] / "tests" / "mocks"


def verify() -> None:
    """Verify the existing mock deployment on Arbitrum Sepolia's Blockscout."""
    network = get_active_network()
    if network.chain_id != 421614 or network.is_local_or_forked_network():
        raise ValueError("Run this script with --network arbitrum-sepolia.")
    if network.explorer_type != "blockscout":
        raise ValueError("Configure explorer_type = 'blockscout' for arbitrum-sepolia.")
    if not network.explorer_api_key or network.explorer_api_key.startswith("$"):
        raise ValueError("Set BLOCKSCOUT_API_KEY in your environment or core/.env before verification.")

    verifier = network.get_verifier_class()(network.explorer_uri, network.explorer_api_key)
    contracts = (
        ("CRVUSD", CRVUSD, boa.load_partial(str(MOCKS_DIR / "MockERC20.vy"))),
        ("VAULT", VAULT, boa.load_partial(str(MOCKS_DIR / "MockERC4626.vy"))),
        ("PEG_ORACLE", PEG_ORACLE, boa.load_partial(str(MOCKS_DIR / "MockDeploymentOracle.vy"))),
        ("BOBC", BOBC, bobc),
        ("CASHBACK", CASHBACK, cashback),
        ("VAULT_ENGINE", VAULT_ENGINE, vault_engine),
    )

    failures = []
    for name, address, deployer in contracts:
        print(f"Verifying {name}={address}", flush=True)
        try:
            if verifier.is_verified(address):
                print(f"{name}: already verified")
            else:
                # Attach to the existing contract; Blockscout detects constructor arguments.
                contract = deployer.at(address)
                result = boa.verify(contract, verifier=verifier)
                result.wait_for_verification()
            print(f"{network.explorer_uri}/address/{address}?tab=contract_code", flush=True)
        except Exception as exc:
            failures.append(name)
            # HTTP exception messages may contain the API key in the request URL.
            print(f"{name}: verification failed ({type(exc).__name__})", flush=True)

    if failures:
        raise RuntimeError(f"Verification failed for: {', '.join(failures)}")
    print("All six contracts are verified on Blockscout.")


def moccasin_main() -> None:
    verify()
