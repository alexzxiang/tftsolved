# Pixel reading of your units on a real Set 19 PBE frame: health bars (6 on board + 4 on the bench) and,
# when the trained item model exists (data/models/items.mlmodel, gitignored), the item under the first unit.
#   python3 -I tests/test_units.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "tests/fixtures/pbe_set19_3-1.png").exists():      # a PBE game screenshot: kept private (player names)
    print("skip: needs tests/fixtures/pbe_set19_3-1.png (a private game screenshot)")
    sys.exit()
sys.path.insert(0, str(ROOT / "capture"))
from hud import TOOL, ocr  # noqa: E402

ocr(ROOT / "tests/fixtures/pbe_set19_3-1.png")                  # builds tftcap if needed
model = ROOT / "data/models/items.mlmodel"
cmd = [str(TOOL), "units", str(ROOT / "tests/fixtures/pbe_set19_3-1.png")] + (["--model", str(model)] if model.exists() else [])
units = [json.loads(x) for x in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.splitlines()]
assert len(units) == 10, len(units)
assert all(0.03 <= u["w"] <= 0.035 for u in units)              # one bar width at this UI scale
if model.exists():
    assert units[0]["items"][0][0] == "Choreographer Emblem", units[0]["items"]
print("ok" + ("" if model.exists() else " (bars only: no item model)"))
