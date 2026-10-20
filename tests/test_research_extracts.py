"""Clean-room research extracts: candlestick patterns (no lookahead, prefix invariance, validation, not wired)
and SKILL.md manifests."""
import json, re
from decimal import Decimal as D
from pathlib import Path
import pytest
from crew import skills as SK
from crew.patterns import detect
ROOT = Path(__file__).resolve().parents[1]

def _fixture_ohlc(symbol="BTCUSDT", bucket=900):
    rows = [json.loads(l) for l in (ROOT/"fixtures"/"binance_replay_sample.jsonl").read_text().splitlines()]
    out = {}
    for r in rows:
        if r.get("type") != "market" or r["symbol"] != symbol: continue
        m = (D(str(r["bid"])) + D(str(r["ask"]))) / 2; b = int(r["ts"]) // bucket
        o = out.get(b); out[b] = [m, m, m, m] if o is None else [o[0], max(o[1], m), min(o[2], m), m]
    v = list(out.values()); return [x[0] for x in v], [x[1] for x in v], [x[2] for x in v], [x[3] for x in v]

def test_textbook_cases():
    # bullish engulfing: red bar then a larger green bar covering it
    assert "bullish_engulfing" in detect([10, 9.4], [10.1, 10.6], [9.4, 9.3], [9.5, 10.5])[1]
    assert "bearish_engulfing" in detect([10, 10.6], [10.6, 10.7], [9.9, 9.4], [10.5, 9.5])[1]
    assert "doji" in detect([10], [10.5], [9.5], [10.02])[0]
    # hammer after a 3-bar downtrend: small body at top, long lower shadow
    o, h, l, c = [12, 11, 10, 9.0], [12.1, 11.1, 10.1, 9.12], [11.4, 10.4, 9.4, 8.0], [11.5, 10.5, 9.5, 9.1]
    assert "hammer" in detect(o, h, l, c)[3]
    assert "three_white_soldiers" in detect([10, 10.5, 11], [10.6, 11.1, 11.6], [9.9, 10.4, 10.9], [10.5, 11, 11.5])[2]
    assert "three_black_crows" in detect([11.5, 11, 10.5], [11.6, 11.1, 10.6], [10.9, 10.4, 9.9], [11, 10.5, 10])[2]

def test_prefix_invariance_and_no_lookahead_on_fixture():
    o, h, l, c = _fixture_ohlc(); full = detect(o, h, l, c)
    assert len(full) > 200 and any(full)
    for n in (5, 50, 150, len(o) // 2): assert detect(o[:n], h[:n], l[:n], c[:n]) == full[:n], n
    k = 120; f = lambda xs: xs[:k] + [x * 3 for x in xs[k:]]
    assert detect(f(o), f(h), f(l), f(c))[:k] == full[:k]

@pytest.mark.parametrize("bad", [([1], [2], [0.5], ["NaN"]), ([1], [0.9], [0.5], [1]), ([1], [2], [0.5], [-1]), ([1, 2], [2], [0.5], [1]),
                                 ([1], [2], [1.5], [1])])
def test_invalid_bars_rejected(bad):
    with pytest.raises(Exception): detect(*bad)

def test_no_signal_and_not_wired():
    out = detect([10, 9.4], [10.1, 10.6], [9.4, 9.3], [9.5, 10.5])
    assert all(isinstance(x, list) and all(isinstance(n, str) for n in x) for x in out)
    assert SK.REGISTRY["candle_patterns"].research_only
    src = "".join((ROOT/"crew"/f).read_text() for f in ("engine.py", "risk.py", "modes.py", "desk_d4.py", "killswitch.py", "overseer.py", "agents.py", "connectors.py"))
    assert "patterns" not in src and "candle_patterns" not in src

REQ = ("name", "callable", "category", "research_only", "inputs", "output", "lookahead", "data_status", "wired_into_execution", "attribution")
def test_skill_manifests_valid():
    ms = sorted((ROOT/"research_skills").glob("*/SKILL.md")); assert ms
    for m in ms:
        fm = re.match(r"^---\n(.*?)\n---\n", m.read_text(), re.S); assert fm, m
        meta = dict(ln.split(": ", 1) for ln in fm.group(1).splitlines())
        for k in REQ: assert k in meta, (m, k)
        assert meta["research_only"] == "true" and meta["wired_into_execution"] == "false" and meta["category"] == "research"
        name = re.search(r'REGISTRY\["(\w+)"\]', meta["callable"]).group(1)
        assert name == meta["name"] == m.parent.name and SK.REGISTRY[name].research_only
        assert (ROOT/meta["attribution"].split(" ")[0]).exists()
