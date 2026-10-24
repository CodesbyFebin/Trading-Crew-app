# Contributing

Thanks for helping!

Trading Crew is a research and paper-execution project with a read-only public market-data feed. Authenticated production trading is not qualified. Please keep documentation, UI labels, and release notes aligned with the evidence in [`reports/LIVE_GATES.md`](reports/LIVE_GATES.md); don't describe local tests or public prices as proof of live order readiness or strategy performance.

## Workflow
1. Fork, then create a branch.
2. Set up: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock`.
3. Make your change and add tests for it where practical.
4. Run `python -m pytest -q tests`, `python scripts/run_drills.py`, and relevant static checks. Include the results and any skips or unavailable integration gates in the PR description.
5. If you changed a typed model, run `scripts/gen_schemas.py` and commit the updated `schemas/`.
6. Open a pull request using the template. Describe the upgrade and any assumptions you changed.

## Safety and evidence
- Never commit API keys, access tokens, wallet secrets, or production credentials. Use narrowly scoped secrets outside the repository.
- Keep testnet and production endpoints explicitly separated. A testnet contract test is not evidence of a completed remote order lifecycle.
- Preserve fail-closed validation, auditability, and risk-limit tests when changing execution, authentication, storage, or mode promotion.
- Any venue integration must document order submission, cancellation, fills, partial fills, reconciliation, rate limits, and kill behavior; mark untested paths clearly.
- Strategy and dashboard metrics must retain their data provenance. Do not present synthetic or replay data as live portfolio data.
- Changes to risk limits, mode promotion, or live execution require focused tests and explicit documentation of the changed risk behavior.
- Add or update tests for behavior changes and keep third-party code properly attributed and licensed.

## Style
Small, typed, deterministic functions where it still fits; `Decimal` for money when doing new money math; pin new dependencies in `requirements.txt` and `requirements.lock`.

## Release artifacts

Version tags (`v*`) trigger the packaging workflow. It runs its configured checks, builds platform artifacts, and attaches checksums to a GitHub pre-release. Do not create a release tag until the intended source commit and required CI checks have been reviewed. Releases are not evidence of production trading qualification.
