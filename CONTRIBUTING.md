# Contributing

Thanks for helping! This is a **paper-only** research project with strict safety rules. Please read [AGENTS.md](AGENTS.md):
its hard safety rules apply to human contributors too.

## Workflow
1. Fork, then create a branch.
2. Set up: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock`.
3. Make your change and add tests for it.
4. Run `.venv/bin/pytest -q tests` and `.venv/bin/python scripts/run_drills.py`. Both must pass.
5. If you changed a typed model, run `scripts/gen_schemas.py` and commit the updated `schemas/`.
6. Open a pull request using the template. Describe any new assumption and add it to `reports/AUDIT.md`.

## Will not be merged
- Live or testnet trading, exchange keys, wallet or withdrawal code.
- LLMs in any trade, risk or mode decision path.
- Weakening risk limits, fail-closed behaviour, append-only storage, auth or the mode ladder.
- Unlabelled synthetic data, fabricated metrics or profit claims.

## Style
Small, typed, deterministic functions; `Decimal` for money; no new dependencies without pinning them in
`requirements.txt` and `requirements.lock`.
