---
name: candle_patterns
callable: crew.skills.REGISTRY["candle_patterns"]
category: research
research_only: true
inputs: open_, high, low, close (equal-length lists of positive finite numbers), doji_body_pct, shadow_ratio, trend_n
output: list of pattern names per bar; no score, no signal, no position size
lookahead: none (label at bar i uses bars <= i; tests/test_research_extracts.py)
data_status: caller must label input data (SYNTHETIC_REPLAY / UNVERIFIED_THIRD_PARTY); the skill does not fetch data
wired_into_execution: false
attribution: third_party/HKUDS_Vibe-Trading/NOTICE.md (idea only, MIT)
---
# Candlestick patterns (research annotation)

Detects doji, hammer, shooting star, bullish/bearish engulfing, bullish/bearish harami, morning/evening star,
three white soldiers and three black crows using textbook definitions. Labels are annotations for research
reports. They are not evidence of an edge and never reach the engine, risk engine or order path.
