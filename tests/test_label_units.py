# Unit-label review: look-alike grouping and the round check against the game's trait panel.
#   python3 -I tests/test_label_units.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "capture"), str(ROOT / "engine")]
import label_units as L  # noqa: E402
from unlocks import load_set  # noqa: E402

# grouping: crops within the measured same-unit distance join; far ones don't
vec = {"a": [0.0, 0.0], "b": [0.3, 0.0], "c": [2.0, 0.0]}
assert L.group(["a", "b", "c"], vec) == [["a", "b"], ["c"]]

# round check: a fully labelled board that reproduces the panel passes; an emblem adds its trait; a wrong
# label shows up as a trait that doesn't add up
S = load_set("TFTSet19")
U = {u["name"]: u["traits"] for u in S["units"]}
board = ["Zac", "Taric", "Zoe"]                       # Zac & Taric: Beach Pop + Juggernaut; Zoe: Beach Pop + Arcanist
panel = {}
for n in board:
    for tr in U[n]:
        panel[tr] = panel.get(tr, 0) + 1
panel["Choreographer"] = 1                            # from a Choreographer Emblem on Zac
m = {"crops": {f"r/{i}": {"id": f"r/{i}", "round": "r", "bench": False, "items": ["Choreographer Emblem"] if n == "Zac" else []}
               for i, n in enumerate(board)},
     "rounds": {"r": {"stage": "3-2", "t": 1, "level": 3, "panel": panel, "units": []}}}
ok = L.check(m, {f"r/{i}": n for i, n in enumerate(board)}, S)[0]
assert ok["labelled"] == 3 and ok["over"] == {} and ok["short"] == {}, ok   # the emblem fills Choreographer
bad = L.check(m, {"r/0": "Zac", "r/1": "Taric", "r/2": "Ziggs"}, S)[0]
assert bad["short"] and not bad["over"], bad          # Ziggs instead of Zoe: Beach Pop falls short (soft)
over = L.check(m, {"r/0": "Zac", "r/1": "Taric", "r/2": "Renekton"}, S)[0]
assert "Beach Pop" not in over["over"] and over["short"].get("Arcanist"), over
m["rounds"]["r"]["panel"]["Beach Pop"] = 2            # units alone exceed the panel: a hard contradiction
assert L.check(m, {f"r/{i}": n for i, n in enumerate(board)}, S)[0]["over"] == {"Beach Pop": [3, 2]}
partial = L.check(m, {"r/0": "Zac"}, S)[0]
assert "diffs" not in partial and partial["labelled"] == 1
print("ok")
