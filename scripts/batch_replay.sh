#!/usr/bin/env bash
# Batch replay: 5 live_rec configs x all live game logs
set -uo pipefail
cd /Users/shuhaozhang/Project/PolyNBA

CONFIGS=(live_rec1 live_rec2 live_rec3 live_rec4 live_rec5)

# Use latest session per game (deduplicate), keep all unique games
GAMES=(
    "20260221185906_ORL_vs_PHX"
    "20260221193126_PHI_vs_NO"
    "20260221201447_MEM_vs_MIA"
    "20260221201548_DET_vs_CHI"
    "20260222173921_DAL_vs_IND"
    "20260223192002_SA_vs_DET"
    "20260223215750_UTAH_vs_HOU"
    "20260224195605_DAL_vs_BKN"
    "20260224195642_OKC_vs_TOR"
    "20260224195652_NY_vs_CLE"
    "20260224200101_PHI_vs_IND"
    "20260224200144_WSH_vs_ATL"
)

OUTDIR="replay_results_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

run_config() {
    local config=$1
    local results_file="$OUTDIR/${config}.csv"
    echo "game,pnl,trades,win,loss" > "$results_file"

    for game in "${GAMES[@]}"; do
        local log_path="logs/live/${game}"
        local outfile="$OUTDIR/${config}_${game}.txt"

        python scripts/replay_strategy.py "$log_path" \
            --config "polynba/config/profiles/${config}.yaml" \
            --json 2>/dev/null > "$outfile" || true

        # Extract from JSON output
        local pnl trades wins losses
        pnl=$(python3 -c "import json; d=json.load(open('$outfile')); print(f\"{d['summary']['realized_pnl']:.2f}\")" 2>/dev/null || echo "0.00")
        trades=$(python3 -c "import json; d=json.load(open('$outfile')); print(d['summary']['total_trades'])" 2>/dev/null || echo "0")
        wins=$(python3 -c "
import json
d=json.load(open('$outfile'))
cp=d.get('closed_positions',[])
w=sum(1 for p in cp if p.get('pnl_usdc',0)>0)
print(w)
" 2>/dev/null || echo "0")
        losses=$(python3 -c "
import json
d=json.load(open('$outfile'))
cp=d.get('closed_positions',[])
l=sum(1 for p in cp if p.get('pnl_usdc',0)<=0)
print(l)
" 2>/dev/null || echo "0")

        # Extract game label
        local label="${game#*_}"  # e.g. "ORL_vs_PHX"
        echo "${label},${pnl},${trades},${wins},${losses}" >> "$results_file"
        echo "  ${config} | ${label} | PnL: \$${pnl} | Trades: ${trades}"
    done
}

echo "=== BATCH REPLAY: 5 configs x ${#GAMES[@]} live games ==="
echo "Output directory: $OUTDIR"
echo ""

# Run all 5 configs in parallel
pids=()
for config in "${CONFIGS[@]}"; do
    run_config "$config" &
    pids+=($!)
done

for pid in "${pids[@]}"; do
    wait "$pid" || true
done

echo ""
echo "=== ALL REPLAYS COMPLETE ==="
echo ""

# Print summary table
echo "REPLAY RESULTS (Realized PnL / Trades)"
echo "======================================="
printf "%-16s" "Game"
for config in "${CONFIGS[@]}"; do
    printf " | %-16s" "$config"
done
echo ""
printf "%-16s" "----------------"
for config in "${CONFIGS[@]}"; do
    printf " | %-16s" "----------------"
done
echo ""

for game in "${GAMES[@]}"; do
    label="${game#*_}"
    printf "%-16s" "$label"
    for config in "${CONFIGS[@]}"; do
        local_file="$OUTDIR/${config}.csv"
        row=$(grep "^${label}," "$local_file" 2>/dev/null || echo "${label},0.00,0,0,0")
        pnl=$(echo "$row" | cut -d, -f2)
        trades=$(echo "$row" | cut -d, -f3)
        printf " | %8s (%2st)" "\$${pnl}" "$trades"
    done
    echo ""
done

# Per-config totals
echo ""
printf "%-16s" "TOTAL"
for config in "${CONFIGS[@]}"; do
    local_file="$OUTDIR/${config}.csv"
    total=$(tail -n+2 "$local_file" | awk -F, '{s+=$2} END {printf "%.2f", s}')
    total_trades=$(tail -n+2 "$local_file" | awk -F, '{s+=$3} END {print s}')
    printf " | %8s (%2st)" "\$${total}" "$total_trades"
done
echo ""

echo ""
echo "Results saved to: $OUTDIR/"
