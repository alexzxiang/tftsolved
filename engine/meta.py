"""MetaTFT Set 19 PBE data (private, gitignored files read from the public pages), joined onto the roster.

    units(set)      {unit: {role, damage, kind, cost, traits, items: {item: place change}, item_play, builds, stars}}
    traits(set)     {(trait, count): avg place of final boards with that trait level}
    artifacts(set)  {artifact: {change, holders: {unit: place change}}}
    augments(set)   {augment: {tier, category, also, summary, expert, types}}: our catalog + MetaTFT's expert tiers
    variants(set)   {comp: {level: [(units, avg place)]}}: the comp's boards by final level, +1 units included

Place changes are MetaTFT's estimates (negative = better); all are final-board stats, so survivorship-biased:
read them as "what strong boards carry", not as causal effects. Empty dicts when a file is missing.
"""
import functools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "data" / "manual"
MIN_HOLDER_PLAY = 0.001        # artifact holders under 0.1% of a unit's games are noise
API_NAMES = {"AkaliKDA19": "Akali (K/DA)", "Akali_TrueDamage19": "Akali (True Damage)"}


def _load(set_name, kind):
    f = MANUAL / f"{set_name}.metatft_{kind}.json"
    return json.loads(f.read_text()) if f.exists() else None


@functools.lru_cache(maxsize=None)
def units(set_name="TFTSet19"):
    d = _load(set_name, "units")
    out = {}
    for u in (d or {}).get("units", []):
        name = API_NAMES.get(u["api"], u["name"])
        damage, _, kind = u["role"].partition(" ")
        # MetaTFT lists a doubled item as "2nd Gargoyle Stoneplate": the same item, so it isn't a separate best-in-slot
        names = {t["item"] for t in u["top_items"]}
        top = [dict(t, item=t["item"][4:]) if t["item"].startswith("2nd ") else t for t in u["top_items"]
               if not (t["item"].startswith("2nd ") and t["item"][4:] in names)]
        items = {t["item"]: t["place_change"] for t in top}
        out[name] = {"role": u["role"], "damage": damage, "kind": kind, "cost": u["cost"], "traits": u["traits"],
                     "items": items, "item_play": {t["item"]: t["play_rate"] for t in top}, "builds": u["builds"], "stars": {s["stars"]: s for s in u["stars"]},
                     "items_count": u["items_count"]}
    return out


@functools.lru_cache(maxsize=None)
def traits(set_name="TFTSet19"):
    d = _load(set_name, "traits")
    return {(x["trait"], x["count"]): x["avg_place"] for x in (d or {}).get("levels", [])}


@functools.lru_cache(maxsize=None)
def trait_games(set_name="TFTSet19"):
    d = _load(set_name, "traits")
    return {(x["trait"], x["count"]): x.get("games", 0) for x in (d or {}).get("levels", [])}


@functools.lru_cache(maxsize=None)
def artifacts(set_name="TFTSet19"):
    d = _load(set_name, "artifacts")
    return {a["name"]: {"change": a["place_change"], "holders": {h["unit"]: h["place_change"] for h in a["holders"]
                                                                 if h["play_rate"] >= MIN_HOLDER_PLAY}}
            for a in (d or {}).get("artifacts", [])}


@functools.lru_cache(maxsize=None)
def augments(set_name="TFTSet19"):
    cat = json.loads((MANUAL / "augments.json").read_text()).get(set_name, []) if (MANUAL / "augments.json").exists() else []
    out = {a["name"]: dict(a) for a in cat}
    for a in (_load(set_name, "augments") or {}).get("augments", []):
        out.setdefault(a["name"], {"name": a["name"], "tier": None, "category": None, "also": [], "summary": ""})
        out[a["name"]].update(expert=a["tier"], types=a["types"])
    return out


def _unit_name(n, comp=""):
    n = n.split(" (")[0] if "(" in n and not n.startswith("Akali") else n       # "Seraphine (SeraphineSuperstar19)"
    if n == "Akali":
        return "Akali (True Damage)" if "True Damage" in comp else "Akali (K/DA)"
    return {"Nunu": "Nunu & Willump"}.get(n, n)


@functools.lru_cache(maxsize=None)
def details(set_name="TFTSet19"):
    """{comp: {levels {L: [(units, avg)]}, level_share {L: share}, positions [(unit, hex 0-27; row x 7 + col, row 0
    = front)], levelling [(level, stage, rerolls spent there)], carousel [(component, priority)], units [(unit, avg
    place in comp, play rate)], items [(item, avg place in comp, play rate)], placements [8 shares], players_per_game}}
    from MetaTFT's comp panels (private file)."""
    d = _load(set_name, "details") or {}
    items = {i.lower(): i for i in _item_names()}
    out = {}
    for c, x in d.get("comps", {}).items():
        fix = lambda u: _unit_name(u, c)                                      # noqa: E731
        out[c] = dict(x, levels={int(k): [([fix(u) for u in us], a) for us, a in v] for k, v in (x.get("levels") or {}).items()},
                      positions=[(fix(u), h) for u, h in x.get("positions") or []],
                      units=[(fix(u), a, p) for u, a, p in x.get("units") or []],
                      items=[(items.get(i.lower(), i), a, p) for i, a, p in x.get("items") or []],
                      carousel=[(items.get(i.lower(), i), n) for i, n in x.get("carousel") or []])
    return out


def _item_names():
    try:
        from review import recipes
        comps, build = recipes()
        return set(comps) | set(build.values())
    except Exception:                                   # noqa: BLE001 (CommunityDragon cache missing)
        return set()


@functools.lru_cache(maxsize=None)
def variants(set_name="TFTSet19"):
    d = _load(set_name, "variants")
    return {c: {int(lv): [(us, avg) for us, avg in boards] for lv, boards in by.items()}
            for c, by in (d or {}).get("comps", {}).items()}


if __name__ == "__main__":
    import sys
    s = sys.argv[1] if len(sys.argv) > 1 else "TFTSet19"
    print(f"units {len(units(s))}, trait levels {len(traits(s))}, artifacts {len(artifacts(s))}, "
          f"augments {len(augments(s))} ({sum('expert' in a for a in augments(s).values())} expert-rated), "
          f"comps with level variants {len(variants(s))}, comp details {len(details(s))}")
