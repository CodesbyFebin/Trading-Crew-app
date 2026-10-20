import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crew import backtest
r = backtest.run(); print(backtest.save(r)); [print(v) for v in r["variants"]]
