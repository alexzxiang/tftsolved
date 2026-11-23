#!/usr/bin/env python3
"""Build one static-data file per set: roster with pool sizes, traits, shop odds, rules, unlocks.

    python3 -I tools/build_static.py --set TFTSet18           # -> data/pbe/TFTSet18.json
    python3 -I tools/build_static.py --set TFTSet19 --refresh # once Set 19 is on PBE

Generated from CommunityDragon game files; rules the files don't hold come from data/constants.json.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I drops the script dir from the path
from extract_unlocks import ROOT, SET_PREFIX, extract, fetch, load, unlock_container

ODDS_KEY = "{bcf1e6a6}"   # hashed field: per-cost odds inside each TftDropRates entry


def build(bins, strings, cdragon, set_name):
    setobj = bins.get(SET_PREFIX + set_name) or sys.exit(f"{set_name} not in game data")
    cd = next((s for s in cdragon["setData"] if s["mutator"] == set_name), None) or sys.exit(
        f"{set_name} not in CommunityDragon's en_us.json")
    champs = {c["apiName"]: c for c in cd["champions"]}
    unlocks = extract(bins, strings, cdragon, set_name) if unlock_container(bins, set_name) else []
    locked = {u["api"] for u in unlocks}

    units = []
    for tier, bag in enumerate(bins[setobj["ShopContentData"]]["TierBags"], start=1):
        for e in bag.get("TierBagEntries", []):
            api = e["ShopData"].split("/")[-1]
            c = champs.get(api, {})
            units.append({"api": api, "name": c.get("name", api), "cost": c.get("cost", tier),
                          "traits": c.get("traits", []), "pool": e["Count"], "unlockable": api in locked})

    odds = [[round(x, 4) for x in lv[ODDS_KEY]]
            for lv in bins[setobj["DropRateTables"]["Shop"]]["mDropRatesByLevel"]]
    traits = [{"api": t["apiName"], "name": t["name"],
               "breakpoints": [e["minUnits"] for e in t.get("effects", []) if e.get("minUnits")]}
              for t in cd["traits"]]
    rules = json.loads((ROOT / "data/constants.json").read_text()).get(set_name)
    if rules is None:
        print(f"warning: no rules for {set_name} in data/constants.json; copy the previous set's and "
              "check them against the patch notes", file=sys.stderr)
    return {"set": set_name, "shop_odds_by_level": odds, "units": units, "traits": traits,
            "rules": rules, "unlocks": unlocks}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", default="pbe")
    ap.add_argument("--set", required=True, help="e.g. TFTSet18")
    ap.add_argument("--refresh", action="store_true", help="re-download raw files")
    a = ap.parse_args()
    data = build(*load(fetch(a.patch, a.refresh)), a.set)
    dest = ROOT / "data" / a.patch / f"{a.set}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    by_cost = {}
    for u in data["units"]:
        by_cost.setdefault(u["cost"], []).append(u)
    for cost, us in sorted(by_cost.items()):
        print(f"cost {cost}: {len(us)} units ({sum(u['unlockable'] for u in us)} unlockable), "
              f"pool {sorted({u['pool'] for u in us})}")
    for lv, o in enumerate(data["shop_odds_by_level"], start=1):
        print(f"level {lv:>2} odds {o}")
    print(f"{len(data['traits'])} traits, {len(data['unlocks'])} unlocks -> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
