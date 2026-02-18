"""Diagnostic: test order signing with neg_risk flag."""

import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions
from py_clob_client.order_builder.constants import BUY

load_dotenv()

KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER = os.getenv("POLYMARKET_FUNDER_ADDRESS")
HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

# Active token_id from your logs
TOKEN_ID = "115398480700108494801153059742450217770464747356385312544248721773516157633342"

# Small test order at low price (won't fill)
order_args = OrderArgs(
    token_id=TOKEN_ID,
    price=0.01,
    size=5.0,
    side=BUY,
)

print(f"Private key: {KEY[:6]}...{KEY[-4:]}")
print(f"Funder: {FUNDER}")
print()

# signature_type=1 is POLY_PROXY (Magic/email wallets)
client = ClobClient(
    HOST,
    key=KEY,
    chain_id=CHAIN_ID,
    signature_type=1,
    funder=FUNDER,
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# Check if this token is neg-risk
neg_risk = client.get_neg_risk(TOKEN_ID)
print(f"Token neg_risk: {neg_risk}")
print()

# Test with and without neg_risk flag
for use_neg_risk in [False, True]:
    label = "with neg_risk=True" if use_neg_risk else "without neg_risk"
    print(f"--- Testing {label} ---")
    try:
        if use_neg_risk:
            signed = client.create_order(order_args, PartialCreateOrderOptions(neg_risk=True))
        else:
            signed = client.create_order(order_args)
        resp = client.post_order(signed)
        print(f"  SUCCESS: {resp}")
        order_id = resp.get("orderID")
        if order_id:
            client.cancel(order_id)
            print(f"  Cancelled test order {order_id}")
        break
    except Exception as e:
        print(f"  FAILED: {e}")
    print()
