---
name: pregame
description: Run the pre-game NBA betting advisor to scan today's games, compute win probabilities, compare to Polymarket odds, and output bet suggestions with Kelly sizing. Use when the user asks for pre-game analysis, daily picks, or betting recommendations.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: [--bankroll 500] [--min-edge 2.0] [--kelly-fraction 0.25] [--model-weight 0.30] [--no-claude] [--no-hold] [--date YYYYMMDD] [--min-speculate-prob 0.72] [--speculate-kelly 0.15] [--hold-threshold 0.70] [--entry-aggression 0.50] [--exit-capture 0.80] [--max-spread 0.08] [--log-level WARNING]
---

# Pre-Game Betting Advisor

Scan today's NBA games with Polymarket markets, compute independent win probabilities using team strength/injuries/H2H, and output bet recommendations with Kelly-optimal sizing.

## Understanding the Request

Parse `$ARGUMENTS` for optional flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `--bankroll N` | 500 | Available bankroll in USDC |
| `--min-edge N` | 2.0 | Minimum edge % to recommend a bet |
| `--kelly-fraction N` | 0.25 | Kelly conservatism (0.25 = quarter-Kelly) |
| `--model-weight N` | 0.30 | Model weight in probability blend (market gets 1-N) |
| `--no-claude` | off | Disable Claude AI qualitative analysis |
| `--no-hold` | off | Hide HOLD recommendations, show only actionable bets |
| `--date YYYYMMDD` | today | Date to scan (e.g. 20260228) |
| `--min-speculate-prob N` | 0.72 | Minimum model probability to trigger SPECULATE verdict |
| `--speculate-kelly N` | 0.15 | Kelly fraction for SPECULATE bets (more conservative) |
| `--hold-threshold N` | 0.70 | Model prob threshold for RESOLUTION (hold-to-resolution) strategy |
| `--entry-aggression N` | 0.50 | Entry price aggression (0=bid, 0.5=mid, 1=ask) |
| `--exit-capture N` | 0.80 | Edge capture fraction for TRADE exit price |
| `--max-spread N` | 0.08 | Max bid-ask spread before liquidity warning |
| `--log-level LEVEL` | WARNING | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

## Build and Run the Command

Construct the command from parsed arguments:

```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame $FLAGS
```

Run with **120000ms Bash timeout** (2 minutes).

## Present Results

After the run completes, summarize:

1. **Games scanned** — How many pre-game NBA games were found today
2. **Markets matched** — How many games had active Polymarket markets
3. **Recommendations** — Present the summary table with separate Buy and Sell action columns:
   - Game (Away @ Home)
   - Model probability vs market probability
   - Edge percentage
   - **Buy**: Limit buy price (smart entry from order book)
   - **Sell**: Limit sell price for TRADE strategy, or `HOLD→$1.00` for RESOLUTION (hold to game resolution)
   - **Expected ROI**: Return on investment for the strategy
   - Suggested bet amount and confidence rating
   - Key factors driving the recommendation
   - Liquidity warnings if spread is too wide
   - Claude AI analysis (for SPECULATE verdicts when --no-claude is not set)
4. **HOLD games** — Brief mention of games where no edge was found (if --no-hold was not set)
5. **Overall assessment** — Any notable patterns (e.g., "heavy favorites across the board", "multiple edges found")

## Execute Bets

After presenting results, for each BET or SPECULATE recommendation that includes an `Execute:` command:

1. Ask the user for confirmation: **"Place $X on TEAM at $Y entry? (Strategy: RESOLUTION/TRADE)"**
2. Only on explicit confirmation (`y`, `yes`, `confirm`), run the execute command:
   ```bash
   cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame.execute --token-id ... --market-id ... --side buy --size ... --price ...
   ```
