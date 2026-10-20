# Research extracts: triage of 29 repositories (2026-10-21 IST)

Method: GitHub API metadata for every repo. Shallow clones (`git clone --depth 1`) into `/tmp/repo-triage/` only for
repos not excluded below; **no third-party code, installer or script was executed**. Live-trading / vendor signals are
grep heuristics over source (counts are not audits). Licence rule for this MIT repo: AGPL/GPL, "non-commercial" and
no-licence repos are **ideas only**; permissive (MIT/Apache-2.0) code could be copied with attribution, but in this
round nothing was copied: the one extraction is clean-room.

| Repo | Licence | Stars / last push | What it is | Live / custody paths | Verdict | Reason |
|---|---|---|---|---|---|---|
| Fincept-Corporation/FinceptTerminal | AGPL-3.0 | 32.8k / 2026-10-13 | C++ finance terminal | n/a (not cloned, 790 MB) | REJECT (ideas only) | AGPL incompatible with MIT; size |
| fsdbtrenbzsern/FinceptTerminal | NOASSERTION | 20 / 2026-06-19 | non-fork copy of FinceptTerminal | not inspected | EXCLUDED, not cloned | suspected impersonation (copy published as non-fork) |
| bloombergterminal-app/bloomberg-terminal-free | MIT (claimed) | 3 / 2026-09-03 | "Bloomberg Terminal Free" keyword-stuffed repo | not inspected | EXCLUDED, not cloned | suspected impersonation / malware lure |
| HKUDS/Vibe-Trading | MIT | 36.0k / 2026-10-20 | LLM trading agent, 100+ SKILL.md skills, swarm | yes: `agent/src/live/*`, broker loaders (OKX, Binance, IBKR, Alpaca), telemetry-ish store/bridge files | EXTRACT (idea) | candlestick pattern list + SKILL.md layout, clean-room; nothing else (LLM decides trades, live routes) |
| OpenByteInc/QuantDinger | Apache-2.0 | 13.0k / 2026-10-19 | "AI trading OS" | yes: Binance/OKX/Alpaca/IBKR integrations; README `curl … \| bash` installer | REJECT | live exchange execution core; installer pattern |
| simonlin1212/Vibe-Research | MIT | 2.8k / 2026-10-18 | TS research workbench (A/US/HK) | minor; AKShare/Tushare/yfinance; analytics hooks | REJECT (ideas only) | TypeScript web stack, Chinese-market vendors; nothing deterministic we lack |
| simonlin1212/vibe-astock | Apache-2.0 | 787 / 2026-10-18 | A-share short-term review workbench | minor; analytics hooks | REJECT | A-share specific, TS stack |
| gameworkerkim/vibe-investing | none | 346 / 2026-10-15 | curated notes/columns + misc code | various vendors | REJECT | no licence; mostly articles |
| wanghsinche/vibe-trading | MIT | 194 / 2025-10-29 | 7 files, no README | none | REJECT | no substantive content |
| Signal-Execution-Labs/forex-trading-ai-agent | MIT | 171 / 2026-09-14 | AI trading platform (crypto/stocks/forex) | yes: MetaTrader, Binance, CCXT | REJECT | live execution bot |
| hopit-ai/india-trade-cli | MIT | 121 / 2026-09-03 | 7 LLM analysts → trade plans, India | yes: Fyers/Zerodha/Upstox/Dhan brokers | REJECT | LLM trade plans + live brokers (Track 3 archived anyway) |
| VibeTradingLabs/vibetrading | none | 101 / 2026-03-23 | NL → strategy framework | yes: Hyperliquid, Binance, CCXT | REJECT | no licence; live execution |
| nimin1/system-design-vibecoding | MIT | 85 / 2026-01-01 | system-design course notes | none | REJECT | not trading code; general reading only |
| sqyangx/quantlab | none | 81 / 2026-06-09 | A-share quant lab (Qlib etc.) | none found | REJECT | no licence; A-share/Qlib stack |
| encyc/vibe-trading | none | 69 / 2026-08-04 | multi-agent LLM crypto trader | yes: Binance/OKX | REJECT | no licence; LLM-driven live trading |
| dcaoyuan/vibetrader | Apache-2.0 | 55 / 2026-04-21 | TS charting, PineTS indicators | none found | REJECT (ideas only) | TS/Pine stack; our indicators already cover the deterministic part |
| Jamailar/VibeTrading | MIT **Non-Commercial** | 39 / 2025-12-13 | Electron chat-to-strategy app | minor: CCXT/Binance | REJECT | non-commercial licence incompatible with MIT |
| VictorVVedtion/vibe-sensei | MIT | 24 / 2026-04-15 | TS "trading terminal" with persona LLMs | yes: CCXT/OANDA/Alpaca; Sentry/PostHog-style hooks | REJECT | LLM personas, telemetry, live brokers |
| spyderweb47/Vibe-Trade | none | 16 / 2026-04-22 | agent + SKILL.md skills | CCXT, yfinance | IDEA ONLY | SKILL.md manifest idea (credited in docs/research-skill-format.md); no licence, no code |
| whisdev/rust-copy-trading | none | 14 / 2025-06-22 | Solana copy-trading bot | live by design | EXCLUDED, not cloned | copy-trading / live bot |
| BizShibe/solana-jito-shredstream-copy-trading-bot | none | 9 / 2026-06-18 | Solana shredstream copy-trading | live by design | EXCLUDED, not cloned | copy-trading / live bot |
| NanoHux/vibetrading | MIT | 7 / 2025-10-29 | wallet auth, deposits, Hyperliquid | custody + live | REJECT | custody (deposits) + live execution |
| shao60533/michael-vibe-trading | MIT | 6 / 2026-07-14 | hosted wrapper around vibe-trading-ai presets | none | REJECT | thin wrapper over a PyPI package; nothing deterministic |
| jo-inc/camofox-browser | MIT | 11.8k / 2026-10-16 | stealth browser, Cloudflare bypass | — | EXCLUDED, not cloned | anti-detection / bot-bypass tooling |
| Johell1NS/browser-search | MIT | 537 / 2026-09-02 | search skill using Camofox | — | EXCLUDED, not cloned | depends on anti-detection browser |
| redf0x1/camofox-browser | MIT | 425 / 2026-09-22 | anti-detection browser server | — | EXCLUDED, not cloned | anti-detection tooling |
| redf0x1/camofox-mcp | MIT | 119 / 2026-09-05 | anti-detection browser MCP | — | EXCLUDED, not cloned | anti-detection tooling |
| yelban/camofox-browser-skills | MIT | 16 / 2026-02-12 | Camoufox automation skill | — | EXCLUDED, not cloned | anti-detection tooling |
| a0-community-plugins/camofox-plugin | none | 13 / 2026-06-13 | CamoFox plugin for Agent Zero | — | EXCLUDED, not cloned | anti-detection tooling; no licence |

No obfuscated payloads were found by a simple pattern scan of the cloned repos (hits were ordinary `curl … | sh`
installer instructions in READMEs: QuantDinger, encyc uv, vibe-sensei bun). Telemetry/analytics hooks were seen in
vibe-sensei, Vibe-Research, vibe-astock and HKUDS (heuristic). The bundled advisory prompt pattern idea was already
implemented in the TA research desk (PR #2), so no further prompts were added here.

## What was extracted
- `crew/patterns.py` + `candle_patterns` research-only skill: clean-room Decimal candlestick detectors (11 patterns),
  pattern names only, no score/signal, validated OHLC, prefix-invariance and no-lookahead tests on the fixture.
- `research_skills/<name>/SKILL.md` manifest format (`docs/research-skill-format.md`), metadata only, validated by tests.
- Attribution: `third_party/HKUDS_Vibe-Trading/{LICENSE,NOTICE.md}` (idea only).
