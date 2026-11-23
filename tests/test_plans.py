# Structural Set 19 plans: well-formed, matched to boards, reach honest about unknowns, used by review.
#   python3 -I tests/test_plans.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from plans import build_plans, match, plan_reach, targets  # noqa: E402
from review import review  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
UNITS = {u["name"] for u in S["units"]}
GATES = {u["unit"]: u.get("min_level") or 0 for u in S["unlocks"]}
plans = {p["id"]: p for p in build_plans(S)}

structural = [p for p in plans.values() if p["source"] == "structural"]
assert len(structural) == 12 and "Pentakill-7" in plans and "Gu Feng-4" in plans, sorted(plans)
assert len(plans) == len(build_plans(S)), "plan ids must be unique"
for p in plans.values():
    assert set(p["core"]) <= UNITS and set(p["unlocks"]) <= set(GATES), p["id"]
    assert not {"Akali (K/DA)", "Akali (True Damage)"} <= set(p["core"]), p["id"]       # exclusive unlocks
    assert p["level"] >= max([GATES.get(u, 0) for u in p["unlocks"]] + [0]), p["id"]
    assert len(p["core"]) <= p["level"], p["id"]
assert plans["Jazz-4"]["level"] == 9                                                    # Smeech's gate
assert set(plans["Pentakill-7"]["unlocks"]) == {"Kayle", "Mordekaiser"}

# A Pentakill board is matched to the Pentakill plan, whose unlocks become the targets
penta = {"stage": "4-1", "level": 7, "gold": 40, "hp": 70,
         "owned": [{"unit": u, "copies": 3, "stars": 2} for u in ("Gnar", "Olaf", "Karthus", "Viego")],
         "traits": [{"name": "Pentakill", "count": 4, "active": True}]}
best, fit = match(S, penta, list(plans.values()))[0]
assert "Pentakill" in best["id"] and fit >= 0.5, (best["id"], fit)     # structural or PBE Pentakill plan
assert {"Kayle", "Mordekaiser"} <= set(targets(S, penta))

# Reach: core units plus unlocks; unknown unlock chances make it an upper bound, never a silent 100%
r = plan_reach(S, penta, plans["Pentakill-7"], "5-1")
assert set(r["missing_units"]) == {"Yorick"} and not r["upper_bound"]
assert 0 <= r["p"]["standard"] <= 1
hyper = plan_reach(S, {"stage": "3-1", "level": 5, "gold": 30}, plans["Hyperpop-5"], "5-1")
assert hyper["upper_bound"] and "Teemo" in hyper["unknown"]                              # Hype not read

# Review names the plan at the checkpoint and what blocks its unlocks
log = [dict(penta, stage="3-2", level=6, traits=[{"name": "Pentakill", "count": 3, "active": True}]), penta]
notes = [m for st, k, m in review(S, log) if k == "PLAN"]
# (an opener can lead to several lines: MetaTFT's Rock Vayne players open Olaf/Karthus/Swain too)
penta_notes = [n for n in notes if "Pentakill" in n and "Mordekaiser" in n]
assert penta_notes, notes
assert any("star levels of Pentakill" in n for n in penta_notes), notes   # fielded Pentakill units, owned at 2 stars
print(*notes, sep="\n")
# With MetaTFT PBE averages saved (private file), real comps join as plans with placement data
pbe = [p for p in plans.values() if p["source"].startswith("MetaTFT")]
if pbe:
    assert all(len(p["core"]) <= 6 and p["avg_place"] > 0 for p in pbe)
    from plans import expected_place, unlock_payoff
    pay = unlock_payoff(S)
    assert pay["Kobuko"][0] < pay["Yasuo"][0]                                  # Hyperpop chain beats Yasuo on PBE
    sure = {"p": {"standard": 1.0, "roll_now": 1.0}}
    assert expected_place(pbe[0], sure) == pbe[0]["avg_place"]
    assert expected_place(plans["Pentakill-7"], sure) is None                 # no placement data, no number
    # early boards: holding a comp's level-5 board fits that comp at level 5, not at level 9
    k = next(p for p in pbe if (p.get("early") or {}).get(5) and not set(p["early"][5]) & set(p["core"][:2]))   # an opener unlike its end
    st = {"stage": "3-1", "level": 5, "traits": [{"name": "X", "count": 1, "active": False}],
          "owned": [{"unit": u, "copies": 1, "stars": 1} for u in k["early"][5]]}
    early_fit = dict((q["id"], f) for q, f in match(S, st, pbe))[k["id"]]
    late_fit = dict((q["id"], f) for q, f in match(S, dict(st, level=9), pbe))[k["id"]]
    assert early_fit == 1.0 and late_fit < 1.0, (k["id"], early_fit, late_fit)
    assert k["carries"] and all(c in k["items"] for c in k["carries"])       # carries: the units with items listed
print("ok")
