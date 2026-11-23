# End to end on the real Set 19 PBE frame: OCR -> HUD -> recorder -> unlock checker -> review.
#   python3 -I tests/test_pipeline.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "tests/fixtures/pbe_set19_3-1.png").exists():      # a PBE game screenshot: kept private (player names)
    print("skip: needs tests/fixtures/pbe_set19_3-1.png (a private game screenshot)")
    sys.exit()
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine")]
from hud import counter_targets, ocr, read  # noqa: E402
from record import Recorder  # noqa: E402
from review import review  # noqa: E402
from unlocks import evaluate, load_set  # noqa: E402

S = load_set("TFTSet19")
rows = ocr(ROOT / "tests/fixtures/pbe_set19_3-1.png")
h = read(rows, [u["name"] for u in S["units"]], [t["name"] for t in S["traits"]], targets=counter_targets(S["unlocks"]))

rec = Recorder({u["name"]: u["cost"] for u in S["units"]}, {u["unit"] for u in S["unlocks"]})
second = dict(h, gold=43, shop=[s for s in h["shop"] if s["slot"] != 1])          # bought Kayn (slot 1, 1 gold)
third = dict(h, t="3-2", gold=48, hp=76, shop=h["shop"])                           # next round, lost 7 HP
states = [s for s in (rec.feed(dict(r), i) for i, r in enumerate([h, second, third])) if s] + [rec.close()]

s31 = states[0]
assert s31["stage"] == "3-1" and s31["owned"] == [{"unit": "Kayn", "copies": 1, "stars": 1}], s31["owned"]
assert s31["gold_end_combat"] == 43 and s31["unlocked"] == []
status = {r["unit"]: r for r in evaluate(S, s31)}
assert status["Zac"]["status"] == "PROGRESS" and status["Zac"]["value"] == 2       # Beach Pop 2 on the panel
assert status["Smeech"]["value"] == 4                                               # Collab, Ionic, Choreo, Frontman
assert status["Seraphine"]["status"] == "UNKNOWN"     # joined at 3-1: earlier rerolls unseen, so not "dead"
assert states[1]["result"] == "loss" and states[1]["streak"]["type"] == "loss"
notes = review(S, states)
assert isinstance(notes, list)
print(*notes, sep="\n")
print("ok")
