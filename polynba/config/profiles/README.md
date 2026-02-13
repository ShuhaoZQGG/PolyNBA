# Profile configs

One file per combination; name freely; add as many as you need.

Run a profile with:

```bash
python -m polynba --config polynba/config/profiles/<filename>.yaml
```

Example: `python -m polynba --config polynba/config/profiles/live_minimal.yaml`

To add a new combination, copy an existing profile YAML, rename it, and edit `mode`, `active_strategies`, `bankroll`, `risk`, and `allocation` as needed. CLI flags (e.g. `--bankroll`, `--strategies`) still override the chosen profile.