3. Report the result (order ID on success, error message on failure).
4. **Write to the pregame ledger** after each successful buy. Read and update the file at `polynba/data/pregame_orders/YYYYMMDD.json` (create it on first order of the day). Append an entry with:
   - `order_id`: from the SUCCESS output
   - `game`: e.g. `"NO @ LAC"`
   - `team`: the team bet on
   - `token_id`: from the execute command
   - `market_id`: from the execute command
   - `side`: `"buy"`
   - `shares`: integer shares placed
   - `entry_price`: limit price
   - `strategy`: `"TRADE"` or `"RESOLUTION"`
   - `exit_price`: target sell price for TRADE, `null` for RESOLUTION
   - `status`: `"OPEN"`
   - `filled_shares`: `0`
   - `sell_order_id`: `null`
   - `actual_sell_price`: `null` (populated when sell fills)
   - `sell_trade_id`: `null` (populated when sell fills)
   - `sell_tx_hash`: `null` (populated when sell fills)
   - `pnl`: `null` (populated when sell fills)

   The ledger file format:
   ```json
   {
     "date": "YYYYMMDD",
     "created_at": "ISO timestamp",
     "orders": [ ... ]
   }
   ```
5. Move to the next BET recommendation and repeat.

**Never execute without explicit user confirmation for each bet.**

## Check Order Fills

After placing buy orders, check whether they have been filled:

1. Run the check command using the date's ledger:
   ```bash
   cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame.check_orders --date YYYYMMDD
   ```
2. Present results as a status table showing: game, team, shares, entry, strategy, exit, filled, status.
3. Report the account balance.

No need to pass order IDs — they are read from the ledger file.

## Place Exit Sell Orders

For filled **TRADE** strategy buys, place corresponding limit sell orders at the advisor's exit price:

1. Ask the user for confirmation: **"Place exit sells for all filled TRADE orders?"**
2. On confirmation, run:
   ```bash
   cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.pregame.check_orders --date YYYYMMDD --place-sells
   ```
3. Report each sell order result (order ID on success, error on failure).
4. For **RESOLUTION** strategy orders, no sell is placed — they are held to resolution.
5. Skip unfilled orders and report them as still waiting.

No need for `--sell-targets` JSON — exit prices and token IDs are already in the ledger.

## Record Sell Fills

When a sell order has been filled (status changes from `SELL_PLACED` to sold), query the Polymarket CLOB API for the actual trade details and update the ledger:

1. Load the `.env` file and query the sell order and its associated trade:
   ```bash
   set -a && source /Users/shuhaozhang/Project/PolyNBA/.env && set +a && .venv/bin/python -c "
   import os, json
   from py_clob_client.client import ClobClient
   from py_clob_client.clob_types import TradeParams

   client = ClobClient('https://clob.polymarket.com', key=os.environ['POLYMARKET_PRIVATE_KEY'], chain_id=137, funder=os.environ.get('POLYMARKET_FUNDER_ADDRESS'))
   client.set_api_creds(client.create_or_derive_api_creds())

   # Check sell order status
   resp = client.get_order('SELL_ORDER_ID')
   print(json.dumps(resp, indent=2))

   # Get trade details for actual fill price
   trades = client.get_trades(TradeParams(maker_address=os.environ.get('POLYMARKET_FUNDER_ADDRESS'), market='MARKET_ID'))
   for t in trades:
       print(json.dumps(t, indent=2))
   "
   ```
2. From the trade data, extract:
   - `actual_sell_price`: the `price` field from the trade where our sell order is the `taker_order_id` (or where our address is in `maker_orders`)
   - `sell_trade_id`: the trade `id`
   - `sell_tx_hash`: the `transaction_hash`
   - `pnl`: `(actual_sell_price - entry_price) * shares`
3. Update the ledger entry:
   - Set `status` to `"SOLD"`
   - Add `actual_sell_price`, `sell_trade_id`, `sell_tx_hash`, and `pnl`
4. Note: the `actual_sell_price` may differ from `exit_price` due to price improvement (filled at a better price than the limit).

## Example Invocations

```
/pregame                              -> Default: $500 bankroll, 2% min edge
/pregame --bankroll 1000              -> Higher bankroll
/pregame --min-edge 3.0 --no-hold    -> Only show strong edges
/pregame --log-level INFO             -> Verbose output for debugging
/pregame --model-weight 0.50          -> Trust model more vs market
/pregame --date 20260228              -> Scan a specific date
/pregame --min-speculate-prob 0.80    -> Only speculate on very strong convictions
/pregame --no-claude                  -> SPECULATE based on model threshold only
/pregame --hold-threshold 0.80        -> Only RESOLUTION for very high conviction
/pregame --entry-aggression 0.0       -> Most patient entry (at bid)
/pregame --exit-capture 0.60          -> More conservative exit targets
/pregame --max-spread 0.04            -> Stricter liquidity requirements
```
