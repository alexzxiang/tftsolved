# Advisor: buy scoring, scouted boards and contest, line ranking by shop reach, items from held components.
#   python3 -I tests/test_advise.py
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "capture")]
import advise as A  # noqa: E402
from record import scouted_boards  # noqa: E402
from review import recipes  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
U = {u["name"]: u for u in S["units"]}
plans = A.build_plans(S)


def outside(p, want):
    return [n for n, u in U.items() if not u.get("unlockable") and n not in p["core"] + p.get("flex", [])
            and (p["trait"] in u["traits"]) == want and u["cost"] <= 3]


if not any("avg_place" in p for p in plans):                      # MetaTFT comps: kept private
    print("skip: needs MetaTFT PBE data")
    sys.exit()
plan = next(p for p in plans if "avg_place" in p and outside(p, True))   # a comp whose trait has outside units
core, trait = plan["core"], plan["trait"]
fits, other = outside(plan, True)[0], outside(plan, False)[0]

# buys: copies you hold and the line's core first; units fitting an active trait next; nothing late and off-trait
state = {"stage": "3-2", "shop_seen": [core[0], other, fits, core[1]], "traits": [{"name": trait, "count": 2, "active": True}],
         "owned": [{"unit": core[1], "copies": 2, "stars": 1}]}
scored = {u: s for u, s, _ in A.buys(S, state, [], plan, Counter())}
assert scored[core[1]] > scored[core[0]] >= A.BUY_AT > scored[fits] > scored[other], scored
assert scored[fits] > 0 == scored[other]
late = {u: s for u, s, _ in A.buys(S, dict(state, stage="5-1"), [], plan, Counter())}
assert late[other] < 0, late
# a unit on a scouted board is worth less to chase
contested = {u: s for u, s, _ in A.buys(S, state, [], plan, Counter({core[0]: 2}))}
assert contested[core[0]] < scored[core[0]]

# scouted panels: grouped per board, read twice or more, ours left out
mine = [{"name": "Beach Pop", "count": 7, "active": True}, {"name": "Arcanist", "count": 2, "active": True}]
kda = [{"name": "K/DA", "count": 13, "active": True}, {"name": "Choreographer", "count": 2, "active": True}]
got = scouted_boards([kda, kda, kda[:1], mine, mine, [{"name": "Jazz", "count": 1, "active": False}]], mine)
assert len(got) == 1 and got[0][0]["name"] == "K/DA" and got[0][0]["count"] == 13, got
states = [{"stage": "4-5", "level": 8, "scouted": [kda]}, {"stage": "4-6", "level": 8, "scouted": [kda]}]
lobby = A.lobby_boards(S, states, 1)
assert len(lobby) == 1 and lobby[0][0] == "4-6" and lobby[0][2], lobby      # one board, its units inferred

# lines: the reach of a comp falls when its units sit on other boards
st = {"stage": "3-2", "level": 6, "xp": [0, 36], "gold": 40, "hp": 80, "unlocked": [],
      "traits": [{"name": plan["trait"], "count": 2, "active": True}],
      "owned": [{"unit": u, "copies": 1, "stars": 1} for u in core[:3]]}
free = {p["id"]: rp for p, _, rp, _, _ in A.lines(S, st, plans, Counter(), k=10)}
taken = {p["id"]: (rp, share) for p, _, rp, share, _ in A.lines(S, st, plans, Counter({u: 2 for u in core[3:]}), k=10)}
if plan["id"] in free and plan["id"] in taken:
    assert taken[plan["id"]][0] < free[plan["id"]] and taken[plan["id"]][1] > 0, (free, taken)

# items: held components that make an item (CommunityDragon data present)
comps, build = recipes()
if build:
    (a, b), it = next((tuple(k), v) for k, v in build.items() if len(k) == 2)
    assert A.items({"items_held": [a, b, "Reforger"]}, plan, {})[0][:1] == (it,)

# artifacts (MetaTFT best holders): a choice ranks by the best holder among the line's units, and an artifact
# you hold lowers the expected place of lines whose units use it well
arts = {"Lich Bane": {"change": -0.68, "holders": {core[0]: -1.2, "Nobody": -0.3}},
        "Fishbones": {"change": 0.05, "holders": {"Nobody": -0.3}}}
ranked = A.item_choice({"item_offer": ["Fishbones", "Lich Bane"]}, plan, arts)
assert ranked[0][0] == "Lich Bane" and ranked[0][1] == 1.0 and core[0] in ranked[0][2], ranked   # capped at 1 place
assert A.artifact_gain(arts["Fishbones"], A.line_units(plan)) == (0.0, None)
with_art = {p["id"]: pl for p, _, _, _, pl in A.lines(S, dict(st, items_held=["Lich Bane"]), plans, Counter(), k=10, arts=arts)}
without = {p["id"]: pl for p, _, _, _, pl in A.lines(S, st, plans, Counter(), k=10, arts=arts)}
if plan["id"] in with_art and plan["id"] in without:
    assert with_art[plan["id"]] < without[plan["id"]]
print("ok")
