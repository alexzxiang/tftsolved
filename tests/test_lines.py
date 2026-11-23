# Line selection: focused lines pull their units onto the board; low HP favours strength now; counter gates
# count; pivots aren't same-trait variants. Uses structural plans, so no private data is needed.
#   python3 -I tests/test_lines.py
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import plans  # noqa: E402
from lines import best_board, pivots  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
plans.FOCUS = Path(tempfile.mkdtemp()) / "focus.json"
P = {p["id"]: p for p in plans.build_plans(S)}


def owned(*units):
    return [{"unit": u, "copies": 3 if s == 2 else 1, "stars": s} for u, s in units]


state = {"stage": "3-2", "level": 6, "gold": 30, "hp": 90,
         "owned": owned(("Ziggs", 2), ("Kobuko", 1), ("Lulu", 1), ("Lux", 2), ("Annie", 2), ("Elise", 2),
                        ("Gragas", 2), ("Taric", 2), ("Olaf", 1), ("Tristana", 1))}

# Focus on the Hyperpop band: its units (Ziggs, Kobuko, Lulu, Tristana) make the board, at some cost now
plans.set_focus(S, ["Hyperpop-5"])
r = best_board(S, state)
names = {u for u, _, _ in r["board"]}
assert {"Ziggs", "Kobuko", "Lulu", "Tristana"} <= names, names
assert r["keep"] >= r["alt"]["keep"] and r["strength"] <= r["alt"]["strength"] + 1e-9
assert r["why"].startswith("field ") or r["why"] == "the strongest board already keeps your line"

# At 10 HP the present dominates: the line board gives up less strength than at 90 HP
low = best_board(S, dict(state, hp=10))
assert (low["alt"]["strength"] - low["strength"]) <= (r["alt"]["strength"] - r["strength"]) + 1e-9

# Gu Feng focus: Xayah keeps three counters running, so she is fielded
plans.set_focus(S, ["Gu Feng-4"])
gu = best_board(S, dict(state, owned=state["owned"] + owned(("Xayah", 1))))
assert "Xayah" in {u for u, _, _ in gu["board"]}, gu["board"]

# Pivots never point at a same-trait variant
for n, q, shared, unl in pivots(S, P["Hyperpop-5"], list(P.values())):
    assert q["trait"] != "Hyperpop" and (shared or unl)
print("ok")
