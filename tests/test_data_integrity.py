"""Every name in the Set 19 data resolves: units, traits, items, comps, openers, artifact holders, augments,
conditions, unlocks. A typo or a renamed unit in a scraped file would otherwise drop silently out of the line finder.

    python3 -I tests/test_data_integrity.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import linefinder as L  # noqa: E402
import meta  # noqa: E402
from plans import pbe_comps, pbe_plans  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
comps = pbe_comps(S)
if not comps:
    print("skip: needs MetaTFT PBE data")
    sys.exit()
bad = []
units = {u["name"]: u for u in S["units"]}
traits = {t["name"]: t for t in S["traits"]}
cat = L.catalog(S)
items = set(cat["completed"]) | set(cat["artifacts"]) | set(cat["radiants"]) | set(cat["emblems"]) | set(cat["components"])
# items a trait or the game hands out, which no recipe builds: listed in comp builds, never held as input
TRAIT_ITEMS = {"Bard's Horn of the Traveler", "Scroll of Heavenly Prayer", "Scroll of The Beast", "Tacticians Crown"}
assert not any(L.buildable(i) for i in TRAIT_ITEMS)


def need(ok, what):
    if not ok:
        bad.append(what)


# roster and traits
for u in S["units"]:
    need(u["cost"] in (1, 2, 3, 4, 5, 7), f"unit cost {u['name']} {u['cost']}")
    for t in u["traits"]:
        need(t in traits, f"unit {u['name']} trait {t}")
for t in S["traits"]:
    bp = t.get("breakpoints") or []
    need(bp == sorted(bp) and len(set(bp)) == len(bp), f"trait {t['name']} breakpoints {bp}")
    need(t.get("counts", "units") in ("units", "stars"), f"trait {t['name']} counts {t.get('counts')}")
    need(any(t["name"] in u["traits"] for u in S["units"]), f"trait {t['name']} has no units")
for lk in S["unlocks"]:
    need(lk["unit"] in units, f"unlock for unknown unit {lk['unit']}")
    for k, v in lk["when"].items():
        for x in (v.get("units") or []) if isinstance(v, dict) else []:
            need(x in units, f"unlock {lk['unit']} names unknown unit {x}")
        for x in (v.get("traits") or []) if isinstance(v, dict) else []:
            need(x in traits, f"unlock {lk['unit']} names unknown trait {x}")
# comps: units, boards, items, stars, openers, places
names = [c["name"] for c in comps]
need(len(names) == len(set(names)), "duplicate comp names")
for c in comps:
    n = c["name"]
    for x in c["units"]:
        need(x in units, f"{n}: unit {x}")
    need(len(c["units"]) == len(set(c["units"])), f"{n}: duplicate units")
    need(7 <= len(c["units"]) <= 10, f"{n}: {len(c['units'])} units")
    need(1 <= c["avg_place"] <= 8 and 0 <= (c.get("pick_rate") or 0), f"{n}: place {c['avg_place']} pick {c.get('pick_rate')}")
    for b in c.get("board") or []:
        need(b["unit"] in units and b.get("stars", 1) in (1, 2, 3), f"{n}: board {b['unit']} {b.get('stars')}")
        for i in b.get("items") or []:
            need(i in items | TRAIT_ITEMS, f"{n}: item {i} on {b['unit']}")     # trait items (Scrolls) aren't held
    for e in c.get("early") or []:
        for x in e["units"]:
            need(x in units, f"{n}: opener unit {x}")
        # MetaTFT openers can run a unit or two over the level (team-size items and augments)
        need(len(e["units"]) <= e["level"] + 2, f"{n}: level-{e['level']} opener has {len(e['units'])} units")
    share = c.get("final_level_share") or {}           # levels 7-10 only: the rest end lower
    need(all(0 <= v <= 1 for v in share.values()) and sum(share.values()) <= 1.02, f"{n}: final level shares {share}")
# plans: carries and item holders are comp units, items exist
plans = {p["id"][4:]: p for p in pbe_plans(S)}
for c in comps:
    p = plans.get(c["name"])
    need(p is not None, f"{c['name']}: no plan")
    if not p:
        continue
    for h, its in p["items"].items():
        need(h in units, f"{c['name']}: item holder {h}")
        for i in its:
            need(i in items | TRAIT_ITEMS, f"{c['name']}: plan item {i}")
    need(bool(p["carries"]), f"{c['name']}: no carries")
    need(L.main_carry_first(c["name"], p["carries"])[0] in c["units"], f"{c['name']}: main carry not on the board")
# MetaTFT unit pages, artifacts, details
mu = meta.units(S["set"])
for u in units:
    need(u in mu, f"no MetaTFT unit page for {u}")
for u, d in mu.items():
    for i in list(d.get("items") or {}) + list(d.get("item_play") or {}):
        need(i in items | TRAIT_ITEMS, f"MetaTFT unit {u}: item {i}")
for a, d in meta.artifacts(S["set"]).items():
    need(a in cat["artifacts"], f"artifact {a} not in the catalog")
    for h in d["holders"]:
        need(h in units, f"artifact {a}: holder {h}")
for n, d in meta.details(S["set"]).items():          # (a panel for a comp MetaTFT has since dropped is unused)
    for x, _, _ in d.get("units") or []:
        need(x in units, f"details {n}: unit {x}")
    for i, _, _ in d.get("items") or []:
        need(i in items | TRAIT_ITEMS, f"details {n}: item {i}")
# conditions and augments
for cd in L.conditions(S["set"]):
    c = cd["if"]
    for x in [c.get("unit"), c.get("requires")] + list(c.get("units_any") or []):
        need(x is None or x in units, f"condition {cd.get('why', '')[:40]}: unit {x}")
    need(c.get("trait_units") is None or c["trait_units"] in traits, f"condition trait {c.get('trait_units')}")
    need(c.get("item") is None or c["item"] in items or f"Radiant {c['item']}" in items, f"condition item {c.get('item')}")
    need(c.get("emblem") is None or c["emblem"] in cat["emblems"], f"condition emblem {c.get('emblem')}")
    for n in cd.get("comps") or []:
        need(n in names, f"condition names unknown comp {n}")
augs = {a["name"] for a in cat["augments"]}
need(len(augs) > 100, f"only {len(augs)} augments")
print("\n".join(bad[:60]) or "data ok")
assert not bad, f"{len(bad)} problems"
