# Learned board model (synthetic lobbies, no data needed) and the player's focus list.
#   python3 -I tests/test_board_model.py
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import board_model as bm  # noqa: E402
import plans  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")

# features: unit-star, cumulative trait tiers, items and best-in-slot per unit
f = bm.features(S, [("Gnar", 1, []), ("Olaf", 2, ["A", "B"]), ("Karthus", 1, [])], {"Olaf": {"A"}})
assert f["u:Olaf*2"] == 1 and f["t:Pentakill:1"] == 1 and "t:Pentakill:2" not in f
assert abs(f["it:Olaf"] - 2 / 3) < 1e-9 and abs(f["bis:Olaf"] - 1 / 3) < 1e-9

# BIS comes from top-4 boards only
lob = [(1, 30, [("Olaf", 2, ["A", "B"])])] * 3 + [(8, 20, [("Olaf", 1, ["Z"])])] * 3
assert bm.bis_table([lob] * 2)["Olaf"] == {"A", "B"}

# training ranks a clearly stronger unit above a weaker one at equal cost
lobbies = []
for i in range(40):
    strong = [("Ahri", 1, []), ("Gnar", 1, [])]
    weak = [("Lillia", 1, []), ("Gnar", 1, [])]
    lobbies.append([(1, 30, strong), (2, 30, strong), (7, 20, weak), (8, 20, weak)])
w = bm.train(bm.rank_lobbies(lobbies, S, {}), epochs=5)
model = {"weights": w, "bis": {}}
assert bm.score(model, S, [("Ahri", 1, [])]) > bm.score(model, S, [("Lillia", 1, [])])
# held-out accuracy: the model ranks these lobbies right, and the 1st/2nd pair counts as same-round
acc = bm.accuracy(w, S, lobbies[:2], {})
assert acc["all"][0] > 0.6 and acc["same_round"][1] == 4          # 2 lobbies x (1st,2nd) + (7th,8th)

# priors: an older model of the same set carries its weights; another set's carries kinds of weight only
old = {"set": "TFTSet19", "weights": {"u:Ahri*1": 0.7, "gold": 0.2}, "kinds": {"u:cost4*1": 0.3, "t:step1": 0.1}}
cost = {u["name"]: min(u["cost"], 5) for u in S["units"]}
same = bm.prior_for(old, S, {"u:Ahri*1", "gold", "t:Pentakill:1"})
assert same == {"u:Ahri*1": 0.7, "gold": 0.2, "t:Pentakill:1": 0.1}
other = bm.prior_for(dict(old, set="TFTSet18"), S, {"u:Ahri*1", "gold"})
assert other["gold"] == 0.2 and other["u:Ahri*1"] == old["kinds"].get(f"u:cost{cost['Ahri']}*1", 0.0)
assert bm.kind(S, "t:Pentakill:3") == "t:step3" and bm.kind(S, "bis:Olaf") == "bis"
# a prior is the starting point: a lobby that agrees with it only pushes further the same way
w = bm.train(bm.rank_lobbies(lobbies[:1], S, {}), prior={"u:Ahri*1": 0.7, "u:Gnar*1": 0.0, "u:Lillia*1": -0.2,
                                                          "units": 0, "gold": 0, "carry": 0, "it:Ahri": 0,
                                                          "it:Gnar": 0, "it:Lillia": 0, "bis:Ahri": 0,
                                                          "bis:Gnar": 0, "bis:Lillia": 0}, epochs=1)
assert w["u:Ahri*1"] >= 0.7 and w["u:Lillia*1"] <= -0.2           # this lobby only agrees with the prior

# focus list: chosen comps drive targets; unknown ids are refused
plans.FOCUS = Path(tempfile.mkdtemp()) / "focus.json"
assert plans.focus(S) == []
some = [p for p in plans.build_plans(S) if p["unlocks"]][:2]
plans.set_focus(S, [p["id"] for p in some])
assert [p["id"] for p in plans.focus(S)] == [p["id"] for p in some]
assert plans.targets(S, {}) == sorted({u for p in some for u in p["unlocks"]})
try:
    plans.set_focus(S, ["no such plan"])
    raise AssertionError("unknown plan accepted")
except SystemExit:
    pass
assert json.loads(plans.FOCUS.read_text())["TFTSet19"] == [p["id"] for p in some]
# Riot unit ids resolve onto the hand-made Set 19 roster (launch-day data path)
from unlocks import unit_resolver  # noqa: E402
r = unit_resolver(S)
assert [r(x) for x in ("TFT19_NunuWillump", "TFT19_AkaliKDA", "TFT19_KSante", "TFT19_Kaisa", "TFT19_Summon")] == \
    ["Nunu & Willump", "Akali (K/DA)", "K'Sante", "Kai'Sa", None]
assert r(S["units"][0]["api"]) == S["units"][0]["name"]
print("ok")
