"""Line finder: a static filter over Set 19 comp data, like tftflow, searched by what you hold.

You type in units (with stars), items (components, completed, artifacts, radiants, emblems) and augments;
every meta comp gets
  - a tier from its average place, moved by those conditions (BIS items, artifacts on their best holders,
    radiants, emblems that add a breakpoint, augments that suit the comp's archetype, trait or units),
  - how much of what you hold it uses (fit), and how much of its opener you already have,
  - its openers (levels 4-7, MetaTFT round win rates), a midgame board, +1 units, unlocks and conditions,
    the endgame board with best-in-slot items, and artifact holders.
Manual input only, nothing read from a running game, nothing computed from gold, level or HP: a pre-game /
between-games reference like tftflow, not live advice (docs/POLICY.md).

    python3 -I engine/linefinder.py Ziggs:2 Lulu "Swain" --items "Needlessly Large Rod,Spear of Shojin" --augments "Hyperpop Crown"
"""
import functools
from collections import Counter
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import augments as A  # noqa: E402
import augvalue  # noqa: E402
import meta  # noqa: E402
from unlocks import Board, check, load_set  # noqa: E402
import power  # noqa: E402
from plans import pbe_comps, pbe_plans  # noqa: E402
from review import recipes  # noqa: E402
from strength import trait_tiers  # noqa: E402

BIS_PER_UNIT = 3        # best-in-slot = a unit's 3 most played items (the definition tools/calibrate.py items measured)
COMPONENT_SHARE = 0.5   # a component is half of a completed item (it takes two)
ODDS_FLOOR = 0.03       # line odds: likelihood of a unit a comp never plays (naive-Bayes smoothing; sorting only)
SUGGESTIONS = 4         # how many suggested lines the page shows (display)
SUGGESTIONS_MIN = 3     # with units held, at least this many (the next likeliest lines fill a tight realistic set)
VARIANT_OVERLAP = 0.8  # comps sharing this share of units are one family on the suggestion strip (display)
INVESTED_COST = 5       # a 2-star of this cost or more is a board's carry even without items (realistic set only)
ODDS_OPENER = 0.9       # line odds: likelihood of a unit on the comp's MetaTFT opener boards (sorting only)
TIERS_PRIOR = [("OP", 3.5), ("S+", 3.8), ("S", 4.1), ("A", 4.4), ("B", 4.7), ("C", 99)]
ARTIFACT_BASE = None    # filled lazily: the mean holder change (MetaTFT holder changes run negative)
COMPONENT_KIND = {"B.F. Sword": "AD", "Recurve Bow": "AD", "Sparring Gloves": "AD", "Needlessly Large Rod": "AP",
                  "Tear of the Goddess": "AP", "Chain Vest": "tank", "Negatron Cloak": "tank", "Giant's Belt": "tank",
                  "Spatula": None, "Frying Pan": None}


def adjust(avg, gain):
    """Expected place after `gain` places of help: gains act on the distance from 1st, so they shrink as a comp
    nears 1st and the result stays in 1-8 (additive near the average: d/dgain = -1 at gain 0)."""
    d = avg - 1
    return round(min(8.0, 1 + d * math.exp(-gain / d)), 2) if d > 0 else avg


@functools.lru_cache(maxsize=None)
def tiers():
    """Tier cut points (expected avg place at most): from MetaTFT's own letters (tools/calibrate.py tiers)."""
    f = ROOT / "data" / "models" / "tier_calibration.json"
    if not f.exists():
        return TIERS_PRIOR
    cuts = json.loads(f.read_text())["cuts"]
    return [(t, cuts[t]) for t in ("OP", "S+", "S", "A", "B", "C") if t in cuts] + [("D", 99)]


def tier_of(place):
    return next(t for t, cut in tiers() if place <= cut)


def catalog(static):
    """Everything the page offers as input: units, traits, items by kind, augments."""
    comps, build = recipes()
    audit = _audit()
    arts = sorted(set(meta.artifacts(static["set"])) | {a["name"] for a in audit.get("artifacts", [])})
    emblems = sorted(f"{t['name']} Emblem" for t in static["traits"] if t.get("kind") in ("origin", "class")
                     and len(t.get("breakpoints") or []) > 1)
    augs = meta.augments(static["set"])
    roles = {u["name"]: u for u in audit.get("units", [])}
    tinfo = {t["name"]: t for t in audit.get("traits", [])}
    locks = {u["unit"]: describe(u["when"]) for u in static["unlocks"]}
    detail = lambda n, k: (roles.get(n) or {}).get(k)                                       # noqa: E731
    return {"units": [{"name": u["name"], "cost": u["cost"], "traits": u["traits"], "unlock": locks.get(u["name"]),
                       "role": detail(u["name"], "riot_role"), "range": detail(u["name"], "range"), "hp": detail(u["name"], "hp"),
                       "melee": detail(u["name"], "melee"), "damage": detail(u["name"], "damage_type"), "ability": detail(u["name"], "ability")}
                      for u in static["units"]],
            "traits": [t["name"] for t in static["traits"]],
            "trait_info": [{"name": t["name"], "breakpoints": t.get("breakpoints") or [], "counts": t.get("counts", "units"),
                            "kind": t.get("kind"), "summary": (tinfo.get(t["name"]) or {}).get("summary"),
                            "effects": (tinfo.get(t["name"]) or {}).get("effects") or {}} for t in static["traits"]],
            "recipes": {it: sorted(k) for k, it in build.items()},
            "icons": _icons(),
            "components": sorted(comps), "completed": sorted(set(build.values())), "artifacts": arts,
            "radiants": sorted(r["name"] for r in audit.get("radiants", [])), "emblems": emblems,
            "augments": sorted(({"name": a["name"], "tier": a.get("tier"), "category": a.get("category"),
                                 "status": a.get("status"), "summary": a.get("summary", ""), "expert": a.get("expert")}
                                for a in augs.values() if a.get("status") not in ("likely_removed",)),
                               key=lambda a: a["name"])}


def _icons():
    """{kind: {name: "kind/file.png"}} from tools/fetch_icons.py; {} before it has run."""
    f = ROOT / "data" / "assets" / "icons" / "index.json"
    return {k: v for k, v in json.loads(f.read_text()).items() if not k.startswith("_")} if f.exists() else {}


def _audit():
    f = ROOT / "data" / "manual" / "TFTSet19.audit.json"
    return json.loads(f.read_text()) if f.exists() else {}


def item_kind(item, build):
    """AD / AP / tank from an item's components (majority); None for items without a recipe."""
    parts = next((list(k) for k, v in build.items() if v == item), None)
    if not parts:
        return None
    kinds = [COMPONENT_KIND.get(p) for p in parts if COMPONENT_KIND.get(p)]
    return max(set(kinds), key=kinds.count) if kinds else None


def damage_type(parts):
    """An item's damage type from its two components (names, any case): AD / AP when its damage components agree,
    hybrid when it has one of each, tank when it has none. The rule tools/calibrate.py items measured the off-type
    premium with."""
    kind = {k.lower(): v for k, v in COMPONENT_KIND.items()}
    ks = {kind.get((x or "").lower()) for x in parts} - {None, "tank"}
    return "hybrid" if ks == {"AD", "AP"} else ks.pop() if ks else "tank"


OFF = {"AD": "AP", "AP": "AD"}


def unit_kind(u):
    """What items a unit wants: AD, AP or tank (MetaTFT role: 'Attack Marksman', 'Magic Tank', ...)."""
    role = (meta.units().get(u) or {}).get("role", "")
    if role.endswith("Tank"):
        return "tank"
    return "AP" if role.startswith("Magic") else "AD" if role.startswith("Attack") else None


COUNTERS = {    # unlock counters in words; {n} is the threshold
    "hyperpop_casts": "{n} casts by Hyperpop units", "hyperpop_kills": "{n} kills by Hyperpop units",
    "captivated_seconds": "enemies Captivated for {n}s in total", "rock_combats": "field Rock for {n} combats",
    "xayah_ally_damage": "{n} damage dealt by allies while Xayah is fielded", "bling": "{n} True Damage bling",
    "ionic_cheers": "{n} Ionic Spark fan cheers", "xayah_interest": "{n} interest earned while Xayah is fielded",
    "xayah_player_damage": "{n} player damage dealt while Xayah is fielded", "hype": "{n} Hyperpop hype",
    "instruments": "all {n} instruments", "malzahar_damage": "{n} damage dealt by Malzahar",
    "collab_inspires": "Collab units inspired {n} times", "rerolls_before_2_carousel": "{n} rerolls before the stage-2 carousel",
}


