"""Diagnose wallet setup: check proxy type, version, and signer-funder relationship."""

import os
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

load_dotenv()

KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER = os.getenv("POLYMARKET_FUNDER_ADDRESS")

# Derive signer address from private key
signer = Account.from_key(KEY)
print(f"Signer address (from private key): {signer.address}")
print(f"Funder address (from .env):        {FUNDER}")
print()

# Check py-clob-client version
try:
    import py_clob_client
    version = getattr(py_clob_client, "__version__", "unknown")
    print(f"py-clob-client version: {version}")
except Exception as e:
    print(f"py-clob-client version check failed: {e}")

# Check what signature types the library defines
try:
    from py_clob_client.order_builder import builder as ob
    for attr in dir(ob):
        val = getattr(ob, attr)
        if isinstance(val, int) and not attr.startswith("_"):
            print(f"  {attr} = {val}")
except Exception:
    pass

print()

# Check proxy wallet factories on-chain
w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
if not w3.is_connected():
    print("Cannot connect to Polygon RPC")
    exit(1)

funder_checksum = Web3.to_checksum_address(FUNDER)

# Check if funder is a contract (proxy wallets are contracts)
code = w3.eth.get_code(funder_checksum)
print(f"Funder is contract: {len(code) > 0}")
print(f"Funder contract bytecode length: {len(code)} bytes")
print()

# Check balances at both addresses
signer_bal = w3.eth.get_balance(Web3.to_checksum_address(signer.address))
funder_bal = w3.eth.get_balance(funder_checksum)
print(f"Signer POL balance: {w3.from_wei(signer_bal, 'ether')}")
print(f"Funder POL balance: {w3.from_wei(funder_bal, 'ether')}")

# Check USDC balance at funder
USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
erc20_abi = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}]'
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=erc20_abi)
usdc_bal = usdc.functions.balanceOf(funder_checksum).call()
print(f"Funder USDC balance: {usdc_bal / 1e6}")
print()

# Test ClobClient with all signature types and get_ok()
from py_clob_client.client import ClobClient

for sig_type in [0, 1, 2]:
    label = {0: "EOA", 1: "POLY_PROXY", 2: "POLY_GNOSIS_SAFE"}[sig_type]
    print(f"--- signature_type={sig_type} ({label}) ---")
    try:
        kwargs = {"host": "https://clob.polymarket.com", "key": KEY, "chain_id": 137}
        if sig_type != 0:
            kwargs["signature_type"] = sig_type
            kwargs["funder"] = FUNDER
        client = ClobClient(**kwargs)
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        print(f"  API creds derived OK")
        print(f"  get_ok(): {client.get_ok()}")

        # Try to get balance (requires correct auth)
        try:
            bal = client.get_balance_allowance()
            print(f"  get_balance_allowance(): {bal}")
        except Exception as e:
            print(f"  get_balance_allowance() failed: {e}")
    except Exception as e:
        print(f"  FAILED: {e}")
    print()
