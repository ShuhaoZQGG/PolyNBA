"""One-time setup: approve Polymarket exchange contracts to spend USDC and conditional tokens.

Requires:
  - POLYMARKET_PRIVATE_KEY in .env
  - Small amount of POL in the wallet for gas (~0.1 POL)
  - pip install web3 python-dotenv

Usage:
  python scripts/setup_allowances.py
"""

import os
import sys
import time

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
if not PRIVATE_KEY:
    print("Error: POLYMARKET_PRIVATE_KEY not set in .env")
    sys.exit(1)

RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
CHAIN_ID = 137

# Contract addresses (Polygon mainnet)
USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# Exchange contracts that need approval
EXCHANGES = {
    "CTF Exchange": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "Neg Risk CTF Exchange": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "Neg Risk Adapter": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
}

# ABIs (minimal, just approve/setApprovalForAll)
ERC20_ABI = '[{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"}]'
ERC1155_ABI = '[{"inputs":[{"name":"operator","type":"address"},{"name":"approved","type":"bool"}],"name":"setApprovalForAll","outputs":[],"type":"function"}]'

MAX_UINT256 = 2**256 - 1


def main():
    web3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not web3.is_connected():
        print(f"Error: Cannot connect to {RPC_URL}")
        sys.exit(1)

    account = web3.eth.account.from_key(PRIVATE_KEY)
    address = account.address
    print(f"Wallet: {address}")

    balance_wei = web3.eth.get_balance(address)
    balance_pol = web3.from_wei(balance_wei, "ether")
    print(f"POL balance: {balance_pol:.4f}")

    if balance_pol < 0.01:
        print("Warning: Very low POL balance, may not have enough for gas")

    usdc = web3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
    ctf = web3.eth.contract(address=Web3.to_checksum_address(CONDITIONAL_TOKENS), abi=ERC1155_ABI)

    tx_count = 0
    for name, exchange_addr in EXCHANGES.items():
        exchange = Web3.to_checksum_address(exchange_addr)

        # Approve USDC
        print(f"\nApproving USDC for {name} ({exchange_addr[:10]}...)...")
        nonce = web3.eth.get_transaction_count(address)
        tx = usdc.functions.approve(exchange, MAX_UINT256).build_transaction({
            "chainId": CHAIN_ID,
            "from": address,
            "nonce": nonce,
            "gas": 60_000,
            "maxFeePerGas": web3.eth.gas_price * 2,
            "maxPriorityFeePerGas": web3.to_wei(30, "gwei"),
        })
        signed = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  USDC approve tx: {tx_hash.hex()}")
        web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print("  Confirmed")
        tx_count += 1

        # Approve Conditional Tokens
        print(f"Approving Conditional Tokens for {name}...")
        nonce = web3.eth.get_transaction_count(address)
        tx = ctf.functions.setApprovalForAll(exchange, True).build_transaction({
            "chainId": CHAIN_ID,
            "from": address,
            "nonce": nonce,
            "gas": 60_000,
            "maxFeePerGas": web3.eth.gas_price * 2,
            "maxPriorityFeePerGas": web3.to_wei(30, "gwei"),
        })
        signed = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"  CTF approve tx: {tx_hash.hex()}")
        web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        print("  Confirmed")
        tx_count += 1

        time.sleep(1)  # Brief pause between batches

    print(f"\nDone! {tx_count} approval transactions confirmed.")
    print("You can now place orders via the CLOB API.")


if __name__ == "__main__":
    main()
