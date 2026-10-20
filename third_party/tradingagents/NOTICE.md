# Third-party notice: TradingAgents

Portions of `crew/research_ta.py` (the market-analyst and bull/bear researcher prompt patterns) are adapted from
TradingAgents by Tauric Research, https://github.com/TauricResearch/TradingAgents, commit `e8f5503` (v0.7.0),
files `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/researchers/bull_researcher.py`
and `tradingagents/agents/researchers/bear_researcher.py`.

Licensed under the Apache License, Version 2.0 (full text: `third_party/tradingagents/LICENSE`).

Changes made: prompts were shortened and rewritten for a paper-only research context; tool calls, ratings,
trader / risk-debate / portfolio-manager roles, memory/reflection, post-screening (TypeSafe), ChatGPT login,
LangChain/LangGraph and all data vendors were NOT ported. No TradingAgents code is imported or vendored.