def _num(n):
    return f"{n:,}" if isinstance(n, int) else str(n)


def _or(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " or " + xs[-1]


def describe(when):
    """An unlock condition in plain words (static data; engine/unlocks.py checks it)."""
    out = []
    for k, v in when.items():
        if k == "counter":
            text = COUNTERS.get(v["name"], "{n} " + v["name"].replace("_", " ")).format(n=_num(v["n"]))
            out.append(text + (f" with {v['requires_trait']} active" if v.get("requires_trait") else ""))
        elif k == "window":
            text = COUNTERS.get(v["counter"], "{n} " + v["counter"].replace("_", " ")).format(n=_num(v["n"]))
            out.append(text + (f" (only until {v['deadline']})" if v.get("deadline") else ""))
        elif k == "unit_state":
            items = v.get("items")
            out.append(f"a {v.get('stars', 1)}★ {_or(v['units'])}" + (" holding an item" if items == 1 else f" holding {items} items" if items else ""))
        elif k == "items_on":
            out.append(f"{v['n']} items on {_or(v.get('traits') or v.get('units') or [])} units")
        elif k == "board_stars":
            out.append(f"{v['n']} star levels of {_or(v['traits'])} units on your board")
        elif k == "board_unique":
            out.append(f"{v['n']} different {_or(v['traits'])} units on your board")
        elif k == "item_on_role":
            out.append(f"{v['item']} on a {_or(v['roles'])}")
        elif k == "gold_end_combat":
            out.append(f"{v['n']}+ gold at the end of a combat")
        elif k == "beach_pop_hex_each_cost":
            out.append("a unit of every cost starting combat in a Beach Pop hex")
        elif k == "front_rows_max":
            out.append(f"at most {v['n']} champion in the front two rows")
        elif k == "streak":
            out.append(f"a {v['win']}-round win streak and a {v['loss']}-round loss streak")
        elif k == "traits_active":
            out.append(f"{v['n']}+ active {'non-unique ' if v.get('non_unique') else ''}traits")
        elif k == "all_of":
            out.append(" and ".join(describe(x) for x in v))
        else:
            out.append(k.replace("_", " ") + ((": " + ", ".join(f"{a} {b}" for a, b in v.items())) if isinstance(v, dict) and v else ""))
    return "; ".join(out)


def classify(items, cat):
    kinds = {"components": [], "completed": [], "artifacts": [], "radiants": [], "emblems": [], "unknown": []}
    sets = {k: set(cat[k]) for k in ("components", "completed", "artifacts", "radiants", "emblems")}
    for i in items:
        kinds[next((k for k, s in sets.items() if i in s), "unknown")].append(i)
    return kinds


def artifact_base(set_name):
    global ARTIFACT_BASE
    if ARTIFACT_BASE is None:
        cs = [c for a in meta.artifacts(set_name).values() for c in a["holders"].values()]
        ARTIFACT_BASE = sum(cs) / len(cs) if cs else 0.0
    return ARTIFACT_BASE


@functools.lru_cache(maxsize=None)
def measured_items():
    """tools/calibrate.py items (Set 18 crawl, 22,784 Master+ boards): premium over a normal completed item, in
    places (- = better), [estimate, 2.5%, 97.5%]. Falls back to zeros (no premium) before it has been run."""
    f = ROOT / "data" / "models" / "item_calibration.json"
    return json.loads(f.read_text())["effects"] if f.exists() else {}


def _premium(key):
    return -(measured_items().get(key) or [0.0])[0]       # places gained (+ = better)


def _premium_cost(key):
    """Places lost (+ = worse) for an effect measured as worse than a normal item."""
    return (measured_items().get(key) or [0.0])[0]


@functools.lru_cache(maxsize=None)
def bis_need(set_name):
    """{unit: how much its best-in-slot items matter relative to the average unit}: its best-in-slot weight in the
    board model (engine/power.py bis: Set 18 learned weights vs MetaTFT-style best-build gaps, r = -0.48, carried
    onto Set 19 through MetaTFT's builds) over the mean weight. Carries that need their items > 1, tanks < 1."""
    m = power._model(set_name) or {}
    w = {k[4:]: v for k, v in (m.get("weights") or {}).items() if k.startswith("bis:")}
    mean = sum(w.values()) / len(w) if w else 0.0
    return {u: min(3.0, max(0.25, v / mean)) for u, v in w.items()} if mean > 0 else {}


def bis_premium(unit, set_name="TFTSet19"):
    """Best-in-slot premium for an item on this unit: the pooled Set 18 premium (-0.087 places) x the unit's need."""
    return _premium("bis") * bis_need(set_name).get(unit, 1.0)


def comp_bis(plan, det, units, u):
    """A holder's best-in-slot set: the comp's listed items for it (its most common build in this comp) and its
    BIS_PER_UNIT most played items (MetaTFT unit page): 'most common items', as tools/calibrate.py items defines BIS."""
    play = (units.get(u) or {}).get("item_play", {})
    top_unit = [i for i, _ in sorted(play.items(), key=lambda x: -x[1])[:BIS_PER_UNIT]]
    return set(plan["items"].get(u) or []) | set(top_unit)


def item_gains(static, plan, held, cat, det=None):
    """[(item, holder, places, label)] for what you hold, at the premiums measured on Set 18 boards (tools/calibrate.py
    items): a best-in-slot item over a non-BIS one (scaled by how much its holder needs its items); a radiant or an
    artifact on a holder that wants it vs on one that doesn't (radiant: its normal version is the holder's best-in-slot;
    artifact: the holder is one of its usual holders, MetaTFT's six on Set 19). Components are matched to the comp's
    best-in-slot recipes, carry first, as you'd slam them: a pair that builds one = that item's premium; a single one
    that is half of a wanted item = half; one that builds nothing the comp wants = nothing. So a Rod and a Tear favour
    the comp whose carry wants Blue Buff, not every comp, and Lich Bane favours the comps that play its holders."""
    _, build = recipes()
    units = meta.units(static["set"])
    holders = main_carry_first(plan.get("name") or plan.get("id", "")[4:], list(plan["items"]) or plan["carries"])
    slots = bis_slots(plan, det, units, holders)
    carry, ctype = damage_carry(plan) if plan.get("carries") else (holders[0] if holders else None, None)
    dealers = damage_dealers(plan, holders)          # {AD / AP: the comp's non-tank carries dealing it}

    def wants(base):     # the holder whose build lists it, else whose most played items include it, else any BIS set
        top3 = lambda h: [i for i, _ in sorted((units.get(h) or {}).get("item_play", {}).items(), key=lambda x: -x[1])[:3]]
        return next((h for h in holders if base in (plan["items"].get(h) or [])), None) \
            or next((h for h in holders if base in top3(h)), None) \
            or next((h for h in holders if base in comp_bis(plan, det, units, h)), None)

    out = []
    for it in held["completed"]:
        u = wants(it)
        g, lab = (bis_premium(u, static["set"]), "best-in-slot" + need_note(u)) if u else (0.0, "")
        parts = next((list(k) * (2 if len(k) == 1 else 1) for k, v in build.items() if v == it), [])
        if not g and parts and offtype(damage_type(parts), dealers):
            g, lab = -_premium_cost("offtype_carry"), f"{damage_type(parts)} item, and this comp's carries ({_or(sum(dealers.values(), []))}) deal {OFF[damage_type(parts)]} damage"
        out.append((it, u, round(g, 3), (lab or "not best-in-slot for this comp's holders") + " (Set 18 measured)"))
        if u and (u, it) in slots:
            slots.remove((u, it))
    for it in held["radiants"]:
        base = re.sub(r"^(Radiant|Prismatic) ", "", it)
        u = wants(base)
        parts = next((list(k) * (2 if len(k) == 1 else 1) for k, v in build.items() if v == base), [])
        kind = damage_type(parts) if parts else None
        # not anyone's best-in-slot: still of the carry's damage type (hybrid: any carry), or a tank item for a tank
        on = None if u else carry if kind and (kind == ctype or (kind == "hybrid" and ctype)) else \
            next((h for h in holders if kind == "tank" and unit_kind(h) == "tank"), None)
        g = _premium("radiant_fit") if u else -_premium_cost("radiant_ontype") if on else -_premium_cost("radiant_misfit")
        out.append((it, u or on, round(g, 3), (f"{base} is best-in-slot for {u}" if u else
                                               f"{base} isn't best-in-slot here but suits {on}" if on else f"no holder here wants {base}")
                    + " (Set 18 measured: a radiant on a holder that wants it, of its type, or neither)"))
        if u and (u, base) in slots:
            slots.remove((u, base))
    out += component_gains(slots, held["components"], build, dealers)
    arts = meta.artifacts(static["set"])
    for a in held["artifacts"]:
        if a not in arts:                                  # no MetaTFT holder data: no basis to favour any comp
            out.append((a, None, 0.0, "no MetaTFT holder data for this artifact"))
            continue
        hs = {u: c for u, c in arts[a]["holders"].items() if u in plan["units"]}
        best = min(hs, key=hs.get, default=None)
        g = _premium("artifact_fit") if best else -_premium_cost("artifact_misfit")
        out.append((a, best, round(g, 3), (f"{best} is one of its usual holders (MetaTFT)" if best else
                                           "none of its usual holders (MetaTFT) is in this comp")
                    + " (Set 18 measured: an artifact on a usual holder vs not)"))
    return out


def conditions(set_name):
    f = ROOT / "data" / "manual" / f"{set_name}.conditions.json"
    return json.loads(f.read_text())["conditions"] if f.exists() else []


def met(static, cond, owned, held, aug_tags):
    """Does what you hold meet one condition clause?"""
    c = cond["if"]
    _, build = recipes()
    if "unit" in c:
        return owned.get(c["unit"], 0) >= c.get("stars", 1)
    if "units_any" in c:
        return sum(u in owned for u in c["units_any"]) >= c["n"] and (not c.get("requires") or c["requires"] in owned)
    if "trait_units" in c:
        return sum(c["trait_units"] in _traits(static, u) for u in owned) >= c["n"]
    if "components" in c:
        return sum(COMPONENT_KIND.get(i) == c["components"] for i in held["components"]) >= c["n"]
    if "item" in c:
        return c["item"] in held["completed"] + held["artifacts"] + held["radiants"] or f"Radiant {c['item']}" in held["radiants"]
    if "emblem" in c:
        return c["emblem"] in held["emblems"]
    if "emblems_any" in c:
        return len(held["emblems"]) >= c["emblems_any"]
    if "augment" in c:
        return any(c["augment"] in tg for tg in aug_tags)
    return False


def archetype(static, plan, comp):
    """MetaTFT's own label ("Fast 9" / "Fast 8" or "Standard" / "lvl 6"), else engine/augments.py's rule (reroll at 7
    or below; fast 9 with 3+ five-costs in its core; else fast 8)."""
    style = comp.get("style") or ""
    if style == "Fast 9":
        return "fast9"
    if style in ("Fast 8", "Standard"):
        return "fast8"
    if style.startswith("lvl"):
        return "reroll"
    return A.archetype(plan, static)


def damage_carry(plan, name=None):
    """(unit, AD / AP): the comp's main damage carry -- its first non-tank carry (named one first), typed by MetaTFT
    role; if every carry is a tank, the first one ("Magic Tank" = AP). Items don't decide: AP carries build Gloves and
    Belt items (Annie's Striker's Flail reads AD) and tanks build Tear ones (Spirit Visage reads AP)."""
    roles = {h: (meta.units().get(h) or {}).get("role", "") for h in plan["carries"]}
    kind = lambda role: "AP" if role.startswith("Magic") else "AD" if role.startswith("Attack") else None
    order = main_carry_first(name or plan.get("name") or plan.get("id", "")[4:], list(plan["carries"]))
    pick = next((h for h in order if not roles[h].endswith("Tank") and kind(roles[h])), None) \
        or next((h for h in order if kind(roles[h])), None)
    return pick, kind(roles[pick]) if pick else None


def main_damage(plan, name=None):
    return damage_carry(plan, name)[1]


def condition_gains(static, plan, comp, conds_met, valued=()):
    """Met conditions that name this comp or its archetype; an item condition whose item is already valued
    on a holder here (item_gains) counts once, there."""
    arch = archetype(static, plan, comp)
    # shown, not weighted: every condition is a unit opener (-> where your units lead), an item or artifact (-> item
    # premiums), an emblem (-> measured emblem premiums) or an augment kind (-> measured augment effects); a weight here
    # would count the same thing twice
    return [(cd["why"], 0.0, cd.get("source", ""))
            for cd in conds_met if comp["name"] in cd.get("comps", []) or cd.get("archetype") == arch]


def emblem_gains(static, plan, emblems):
    """[(emblem, trait, places, label)] on the comp's final board, at the premiums measured on Set 18 boards over a
    normal item (tools/calibrate.py items): in a trait the comp runs (a tier deeper, or the holder gains an active
    trait's bonus), activating a trait the comp doesn't run (a splash), or leaving the trait inactive."""
    board = [{"unit": u, "stars": plan["stars"].get(u, 1)} for u in plan["units"]]
    ext = dict(static, units=list(static["units"]))
    out = []
    for n, e in enumerate(emblems):
        t = e[:-len(" Emblem")]
        before = trait_tiers(ext, board).get(t, (0, 0))[0]
        ext["units"].append({"name": f"__{t}{n}", "cost": 0, "traits": [t]})
        board = board + [{"unit": f"__{t}{n}", "stars": 1}]
        after = trait_tiers(ext, board).get(t, (0, 0))[0]
        kind = "used" if before else "activates" if after else "dead"
        g = _premium("emblem_used") if kind == "used" else -_premium_cost(f"emblem_{kind}")
        why = {"used": f"{t} is active here" + (": a tier deeper" if after > before else ": the holder gains its bonus"),
               "activates": f"activates {t}, which this comp doesn't run (a splash)",
               "dead": f"{t} stays inactive in this comp"}[kind]
        out.append((e, t, round(g, 3), why + " (Set 18 measured)"))
    return out


def _traits(static, u):
    return next((x["traits"] for x in static["units"] if x["name"] == u), [])


def opener_strengths(static):
    """{units on board: sorted strengths of the meta openers that size}: MetaTFT lists core units only, so a
    board is compared with openers of the same size, not the same level. Stars as pairs usually go: 1-costs
    2-star from level 5, 2-costs from level 6."""
    out = {}
    for c in pbe_comps(static):
        for e in c.get("early", []):
            board = opener_board(static, e)
            if board:
                out.setdefault(len(board), []).append(board_score(static, board))
    return {n: sorted(v) for n, v in out.items()}


def board_score(static, board):
    """Fight score (stars and board size count as fights do) when engine/power.py fight has run, else the ranking score."""
    return power.fight_z(static, board) if power._model(static["set"]).get("fight") else power.strength(static, board)


def opener_board(static, e):
    cost = {u["name"]: u["cost"] for u in static["units"]}
    lv = e["level"]
    return [{"unit": u, "stars": 2 if (cost.get(u, 9) == 1 and lv >= 5) or (cost.get(u, 9) == 2 and lv >= 6) else 1}
            for u in e["units"]]


def midgame(static, plan, comp):
    """Level 7-8 boards: MetaTFT's level variants when scraped, else the level-7 opener filled from the
    final board, cheapest first (marked constructed)."""
    var = meta.variants(static["set"]).get(comp["name"])
    if var:
        return [{"level": lv, "units": us, "avg_place": ap, "source": "MetaTFT"} for lv in (7, 8) for us, ap in var.get(lv, [])[:2]]
    cost = {u["name"]: u["cost"] for u in static["units"]}
    base = list(plan["early"].get(7) or plan["early"].get(6) or [])
    rest = sorted((u for u in plan["units"] if u not in base), key=lambda u: cost.get(u, 9))
    out = []
    for lv in (7, 8):
        b = (base + rest)[:lv]
        out.append({"level": lv, "units": sorted(b, key=lambda u: cost.get(u, 9)), "source": "constructed"})
    return out


def place_units(static, units, fixed):
    """[(unit, hex)]: units keep their final-board hex (MetaTFT positioning) where they have one; the rest go
    front (melee) or back (ranged), nearest free hex to the middle (front) or the corners (back)."""
    rng = {u["name"]: u.get("range") for u in catalog_units(static)}
    taken, out = set(), []
    for u in units:
        if u in fixed and fixed[u] not in taken:
            out.append((u, fixed[u]))
            taken.add(fixed[u])
    for u in units:
        if any(x == u for x, _ in out):
            continue
        melee = (rng.get(u) or 1) <= 1
        order = ([(0, c) for c in (3, 2, 4, 1, 5, 0, 6)] + [(1, c) for c in (3, 2, 4, 1, 5, 0, 6)]) if melee else \
            ([(3, c) for c in (0, 6, 1, 5, 2, 4, 3)] + [(2, c) for c in (0, 6, 1, 5, 2, 4, 3)])
        order += [(r, c) for r in range(4) for c in range(7)]
        h = next(r * 7 + c for r, c in order if r * 7 + c not in taken)
        out.append((u, h))
        taken.add(h)
    return out


@functools.lru_cache(maxsize=None)
def _roles(set_name):
    f = ROOT / "data" / "manual" / f"{set_name}.audit.json"
    return {u["name"]: u for u in (json.loads(f.read_text()).get("units", []) if f.exists() else [])}


def catalog_units(static):
    roles = _roles(static["set"])
    return [{"name": u["name"], "range": (roles.get(u["name"]) or {}).get("range")} for u in static["units"]]


def stages(static, c, p, det):
    """Board tabs for a comp: MetaTFT's openers (levels 4-6), its level 7-10 boards and the final board, each
    placed on the hex grid. Stars: openers as pairs usually go; level 7-8 boards 2-star up to 3-costs; level 9+
    and final at the comp's targets. Items: the carries' best-in-slot from level 8 on."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    fixed = dict((det or {}).get("positions") or [])
    target = {b["unit"]: b.get("stars", 1) for b in c.get("board", [])}
    items = {b["unit"]: b.get("items", []) for b in c.get("board", []) if b.get("items")}

    def star(u, lv):
        if lv >= 9:
            return target.get(u, 2 if cost.get(u, 9) <= 3 else 1)
        if lv >= 7:
            return min(target.get(u, 2), 2) if cost.get(u, 9) <= 3 else 1
        return 2 if (cost.get(u, 9) == 1 and lv >= 5) or (cost.get(u, 9) == 2 and lv >= 6) else 1

    def board(units, lv, with_items):
        return [{"unit": u, "stars": star(u, lv), "items": items.get(u, []) if with_items else [], "hex": h}
                for u, h in place_units(static, units, fixed)]

    out = []
    for e in sorted(c.get("early", []), key=lambda e: e["level"]):
        if e["level"] <= 6:
            out.append({"key": f"o{e['level']}", "label": f"Lvl {e['level']}", "group": "Opener", "units": board(e["units"], e["level"], False),
                        "note": f"MetaTFT's most common level-{e['level']} board (core units only): {e['round_win_rate']:.0%} round win rate"})
    levels = (det or {}).get("levels") or {}
    share = (det or {}).get("level_share") or {}
    for lv in (7, 8, 9, 10):
        bs = levels.get(lv)
        if bs:
            us, ap = bs[0]
            out.append({"key": f"l{lv}", "label": f"Lvl {lv}", "group": "Midgame" if lv <= 8 else "Late",
                        "units": board(us, lv, lv >= 8), "avg_place": ap, "share": share.get(str(lv), share.get(lv)),
                        "note": f"MetaTFT's most common level-{lv} board: avg place {ap:.2f}"
                                + (f"; {share.get(str(lv), share.get(lv)):.0%} of games end at {lv}" if share.get(str(lv), share.get(lv)) else ""),
                        "alternatives": [{"units": u2, "avg_place": a2} for u2, a2 in bs[1:]]})
        elif lv in (7, 8):
            m = next((x for x in midgame(static, p, c) if x["level"] == lv), None)
            if m:
                out.append({"key": f"l{lv}", "label": f"Lvl {lv}", "group": "Midgame", "units": board(m["units"], lv, lv >= 8),
                            "note": "constructed: the level-7 opener filled from the final board, cheapest first"})
    out.append({"key": "final", "label": "Final", "group": "Final",
                "units": [{"unit": b["unit"], "stars": b.get("stars", 1), "items": b.get("items", []), "hex": h}
                          for b, (_, h) in zip(c.get("board", []), place_units(static, [b["unit"] for b in c.get("board", [])], fixed))],
                "note": "MetaTFT's final board and positioning" if fixed else "MetaTFT's final board (positions: front for melee, back for ranged)"})
    return out


def best_augments(static, c, p, arch, det, k=6):
    """The augments this model values most for the comp (static guide, like tftflow's augment setup)."""
    cat = A.catalog(static["set"])
    base = _centre(static["set"], c["name"], arch)
    rows = []
    for a, info in meta.augments(static["set"]).items():
        if (info.get("status") or "confirmed") != "confirmed":
            continue
        v, kind, why = augvalue.value(static, c, p, arch, a, cat, det)
        rows.append((v - base, a, kind, why, info.get("tier")))
    rows.sort()
    best, seen = [], Counter()                    # the best of each kind first, then the rest: a varied shortlist
    for row in rows:
        if seen[row[2]] < 1:
            best.append(row)
            seen[row[2]] += 1
    best += [r for r in rows if r not in best]
    return [{"augment": a, "places": round(-v, 2), "kind": kind, "why": why, "tier": t} for v, a, kind, why, t in best[:k]]


_CENTRES = {}


def _centre(set_name, comp_name, arch):
    return _CENTRES.get((set_name, comp_name, arch), 0.0)


def progression(det, c):
    lv = (det or {}).get("levelling") or []
    return {"levelling": [{"level": L, "stage": st, "rerolls": r} for L, st, r in lv] or
            [{"level": x["level"], "stage": x["stage"], "rerolls": None} for x in c.get("levelling", [])],
            "carousel": [{"item": i, "priority": n} for i, n in (det or {}).get("carousel") or []]}


@functools.lru_cache(maxsize=None)
def top4_line(set_name="TFTSet19"):
    """Top-4 share from average place, least squares over MetaTFT's comps (2026-11-23: 43 comps, r = -0.992,
    residual sd 0.014): for comps without MetaTFT placements (lolchess-only ones, on MetaTFT's place scale)."""
    xs = [(c["avg_place"], sum(pl[:4]) / sum(pl)) for c in pbe_comps(load_set(set_name)) if c.get("source") != "lolchess"
          for pl in [(meta.details(set_name).get(c["name"]) or {}).get("placements") or []] if len(pl) == 8 and sum(pl)]
    if len(xs) < 3:
        return lambda a: 0.5
    mx, my = sum(a for a, _ in xs) / len(xs), sum(t for _, t in xs) / len(xs)
    b = sum((a - mx) * (t - my) for a, t in xs) / sum((a - mx) ** 2 for a, _ in xs)
    return lambda a: min(1.0, max(0.0, my + b * (a - mx)))


def comp_stats(det, c):
    pl = (det or {}).get("placements") or []
    ppg = (det or {}).get("players_per_game") or []
    return {"top4": round(sum(pl[:4]) / (sum(pl) or 1), 3) if len(pl) == 8 else round(top4_line()(c["avg_place"]), 3),
            "win": round(pl[0], 3) if pl else c.get("win_rate"),
            "placements": pl, "contested": round(1 - ppg[0] - ppg[1], 3) if len(ppg) >= 2 else None}


def flex_units(det, c):
    """Units played in this comp beyond its final board, best average place first (MetaTFT comp unit table)."""
    final = {b["unit"] for b in c.get("board", [])} | set(c["units"])
    return [{"unit": u, "avg_place": a, "play_rate": pr} for u, a, pr in sorted(((det or {}).get("units") or []), key=lambda x: x[1])
            if u not in final and pr >= 0.05][:5]


def comp_items(det, c):
    """The comp's most played items with their average place in the comp (MetaTFT comp item table)."""
    return [{"item": i, "avg_place": a, "play_rate": pr, "vs_comp": round(a - c["avg_place"], 2)}
            for i, a, pr in sorted(((det or {}).get("items") or []), key=lambda x: -x[2])[:8]]



LP = [40, 30, 20, 10, -10, -20, -30, -40]   # ponytail: ranked LP by place at an even MMR (Riot's scale varies with MMR)


def expected_lp(det):
    pl = (det or {}).get("placements") or []
    return round(sum(p * lp for p, lp in zip(pl, LP)), 1) if len(pl) == 8 else None


def tempo_profile(static, comps):
    """(generic early rate per unit, tempo share per comp), both measured from MetaTFT's opener boards:
    generic: how often a unit is on anyone's level 4-6 opener (pick-weighted share of openers holding it);
    tempo share: the fraction of a comp's level 4-6 opener units that never make its final board (tempo filler)."""
    seen, total = {}, 0.0
    share = {}
    for c in comps:
        early = [e for e in c.get("early", []) if e["level"] <= 6]
        w = c.get("pick_rate", 0.0) or 0.0
        units = [u for e in early for u in e["units"]]
        for u in set(units):
            seen[u] = seen.get(u, 0.0) + w
        total += w if early else 0.0
        if units:
            share[c["name"]] = sum(u not in c["units"] for u in units) / len(units)
    generic = {u: v / total for u, v in seen.items()} if total else {}
    mean_share = sum(share.values()) / len(share) if share else 0.0
    return generic, {c["name"]: share.get(c["name"], mean_share) for c in comps}


def unit_role(static, c, u, det):
    """'keep' (in the comp's final board or its play table), 'opener' (on its MetaTFT openers) or 'tempo'."""
    rate = {x: pr for x, _, pr in (det or {}).get("units") or []}
    if u in c["units"] or rate.get(u, 0.0) >= 0.1:
        return "keep"
    if u in {x for e in c.get("early", []) for x in e["units"]}:
        return "opener"
    return "tempo"


@functools.lru_cache(maxsize=None)
def odds_calibration():
    """tools/eval_lines.py fit: naive-Bayes floor, opener likelihood and temperature alpha fitted by held-out log-
    likelihood on boards sampled from MetaTFT's openers and final boards, and tau, the conformal cut-off that keeps the
    comp a board came from in the realistic set 90% of the time. {} before it has run (the priors above apply)."""
    f = ROOT / "data" / "models" / "odds_calibration.json"
    return json.loads(f.read_text()) if f.exists() else {}


def odds_tables(static, comps, details):
    """Per comp: (log prior, {unit: (on its openers, base likelihood)}) and the generic opener rates, for line_odds.
    Base likelihood: the unit's play rate in the comp's final boards (1 if on its listed board), or its chance of
    being tempo filler there (the comp's measured tempo share x how often anyone opens with it)."""
    generic, tshare = tempo_profile(static, comps)
    out = {}
    for c in comps:
        det = details.get(c["name"]) or details.get(c.get("parent") or "") or {}      # lolchess variants: their parent's panels
        rate = {u: min(1.0, pr) for u, _, pr in det.get("units") or []}
        for u in c["units"]:
            rate[u] = 1.0
        opener = {u for e in c.get("early", []) for u in e["units"]}
        units = set(rate) | opener | set(generic)
        out[c["name"]] = (math.log(max(c.get("pick_rate", 0.01), 0.01)),
                          {u: (u in opener, max(rate.get(u, 0.0), tshare[c["name"]] * generic.get(u, 0.0))) for u in units})
    return out, generic


def line_odds(static, owned, comps, details, params=None, tables=None):
    """P(comp | the units you hold), naive Bayes on MetaTFT data. Prior: the comp's pick rate. Likelihood of each unit:
    its play rate in the comp's final boards, the opener likelihood if it is on the comp's opener boards, or -- a unit
    the comp doesn't play -- the chance it is tempo filler there, floored. So a strong early unit no comp keeps
    (a 2-star 2-cost) doesn't pin you to the one comp that does: it is filler for every line. The summed
    log-likelihood is scaled by alpha, and each unit's term by cost^beta: cheap units are everyone's tempo, dear ones
    commit you (all fitted, odds_calibration). Stars aren't used: a 2-star is tempo, not a reroll commitment."""
    if not owned:
        return {}
    p = params or odds_calibration()
    floor, op, alpha, beta = p.get("floor", ODDS_FLOOR), p.get("opener", ODDS_OPENER), p.get("alpha", 1.0), p.get("beta", 0.0)
    tab, _ = tables or odds_tables(static, comps, details)
    cost = {u["name"]: max(u["cost"], 1) for u in static["units"]}
    w = {u: cost.get(u, 1) ** beta for u in owned}         # dearer units commit you more (beta fitted; 0 = all equal)
    logp = {}
    for c in comps:
        prior, lik = tab[c["name"]]
        logp[c["name"]] = prior + alpha * sum(w[u] * math.log(max(floor, op if lik.get(u, (False, 0.0))[0] else 0.0,
                                                                  lik.get(u, (False, 0.0))[1])) for u in owned)
    top = max(logp.values())
    z = sum(math.exp(v - top) for v in logp.values())
    return {n: math.exp(v - top) / z for n, v in logp.items()}


@functools.lru_cache(maxsize=None)
def _rules():
    f = ROOT / "data" / "manual" / "pro_rules.json"
    return json.loads(f.read_text()) if f.exists() else {"rules": [], "top10": []}


def playbook(arch, k=8):
    """Pro rules for a line (static; docs/knowledge/pro_playbook.md): this archetype's own rules first, then the
    playbook's top general rules. MetaTFT's 'Standard' is a fast-8 line."""
    d = _rules()
    want = {"fast9": {"fast9"}, "fast8": {"fast8", "standard"}, "reroll": {"reroll"}}.get(arch, set())
    own = [r for r in d["rules"] if (r["when"] or {}).get("archetype") in want]
    top = [r for r in d["rules"] if r["id"] in d.get("top10", []) and r not in own]
    out = []
    for r in (own + top)[:k]:
        nums = [f"{k2.replace('_', ' ')}: {v}" for k2, v in (r.get("numbers") or {}).items() if isinstance(v, (int, float, str)) and len(str(v)) < 40][:3]
        out.append({"id": r["id"], "area": r["area"], "title": r.get("title", r["id"]), "do": r["do"], "numbers": nums,
                    "confidence": r.get("confidence"), "conflict": r.get("conflict"), "own": r in own,
                    "source": (r.get("sources") or [{}])[0].get("who")})
    return out


ROUNDS = ("2-1", "3-2", "4-1", "4-2", "4-5", "5-1", "5-5", "6-1")


def main_carry_first(comp_name, holders):
    """Holders with the main carry first: MetaTFT names a comp after its trait and main carry ("Gu Feng Aphelios"),
    so the holder named earliest in the comp's name; else the listed order."""
    named = sorted((comp_name.find(h), i) for i, h in enumerate(holders) if h and comp_name.find(h) >= 0)
    return [holders[named[0][1]]] + [h for i, h in enumerate(holders) if i != named[0][1]] if named else holders


def buildable(item):
    """An item a player can make or hold: a completed recipe, an artifact, a radiant or an emblem -- not a trait's
    own item (Gu Feng's Scrolls, Bard's Horn, Tactician's Crown), which no component builds."""
    return item in set(recipes()[1].values()) or item in meta.artifacts() or item.startswith(("Radiant ", "Prismatic ")) \
        or item.endswith(" Emblem")


def bis_slots(plan, det, units, holders):
    """[(holder, item)] a comp wants, in slam order: each holder (carry first) gets its listed build (items a player
    builds), topped up to BIS_PER_UNIT with its most played items."""
    out = []
    for h in holders:
        listed = [i for i in plan["items"].get(h) or [] if buildable(i)]
        more = sorted(i for i in comp_bis(plan, det, units, h) - set(listed) if buildable(i))
        out += [(h, i) for i in (listed + more)[:BIS_PER_UNIT]]
    return out


def need_note(u):
    n = bis_need("TFTSet19").get(u)
    return f" ({u} needs its items {n:.1f}x the average unit)" if n and abs(n - 1) >= 0.25 else ""


def damage_dealers(plan, holders):
    """{"AD" / "AP": [units]}: the damage types the comp's non-tank carries deal (MetaTFT role). An item of a type
    one of them deals has a home; an item of neither type goes on a carry it doesn't suit."""
    out = {}
    for h in dict.fromkeys(list(holders) + list(plan.get("carries") or [])):
        role = (meta.units().get(h) or {}).get("role", "")
        k = "AP" if role.startswith("Magic") else "AD" if role.startswith("Attack") else None
        if k and not role.endswith("Tank"):
            out.setdefault(k, []).append(h)
    return out


def offtype(kind, dealers):
    """An AD / AP item no carry in the comp deals (hybrid and tank items always find a holder)."""
    return kind in ("AD", "AP") and bool(dealers) and kind not in dealers


def component_gains(slots, components, build, dealers=None):
    """Match held components to open best-in-slot slots: full recipes first (in slot order), then single components
    that are half of a still-open slot. [(component(s), holder, places, label)]."""
    recipe = {v: tuple(sorted(k)) * (2 if len(k) == 1 else 1) for k, v in build.items()}
    pool = Counter(components)
    out, open_ = [], []
    for h, i in slots:
        r = recipe.get(i)
        if r and not (Counter(r) - pool):
            pool -= Counter(r)
            out.append((" + ".join(r), h, round(bis_premium(h), 3), f"builds {i}, best-in-slot for {h}" + need_note(h)))
        elif r:
            open_.append((h, i, r))
    for h, i, r in open_:
        x = next((c for c in r if pool[c] > 0), None)
        if x:
            pool[x] -= 1
            out.append((x, h, round(COMPONENT_SHARE * bis_premium(h), 3), f"half of {i} for {h}"))
    for c in pool.elements():                                # left over: off-type for every carry costs (half an item's)
        off = offtype(COMPONENT_KIND.get(c), dealers or {})
        out.append((c, None, round(-COMPONENT_SHARE * _premium_cost("offtype_carry"), 3) if off else 0.0,
                    f"{COMPONENT_KIND[c]} component, and this comp's carries ({_or(sum(dealers.values(), []))}) deal "
                    f"{OFF[COMPONENT_KIND[c]]} damage (Set 18 measured)" if off else "builds nothing this comp wants"))
    return out


def typical_stars(set_name, unit, board_target=None):
    """The star level a final board usually has the unit at: MetaTFT's most common star level for it (a 3-star target
    on the comp's MetaTFT board wins)."""
    if board_target == 3:
        return 3
    st = (meta.units(set_name).get(unit) or {}).get("stars") or {}
    return max(st, key=lambda s: st[s].get("share") or 0) if st else (board_target or 1)


def pivot_cost(static, c, owned):
    """What going into this comp from your units takes: units still to buy and the gold for them at their usual star
    levels, plus upgrades of units you hold below it. Static: shop odds and your gold aren't modelled."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    target = {b["unit"]: b.get("stars") for b in c.get("board") or []}
    buy, gold = [], 0
    for u in c["units"]:
        s = typical_stars(static["set"], u, target.get(u))
        have = owned.get(u, 0)
        if have < s:
            gold += cost.get(u, 1) * (3 ** (s - 1) - (3 ** (have - 1) if have else 0))
            buy.append({"unit": u, "stars": s, "have": have})
    return {"buy": buy, "gold": gold, "keep": [u for u in c["units"] if owned.get(u)]}


@functools.lru_cache(maxsize=None)
def level_at(set_name, rnd):
    """The level a typical player has at a round: pick-weighted median over MetaTFT comps' levelling."""
    from power import _rnd
    lv = []
    for c in pbe_comps(load_set(set_name)):
        if c.get("source") != "lolchess" and c.get("levelling"):
            lv.append((max((e["level"] for e in c["levelling"] if e["stage"] is None or _rnd(e["stage"]) <= _rnd(rnd)), default=3),
                       c.get("pick_rate") or 0))
    lv.sort()
    half, acc = sum(w for _, w in lv) / 2, 0.0
    for v, w in lv:
        acc += w
        if acc >= half:
            return v
    return 3


@functools.lru_cache(maxsize=None)
def usual_round(set_name, n):
    """The round whose lobby has boards closest to n units (pick-weighted mean level of MetaTFT comps then, as
    engine/power.py lobby_at builds it); the earlier round on a tie; None when no round's boards are within a unit of
    n (a 1- or 2-unit board is stage 1, before the first round listed). A board's default comparison: a typical
    level-8 board is one at 5-1, not the end-of-game boards that the same-size par is built from."""
    def size(r):
        lob = power.lobby_at(set_name, r)
        w = sum(x[0] for x in lob)
        return sum(x[0] * x[3] for x in lob) / w if w else 0.0
    best = min(ROUNDS, key=lambda r: abs(size(r) - n))
    return best if abs(size(best) - n) <= 1 else None


def past(set_name, deadline, mine, stage=None):
    """Is your board past a round? The round you picked, else more units than a typical board has by then."""
    from power import _rnd
    if stage:
        return _rnd(stage) > _rnd(deadline)
    return len(mine) > level_at(set_name, deadline)


def availability(static, c, mine, stage=None):
    """Each unlock-gated unit in the comp, checked against your board (engine/unlocks.py conditions): ready,
    progress n / target, a condition only the game can track (counters, streaks), or closed: a window unlock
    (Seraphine: rerolls before 2-4) your board is past without holding the unit."""
    locks = {u["unit"]: u for u in static["unlocks"]}
    roles = {n: (u.get("role") or "").split(" ")[-1] for n, u in meta.units(static["set"]).items()}
    b = Board(static, {"board": [dict(x) for x in mine]})
    out = []
    for u in c["units"]:
        if u not in locks:
            continue
        if any(x["unit"] == u for x in mine):
            out.append({"unit": u, "status": "have", "detail": "on your board"})
            continue
        (kind, arg), = locks[u]["when"].items()
        if kind == "window" and past(static["set"], arg["deadline"], mine, stage):
            out.append({"unit": u, "status": "closed", "detail": f"{describe(locks[u]['when'])}; your board is past {arg['deadline']}",
                        "min_level": locks[u].get("min_level")})
            continue
        try:
            ok, v, n, detail = check(locks[u]["when"], b, {"roles": roles})
        except (KeyError, ValueError, TypeError):
            ok, v, n, detail = None, None, None, describe(locks[u]["when"])
        status = "ready" if ok is True else "in-game" if ok is None else "closed" if ok == "dead" else "progress"
        out.append({"unit": u, "status": status, "value": v, "target": n,
                    "detail": detail if status != "in-game" else describe(locks[u]["when"]),
                    "min_level": locks[u].get("min_level")})
    return out


def clean_input(static, inp):
    """The request as find reads it, checked at the trust boundary (the page posts JSON): an object; units a list of
    {unit on the roster, stars 1-4, items}; items, augments and filter lists lists of strings; hp 1-100 or absent.
    Raises ValueError on a wrong shape; unknown unit names are dropped and returned under "unknown_units"."""
    if not isinstance(inp, dict):
        raise ValueError("expected a JSON object")

    def strs(v, what):
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ValueError(f"{what} must be a list of names")
        return v
    roster = {u["name"] for u in static["units"]}
    units, unknown = [], []
    raw = inp.get("units") or []
    if not isinstance(raw, list) or not all(isinstance(u, dict) and isinstance(u.get("unit"), str) for u in raw):
        raise ValueError("units must be a list of {unit, stars, items}")
    for u in raw:
        st = u.get("stars", 1)
        if not isinstance(st, int) or isinstance(st, bool):
            raise ValueError(f"stars for {u['unit']} must be a whole number")
        if u["unit"] not in roster:
            unknown.append(u["unit"])
            continue
        units.append(dict(u, stars=min(max(st, 1), 4), items=strs(u.get("items") or [], f"items on {u['unit']}")))
    hp = inp.get("hp")
    if hp is not None and (isinstance(hp, bool) or not isinstance(hp, (int, float)) or not 1 <= hp <= 100):
        raise ValueError("hp must be a number from 1 to 100")
    filters = inp.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    for k in ("must_units", "exclude_units", "traits", "styles"):
        if k in filters:
            strs(filters[k], f"filters.{k}")
    if filters.get("sort", "tier") not in ("tier", "fit", "place", "odds", "lp", "top4"):
        raise ValueError("filters.sort must be tier, fit, place, odds, lp or top4")
    return dict(inp, units=units, items=strs(inp.get("items") or [], "items"), augments=strs(inp.get("augments") or [], "augments"),
                filters=filters), unknown


def find(static, inp):
    """inp: {"units": [{"unit", "stars"}], "items": [...], "augments": [...], "filters": {...}, "stage": round or absent}
    -> results. stage: compare your board with the lobby at that round instead of a typical board its size (display
    only: tempo and comps' places keep the size comparison, which the tempo slope was measured on)."""
    inp, unknown_units = clean_input(static, inp)
    stage = inp.get("stage") or None
    if stage is not None and stage not in ROUNDS:          # before anything reads it (unlock windows compare rounds)
        raise ValueError(f"stage must be one of {', '.join(ROUNDS)}")
    cat = catalog(static)
    units_in = inp.get("units") or []
    # items on units count as held (the line finder asks what you hold); the board's strength keeps them on their units
    held = classify(list(inp.get("items") or []) + [i for u in units_in for i in u.get("items") or []], cat)
    owned = {}
    for u in units_in:
        owned[u["unit"]] = max(owned.get(u["unit"], 0), max(u.get("stars", 1), 1))
    filt = inp.get("filters") or {}
    cost = {u["name"]: u["cost"] for u in static["units"]}
    locks = {u["unit"]: u for u in static["unlocks"]}
    plans = {p["id"][4:]: p for p in pbe_plans(static)}
    openers = opener_strengths(static)
    mine = [{"unit": u["unit"], "stars": max(u.get("stars", 1), 1), "items": list(u.get("items") or [])}
            for u in units_in if not u.get("bench")] or [{"unit": u, "stars": s, "items": []} for u, s in owned.items()]
    my_strength = board_score(static, mine) if mine else None
    # units you're invested in -- the board's carry, not filler: 3-star, holding two items, or a 2-star 5- or 7-cost
    # (an unitemised 2-star 4-cost is strong frontline that fits many lines, not yet a carry)
    invested = {x["unit"]: x for x in mine if x["stars"] >= 3 or len(x["items"]) >= 2
                or (x["stars"] >= 2 and cost.get(x["unit"], 1) >= INVESTED_COST)}
    weight = {u: (s ** 1.5) * math.sqrt(cost.get(u, 1)) for u, s in owned.items()}
    win = power.win_chance(static, mine, inp.get("augments") or []) if mine else None
    details = meta.details(static["set"])
    acat = A.catalog(static["set"])
    aug_tags = [A.tags(a, "", static, acat)[0] for a in inp.get("augments") or []]
    conds_met = [cd for cd in conditions(static["set"]) if met(static, cd, owned, held, aug_tags)]
    out = []
    odds = line_odds(static, owned, pbe_comps(static), details)
    tempo = tempo_shifts(static, plans, inp.get("hp"), stage or (usual_round(static["set"], len(mine)) if mine else None))
    held_any = any(held[k] for k in ("components", "completed", "artifacts", "radiants", "emblems")) or bool(inp.get("augments"))
    for c in pbe_comps(static):
        p = plans.get(c["name"])
        if not p:
            continue
        p = dict(p, units=c["units"])
        allu = set(c["units"]) | {u for e in c.get("early", []) for u in e["units"]}
        traits = {t for u in c["units"] for t in _traits(static, u)}
        arch = archetype(static, p, c)
        if not _passes(filt, arch, p, allu, traits):
            continue
        used = [u for u in owned if u in allu]
        fit = sum(weight[u] for u in used) / sum(weight.values()) if owned else 0.0
        it = item_gains(static, p, held, cat, details.get(c["name"]))
        em = emblem_gains(static, p, held["emblems"])
        det = details.get(c["name"]) or details.get(c.get("parent") or "")      # lolchess variants: their parent's panels
        key = (static["set"], c["name"], arch)
        if key not in _CENTRES:
            _CENTRES[key] = augvalue.centred(static, c, p, arch, acat, det)
        ag = []
        for r, a in enumerate(inp.get("augments") or []):          # slot order = pick order: 2-1, 3-2, 4-2
            v, kind, why = augvalue.value(static, c, p, arch, a, acat, det, round_idx=min(r, 2))
            ag.append((a, round(_CENTRES[key] - v, 2), why, (meta.augments(static["set"]).get(a) or {}).get("expert"), kind))
        cg = condition_gains(static, p, c, conds_met, {i for i, _, g, _ in it if g > 0})
        special = set(held["artifacts"]) | set(held["radiants"])
        gains = {"items": sum(g for i, _, g, _ in it if i not in special),
                 "artifacts": sum(g for i, _, g, _ in it if i in special),
                 "emblems": sum(g for *_, g, _ in em),
                 "augments": sum(x[1] for x in ag),
                 "tempo": -(tempo.get(c["name"]) or {}).get("places", 0.0),
                 "conditions": 0.0}
        # the HP chain's shift is in places already (its chain is anchored to MetaTFT's average): added, not adjust()ed
        place = min(8.0, max(1.0, adjust(c["avg_place"], sum(v for k, v in gains.items() if k != "tempo")) - gains["tempo"]))
        early = []
        for e in sorted(c.get("early", []), key=lambda e: e["level"]):
            board = opener_board(static, e)
            pool = openers.get(len(board)) or []
            st = board_score(static, board) if board else None
            early.append({"level": e["level"], "units": e["units"], "round_win_rate": e["round_win_rate"],
                          "have": [u for u in e["units"] if u in owned],
                          "stronger_than": round(sum((x < st) + 0.5 * (x == st) for x in pool) / len(pool), 2) if pool and st is not None else None})
        unlocks = [{"unit": u, "min_level": locks[u].get("min_level"), "condition": describe(locks[u]["when"])}
                   for u in c["units"] if u in locks]
        out.append({
            "name": c["name"], "units": c["units"], "style": c["style"], "metatft_tier": c["tier"], "avg_place": c["avg_place"],
            "source": c.get("source", "metatft"), "parent": c.get("parent"),
            "pick_rate": c["pick_rate"], "win_rate": c["win_rate"], "adjusted_place": round(place, 2),
            "tier": tier_of(place), "fit": round(fit, 2), "uses": used, "gains": {k: round(v, 2) for k, v in gains.items()},
            "item_notes": [{"item": i, "holder": u, "places": g, "why": w} for i, u, g, w in it],
            "emblem_notes": [{"item": e, "trait": t, "places": g, "why": w} for e, t, g, w in em],
            "augment_notes": [{"augment": a, "places": g, "why": w, "expert_set18": x, "kind": k} for a, g, w, x, k in ag],
            "tempo_note": tempo.get(c["name"]), "unlock_arrival": unlock_arrival(static, c, det),
            "stages": stages(static, c, p, det), "progression": progression(det, c), "stats": dict(comp_stats(det, c), lp=expected_lp(det)),
            "odds": round(odds.get(c["name"], 0.0), 4), "playbook": playbook(arch),
            "pivot": {k: [u for u in owned if unit_role(static, c, u, det) == k] for k in ("keep", "opener", "tempo")},
            "flex": flex_units(det, c), "comp_items": comp_items(det, c), "best_augments": best_augments(static, c, p, arch, det),
            "conditions_met": [{"why": w, "places": g, "source": src} for w, g, src in cg],
            "openers": early, "midgame": midgame(static, p, c),
            "plus_one": [u for u in c["units"][len(p["core"]):]],
            "unlocks": unlocks, "availability": availability(static, c, mine, stage) if mine else [],
            "pivot_cost": pivot_cost(static, c, owned),
            "endgame": [{"unit": b["unit"], "stars": b.get("stars", 1), "items": b.get("items", []),
                         "top_items": _top_items(b["unit"])} for b in c.get("board", [])],
            "artifact_holders": _artifact_holders(static, c["units"]),
            "levelling": c.get("levelling", []), "final_level_share": c.get("final_level_share", {}),
            "carries": main_carry_first(c["name"], p["carries"]), "archetype": arch,
        })
    rank = {t: i for i, (t, _) in enumerate(tiers())}
    min_fit = filt.get("min_fit", 0)              # every comp: a board can pivot anywhere; odds say where it leads
    out = [r for r in out if r["fit"] >= min_fit]
    if filt.get("min_tier") in rank:
        out = [r for r in out if rank[r["tier"]] <= rank[filt["min_tier"]]]
    key = {"tier": lambda r: (rank[r["tier"]], -r["odds"], r["adjusted_place"]),    # tiers, then where your board leads
           "fit": lambda r: (-r["odds"], r["adjusted_place"]), "place": lambda r: r["adjusted_place"],
           "odds": lambda r: -r["odds"], "lp": lambda r: -(r["stats"].get("lp") or -99),
           "top4": lambda r: -top4_now(r)}[filt.get("sort", "tier")]
    out.sort(key=key)
    pct = None
    if my_strength is not None and openers:
        pool = openers.get(len(mine)) or []
        # ties count half: the standard Ziggs + Lulu opener equals every other Ziggs + Lulu opener exactly
        pct = round(sum((s < my_strength) + 0.5 * (s == my_strength) for s in pool) / len(pool), 2) if pool else None
    # suggested lines: the strongest comps for you (expected place with your items, augments and board strength)
    # among those something you hold carries into: a unit it keeps or opens with, or items / augments that measurably
    # favour it. Units it doesn't use are tempo: play them now, sell them on the way. A 2-star 2-cost is a strong
    # opener for any line, not a reason to reroll.
    total = sum(c.get("pick_rate", 0.0) for c in pbe_comps(static)) or 1.0
    prior = {c["name"]: (c.get("pick_rate", 0.0) or 0.0) / total for c in pbe_comps(static)}
    best, tau = max(odds.values(), default=0.0), odds_calibration().get("tau", 0.0)
    fitness = lambda r: sum(r["gains"][k] for k in ("items", "artifacts", "emblems", "augments"))
    fits = sorted(fitness(r) for r in out)
    top_fit = fits[(3 * len(fits)) // 4] if fits else 0.0     # the top quarter of comps by how well your items fit
    for r in out:
        r["lift"] = round(r["odds"] / prior[r["name"]], 2) if owned and prior.get(r["name"]) else None
        # with units: a unit it keeps or opens with (generic items and augments help every line, so they rank the
        # reachable lines but don't make one reachable); without units: items / augments that favour it
        # a unit you're invested in that this comp itemises as its main carry (or second carry, unless a tank: a
        # frontline piece fits anywhere) keeps the comp open: the odds ask where boards like yours came from, and four
        # filler units outvote one 3-star carry; a pro builds around the carry they have
        cs = r["carries"]
        r["anchors"] = [{"unit": u, "stars": x["stars"], "items": len(x["items"])} for u, x in invested.items()
                        if u in cs[:1] or (u in cs[:2] and unit_kind(u) != "tank")]
        if owned:                     # realistic: within the conformal cut-off of the likeliest line (odds_calibration)
            r["reachable"] = (odds.get(r["name"], 0.0) >= tau * best and bool(r["pivot"]["keep"] or r["pivot"]["opener"])) \
                or bool(r["anchors"])
        else:                         # items / augments only: the comps they fit best (top quarter)
            r["reachable"] = not held_any or (fitness(r) > 0 and fitness(r) >= top_fit)
        # closed: a carry you can no longer unlock (a window you're past) -- the line isn't open to this board
        carries = set(r["carries"][:1]) | {b["unit"] for b in r["endgame"] if len(b["items"]) >= 2}
        r["closed"] = [a["unit"] for a in r["availability"] if a["status"] == "closed" and a["unit"] in carries]
        if r["closed"]:
            r["reachable"] = False
    # one card per family: a comp sharing VARIANT_OVERLAP of its units with a better suggestion is listed as its variant
    suggested = []

    def card(r, cap):
        same = next((s for s in suggested if len(set(r["units"]) & set(s["units"])) / len(set(r["units"]) | set(s["units"])) >= VARIANT_OVERLAP), None)
        if same:
            same.setdefault("variants", []).append(r["name"])
        elif len(suggested) < cap:
            suggested.append(r)

    # lines that carry a unit you're invested in first: a pro plays around the carry they have; then by expected place
    order = lambda r: (not r["anchors"], r["adjusted_place"])
    for r in sorted((r for r in out if r["reachable"]), key=order):
        card(r, SUGGESTIONS)
    # fewer than SUGGESTIONS_MIN cards (a mixed or a settled board): stretch lines, likeliest first, from the wider
    # conformal set (tau_stretch keeps the board's comp 99% of the time) that still keep or open with a unit you hold
    # -- never a line the odds rule out, or one you'd start from scratch
    tau_s = odds_calibration().get("tau_stretch", 0.0)
    stretch = (r for r in out if owned and not r["reachable"] and not r["closed"] and odds.get(r["name"], 0.0) >= tau_s * best
               and (r["pivot"]["keep"] or r["pivot"]["opener"]))
    for r in sorted(stretch, key=lambda r: -odds.get(r["name"], 0.0)):
        if len(suggested) >= SUGGESTIONS_MIN:
            break
        card(r, SUGGESTIONS_MIN)
    suggested.sort(key=order)          # then strongest first, realistic or stretch (marked on the card)
    res = {"comps": out, "suggested": [r["name"] for r in suggested], "your_board": {"strength": round(my_strength, 2) if my_strength is not None else None,
                                         "level": len(mine), "stronger_than_openers": pct,
                                         "win_chance": round(win, 3) if win is not None else None,
                                         "tempo_gold": round(augvalue.tempo_gold(round(win, 2), static["set"]), 1) if win is not None else None,
                                         "vs_typical": power.fight_breakdown(static, mine) if mine and power._model(static["set"]).get("fight") else None,
                                         "stage": None, "typical_level": None,
                                         "hp": inp.get("hp"), "tempo_round": next((t["round"] for t in tempo.values()), None)},
            "unknown_items": held["unknown"], "unknown_units": unknown_units}
    # board strength: against the lobby at the round you picked, else at the round when boards are usually your size
    # (the same-size number, win_size, stays: tempo was measured on it)
    if mine and power._model(static["set"]).get("fight"):
        rnd = stage or usual_round(static["set"], len(mine))
        vs = power.vs_lobby(static, mine, rnd) if rnd else None
        if vs:
            res["your_board"].update(win_chance=round(vs["win"], 3), stage=rnd, stage_auto=not stage, typical_level=vs["typical_level"],
                                     win_size=round(win, 3) if win is not None else None,
                                     vs_typical={k: vs[k] for k in ("parts", "items", "typical_items")})
    return res


def tempo_shifts(static, plans, hp, rnd):
    """{comp: tempo note} for a player at `rnd` with `hp` (engine/survival.py: the HP chain on MetaTFT-anchored
    curves): places and top-4 shift against a typical player of the comp alive then, its roll-down, your chance to
    reach it. A lolchess variant takes its MetaTFT parent's; a comp with no MetaTFT levelling the mean shift of its
    archetype. {} without hp or a round to place it at."""
    if hp is None or not rnd:
        return {}
    import survival
    out, by_arch = {}, {}
    for c in pbe_comps(static):
        arch = archetype(static, plans[c["name"]], c) if c["name"] in plans else None
        sc = survival.scenario(static["set"], c.get("parent") or c["name"], rnd, int(round(hp)))
        if sc:
            out[c["name"]] = dict(sc, hp=hp, round=rnd, source="chain")
            by_arch.setdefault(arch, []).append(sc)
    for c in pbe_comps(static):
        if c["name"] not in out and c["name"] in plans:
            xs = by_arch.get(archetype(static, plans[c["name"]], c)) or [x for v in by_arch.values() for x in v]
            if xs:
                out[c["name"]] = {"places": round(sum(x["places"] for x in xs) / len(xs), 3), "top4": round(sum(x["top4"] for x in xs) / len(xs), 3),
                                  "online": None, "survive": None, "typical_hp": None, "hp": hp, "round": rnd, "source": "archetype mean"}
    return out


def unlock_arrival(static, c, det):
    """Unlock-gated units on the comp's final board and the first level whose MetaTFT boards mostly play them (2 of
    its 3 listed boards): a carry that only arrives at 8-9 is a line that waits on its unlock."""
    locks = {u["unit"] for u in static["unlocks"]}
    levels = (det or {}).get("levels") or {}
    out = []
    for b in c.get("board") or []:
        if b["unit"] in locks:
            lv = next((lv for lv in sorted(levels) if sum(b["unit"] in us for us, _ in levels[lv]) * 3 >= 2 * len(levels[lv])), None)
            out.append({"unit": b["unit"], "level": lv, "items": len(b.get("items") or [])})
    return out


def top4_now(r):
    """A comp's top-4 chance: MetaTFT's (lolchess's for its comps), moved by the HP chain when a tempo scenario is set."""
    base = r["stats"].get("top4")
    if base is None:
        base = 0.5
    return min(1.0, max(0.0, base + ((r.get("tempo_note") or {}).get("top4") or 0.0)))


def _passes(f, arch, p, allu, traits):
    if any(u not in allu for u in f.get("must_units") or []):
        return False
    if any(u in allu for u in f.get("exclude_units") or []):
        return False
    if f.get("traits") and not set(f["traits"]) & traits:
        return False
    if f.get("styles") and arch not in f["styles"]:
        return False
    if f.get("damage") and main_damage(p) != f["damage"]:
        return False
    return True


def _top_items(u):
    items = (meta.units().get(u) or {}).get("items", {})
    return [{"item": i, "place_change": c} for i, c in sorted(items.items(), key=lambda x: x[1])]


def _artifact_holders(static, units, k=4):
    base = artifact_base(static["set"])
    rows = [(c - base, a, u) for a, d in meta.artifacts(static["set"]).items() for u, c in d["holders"].items() if u in units]
    return [{"artifact": a, "holder": u, "places": round(c, 2)} for c, a, u in sorted(rows)[:k]]


def main():
    from unlocks import load_set
    static = load_set("TFTSet19")
    args = sys.argv[1:]
    inp = {"units": [], "items": [], "augments": []}
    skip = None
    for a in args:
        if skip:
            inp[skip] = [x.strip() for x in a.split(",") if x.strip()]
            skip = None
        elif a in ("--items", "--augments"):
            skip = a[2:]
        else:
            u, _, s = a.partition(":")
            inp["units"].append({"unit": u, "stars": int(s or 1)})
    res = find(static, inp)
    yb = res["your_board"]
    if yb["strength"] is not None:
        print(f"your board: strength {yb['strength']}" + (f", stronger than {yb['stronger_than_openers']:.0%} of "
              f"{yb['level']}-unit meta openers" if yb["stronger_than_openers"] is not None else ""))
    for r in res["comps"][:12]:
        print(f"{r['tier']:3} {r['name']:26} {r['style']:9} place {r['avg_place']:.2f} -> {r['adjusted_place']:.2f}  "
              f"fit {r['fit']:.0%}  uses {', '.join(r['uses']) or '-'}  {r['gains']}")
    if res["unknown_items"]:
        print("not recognised:", ", ".join(res["unknown_items"]))


if __name__ == "__main__":
    main()
