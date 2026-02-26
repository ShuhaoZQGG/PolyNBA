#!/usr/bin/env bash
# Batch test: 5 configs x 10 scenarios
# Runs configs in parallel (5 at a time), scenarios sequentially per config
set -uo pipefail
cd /Users/shuhaozhang/Project/PolyNBA

CONFIGS=(live_rec1 live_rec2 live_rec3 live_rec4 live_rec5)
SCENARIOS=(home_blowout away_blowout close_game home_comeback away_comeback failed_comeback overtime_thriller wire_to_wire late_collapse back_and_forth)

OUTDIR="batch_results_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"

run_config() {
    local config=$1
    local config_idx=$2
    local results_file="$OUTDIR/${config}.csv"
    echo "scenario,pnl,trades,winrate" > "$results_file"

    local scen_idx=0
    for scenario in "${SCENARIOS[@]}"; do
        local instance_id=$((500 + config_idx * 20 + scen_idx))
        local outfile="$OUTDIR/${config}_${scenario}.txt"

        python -m polynba \
            --config "polynba/config/profiles/${config}.yaml" \
            --test-game --test-game-scenario "$scenario" \
            --interval 1 --no-claude --instance-id "$instance_id" \
            --log-level WARNING 2>&1 > "$outfile" || true

        # Extract metrics from PERFORMANCE section
        local pnl trades winrate
        pnl=$(grep -m1 'Realized PnL:' "$outfile" 2>/dev/null | sed 's/.*\$\s*//' | tr -d ' ' || echo "0.00")
        trades=$(grep -m1 'Total trades:' "$outfile" 2>/dev/null | grep -oE '[0-9]+' | tail -1 || echo "0")
        winrate=$(grep -m1 'Win rate:' "$outfile" 2>/dev/null | grep -oE '[0-9.]+%' || echo "0.0%")

        echo "${scenario},${pnl},${trades},${winrate}" >> "$results_file"
        echo "  ${config} | ${scenario} | PnL: \$${pnl} | Trades: ${trades} | WR: ${winrate}"
        scen_idx=$((scen_idx + 1))
    done
}

echo "=== BATCH TEST: 5 configs x 10 scenarios ==="
echo "Output directory: $OUTDIR"
echo ""

# Run all 5 configs in parallel
pids=()
for i in "${!CONFIGS[@]}"; do
    run_config "${CONFIGS[$i]}" "$i" &
    pids+=($!)
done

# Wait for all
for pid in "${pids[@]}"; do
    wait "$pid" || true
done

echo ""
echo "=== ALL RUNS COMPLETE ==="
echo ""

# Print summary table
echo "SUMMARY TABLE (Realized PnL / Trades)"
echo "======================================"
printf "%-20s" "Scenario"
for config in "${CONFIGS[@]}"; do
    printf " | %-16s" "$config"
done
echo ""
printf "%-20s" "--------------------"
for config in "${CONFIGS[@]}"; do
    printf " | %-16s" "----------------"
done
echo ""

for scenario in "${SCENARIOS[@]}"; do
    printf "%-20s" "$scenario"
    for config in "${CONFIGS[@]}"; do
        local_file="$OUTDIR/${config}.csv"
        row=$(grep "^${scenario}," "$local_file" 2>/dev/null || echo "${scenario},0.00,0,0.0%")
        pnl=$(echo "$row" | cut -d, -f2)
        trades=$(echo "$row" | cut -d, -f3)
        printf " | %8s (%2st)" "\$${pnl}" "$trades"
    done
    echo ""
done

# Per-config totals
echo ""
printf "%-20s" "TOTAL"
for config in "${CONFIGS[@]}"; do
    local_file="$OUTDIR/${config}.csv"
    total=$(tail -n+2 "$local_file" | awk -F, '{s+=$2} END {printf "%.2f", s}')
    total_trades=$(tail -n+2 "$local_file" | awk -F, '{s+=$3} END {print s}')
    printf " | %8s (%2st)" "\$${total}" "$total_trades"
done
echo ""

echo ""
echo "Results saved to: $OUTDIR/"
