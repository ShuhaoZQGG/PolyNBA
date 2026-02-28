---
name: validate-apis
description: Validate all external API integrations (ESPN, NBA.com, Polymarket) by hitting live endpoints and checking response parsing. Use when the user wants to check APIs, validate endpoints, verify parsing, health check, or diagnose data issues.
allowed-tools: Bash, Read, Glob, Grep
argument-hint: [--section espn|nba|polymarket] [--verbose]
---

# Validate APIs Skill

Test all external API integrations and parsing pipelines against live endpoints.

## What It Validates

| # | Section | Endpoint | Parser | What's Checked |
|---|---------|----------|--------|----------------|
| 1a | ESPN Scoreboard | `/apis/site/v2/.../scoreboard` | `ESPNParser.parse_scoreboard` | Events present, GameSummary fields (game_id, teams, status, period) |
| 1b | ESPN Game Summary | `/apis/site/v2/.../summary` | `ESPNParser.parse_game_summary` | GameState fields (boxscore stats, period scores, recent plays) |
| 1c | ESPN Team Stats | `/teams/{id}/statistics` + `/teams/{id}` | `ESPNParser.parse_team_stats` | TeamStats fields (record, PPG, ratings, splits, net rating) |
| 1d | ESPN Injuries | `/injuries` | `ESPNParser.parse_injuries` | Injury parsing, status normalization, team grouping |
| 1e | ESPN Standings | `/apis/v2/.../standings` | `ESPNParser.parse_standings` | Conference groups, team rankings, win/loss records |
| 2a | NBA.com Scoreboard | `cdn.nba.com/.../todaysScoreboard_00.json` | `NBAParser.parse_scoreboard` | GameSummary fields, ISO duration parsing |
| 2b | NBA.com Boxscore | `cdn.nba.com/.../boxscore_{id}.json` | `NBAParser.parse_boxscore` | GameState fields (gracefully handles 403 for pre-game) |
| 3a | Polymarket Discovery | `gamma-api.polymarket.com/series/10345` | `MarketDiscovery.discover_nba_markets` | Market discovery, team extraction, moneyline filtering, token IDs |
| 3b | Polymarket CLOB | `clob.polymarket.com` order books | `PriceFetcher.get_market_prices` | Mid prices (0-1 range), bid < ask, price sum ~1.0, depth, spread |

## Understanding the Request

Parse `$ARGUMENTS` to determine scope:

### Section filter (`--section`)
- `espn` — Run only ESPN tests (1a-1e)
- `nba` — Run only NBA.com CDN tests (2a-2b)
- `polymarket` — Run only Polymarket tests (3a-3b)
- *(omit)* — Run all sections (default)

### Verbose mode (`--verbose`)
If present, add `--log-level DEBUG` equivalent context to the output.

## Build and Run the Command

### Full validation (default):
```bash
cd /Users/shuhaozhang/Project/PolyNBA && .venv/bin/python -m polynba.tests.validate_apis
```

### Section-specific validation:
If the user specified `--section`, run the full script but tell the user which sections to focus on in the summary. The script always runs all sections.

Run with **2-minute Bash timeout** (120000ms).

## Present Results

After the run completes, summarize:

1. **Overall status** — How many sections passed/failed out of total
2. **Per-section results** — List each section with pass/fail and key metrics:
   - ESPN Scoreboard: N games found
   - ESPN Game Summary: game status, scores, stats availability
   - ESPN Team Stats: team name, record, key ratings
   - ESPN Injuries: N injuries across N teams
   - ESPN Standings: N teams parsed
   - NBA.com Scoreboard: N games found
   - NBA.com Boxscore: parsed or gracefully handled pre-game
   - Polymarket Discovery: N markets found, sample matchups
   - Polymarket CLOB: prices, spread, liquidity status
3. **Issues found** — Any failures or warnings with suggested fixes
4. **Bugs fixed** — If any parsing bugs were discovered and fixed during validation, note them

### If failures occur:

For each failure, diagnose:
1. **Is it an API issue?** (endpoint down, rate-limited, format changed)
2. **Is it a parsing bug?** (our code doesn't handle the response correctly)
3. **Is it expected?** (e.g., no games today, offseason, pre-game 403)

If it's a parsing bug, read the relevant parser file and the raw response to propose a fix.

## Example Invocations

```
/validate-apis                     → Run all validations
/validate-apis --section espn      → ESPN only
/validate-apis --section polymarket → Polymarket only
/validate-apis --verbose           → Full output with all checks
```
