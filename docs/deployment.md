# Deployment

## Quickstart

### Local (Python 3.13)
```bash
git clone https://github.com/CodesbyFebin/Trading-Crew-app
cd Trading-Crew-app
cp .env.example .env          # optional: fill in tokens; leave LLM keys empty if you don't want JEV answers
scripts/run_all.sh            # venv + pinned deps, pytest, drills, paper day, backtests, then serves 127.0.0.1:8795
```
If you did not set tokens, `run_all.sh` generates throwaway ones and writes them to `var/session.env` (mode 600, gitignored).
It does not print them. Open http://127.0.0.1:8795/ and paste a token into the sign-in form.

### Docker
```bash
cp .env.example .env    # set CREW_*_TOKEN, CREW_APPROVAL_HMAC_KEY and POSTGRES_PASSWORD
docker compose up --build
```
- The image is `python:3.13-slim`, runs as non-root uid 10001 and contains no secrets.
- Compose starts the app plus `postgres:17-alpine` and `redis:7-alpine`.
- Verified so far: the image builds, and the container serves the API on SQLite.
- **Not yet verified:** the app reaching Postgres inside Docker, and `docker compose` end-to-end (see
  [known limitations](#audit-summary-and-known-limitations)).
- Redis is provisioned, but the runtime engine does not use a bus yet (only the drills do).

## Configuration and environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LIVE_ENABLED` | opt-in mode-promotion flag; not an order capability by itself | `false` |
| `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET` | optional credentials for the isolated Binance Spot Testnet client only | unset |
| `CREW_OWNER_TOKEN` / `CREW_OPERATOR_TOKEN` / `CREW_VIEWER_TOKEN` | API role tokens | none (required) |
| `CREW_APPROVAL_HMAC_KEY` | signs owner approvals | none (approvals cannot be signed) |
| `CREW_OWNER_TOTP_SECRET` | optional TOTP for owner actions | unset = disabled |
| `DATABASE_URL` | Postgres for ledger and shared memory | unset = SQLite |
| `CREW_LEDGER_PATH` | persistent SQLite ledger/audit DB, including restart-safe kill state | `var/trading_crew.db` |
| `DB_CONNECT_TIMEOUT_S` | Postgres connect timeout | 10 |
| `CREW_MEMORY_PATH` | SQLite path for shared memory | `var/shared_memory.db` |
| `OPENROUTER_API_KEY`, `KILOCODE_API_KEY`, `KILOCODE_BASE_URL`, `GROQ_API_KEY`, `GROQ_MODEL`, `CLINE_API_KEY`, `CLINE_MODEL` | advisory LLM gateway | unset = NOT CONFIGURED |
| `INDIATRADER_ROOT` | path to the archived India project (D5 replay) | `/workspace/indiatrader` |
| `TEST_DATABASE_URL` | enables the Postgres tests | unset = skipped |

Files:
- `config/limits.json`: hard risk limits (immutable at runtime).
- `config/llm_routing.json`: providers, fallback order and agent-to-model mapping.
- `config/llm_sources.json`: the verified model-list snapshot.

### Binance Spot Testnet contract checks

`crew.binance_testnet.BinanceSpotTestnet` is a standalone, fixed-host client for Binance Spot Testnet. It is not wired into the strategy engine or live connector registry, cannot be configured with a production host, supports limit orders only, validates current exchange quantity/price filters, and uses a client order ID. A network timeout after submitting an order is an ambiguous outcome; query by client order ID before any retry.

The client defaults to no network activity until a method is called. For an account-authentication check, create a **Testnet-only** key on Binance Spot Testnet and set `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_API_SECRET` in your shell, then run a local Python call to `BinanceSpotTestnet().account()`. Never use a production key in these variables. Offline contract tests do not count as a remote Testnet pass, and Testnet success does not qualify a production strategy or live account. No production trading route is provided.
