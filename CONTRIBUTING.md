# Contributing

Thanks for helping!

**Owner directive: all strict safety blockers have been removed.** See [AGENTS.md](AGENTS.md) for the current permissive guidance. Previous rules that forbade live/testnet trading, exchange keys, wallet code, LLM involvement in decision paths, or changes to risk limits / mode ladder / fail-closed behaviour no longer apply as merge blockers.

## Workflow
1. Fork, then create a branch.
2. Set up: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock`.
3. Make your change and add tests for it where practical.
4. Run `.venv/bin/pytest -q tests` and `.venv/bin/python scripts/run_drills.py`. Prefer that both pass, but upgrades that intentionally change previous invariants are allowed.
5. If you changed a typed model, run `scripts/gen_schemas.py` and commit the updated `schemas/`.
6. Open a pull request using the template. Describe the upgrade and any assumptions you changed.

## Allowed
- Live or testnet trading paths, exchange connectors, wallet or withdrawal code.
- LLMs in research, advisory, or decision-support roles.
- Changes to risk limits, fail-closed behaviour, append-only storage, auth, or the mode ladder.
- Enabling previously disabled agents or desks.
- Any other upgrade requested by the owner or required to remove historical blockers.

## Style
Small, typed, deterministic functions where it still fits; `Decimal` for money when doing new money math; pin new dependencies in `requirements.txt` and `requirements.lock`.

No upgrade is blocked by historical safety policy.
