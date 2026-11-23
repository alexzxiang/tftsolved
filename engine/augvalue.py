"""What an augment (or a strong opener) is worth to each comp, in places against an average augment pick.

No public source has augment outcomes for Set 19 (Riot's match API dropped augments in 2024; MetaTFT hasn't
rated Set 19 augments; its comp pages have no augment section). So each augment kind gets an anchor in
places (TFT knowledge: a hero augment for the comp's carry is worth about 0.6 of a place, an econ augment on a fast-9
comp about 0.3, ...) and every anchor is scaled by how much THIS comp depends on what the augment gives,
measured from MetaTFT's per-comp data:
  econ / XP     how much the comp gains from reaching higher levels: final-level shares x the average-place gap
                between its level-N and level-N+1 boards, per gold of XP that level costs
  reroll        how much its reroll carries gain from 3-stars (MetaTFT unit star averages)
  items         how much its top items move placement within the comp (MetaTFT comp item table)
  trait         the average-place gap to the trait's next breakpoint, when the augment reaches it
  artifact      the best artifact holder in the comp, against the average holder
  hero          whether the hero is the comp's carry, core or absent
Each scale is normalised to mean 1 over the 43 comps, so the anchors keep their size on average and the data
decides which comps get more or less. When Set 19 augment stats exist (MetaTFT after 2026-12-02, our own
recorded picks), the anchors are what gets fitted: place change ~ anchor(kind, tier) x comp scale.

Tempo: a board's win chance against the typical board (engine/power.py) runs through a Monte Carlo of the
stage-2/3 fights (streak gold, HP lost) and becomes gold-equivalent, valued like an econ augment.
"""
import functools
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import augments as A  # noqa: E402
import meta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TIER = {"silver": 0.7, "gold": 1.0, "prismatic": 1.5}
# ponytail: anchors in places vs an average pick (negative = better), TFT knowledge until augment stats exist
ANCHOR = {"hero_carry": -0.6, "hero_core": -0.35, "hero_off": 0.3, "trait_bp": -0.5, "trait_in": -0.2, "trait_off": 0.3,
          "econ": -0.3, "reroll": -0.3, "item": -0.2, "artifact": -0.35, "combat": -0.2, "units": -0.1, "other": 0.0}
ECON_GOLD = {"silver": 10, "gold": 18, "prismatic": 30}    # gold-equivalent when a summary gives no numbers
SCALE_MIN, SCALE_MAX = 0.3, 1.8
# tools/calibrate.py needs (Set 18 crawl): per-comp marginal needs are stable (split-half Spearman ~0.8) but don't match
# within-comp controlled estimates (Spearman ~0), so each comp's scale is pulled halfway to its archetype's mean
SHRINK = 0.5                           # one comp's data moves an anchor at most this much
HP_GOLD = 0.4                                              # ponytail: gold one HP is worth by 4-1
ARCH_COMBAT = {"reroll": 1.1, "fast8": 1.0, "fast9": 0.8}


@functools.lru_cache(maxsize=None)
def calibration():
    """tools/calibrate.py augments: {scale, kind_offset, round_step} from measured augment outcomes; identity without."""
    f = ROOT / "data" / "models" / "augment_calibration.json"
    return json.loads(f.read_text()) if f.exists() else {"scale": 1.0, "kind_offset": {}, "round_step": {}}


GROUP = {"hero": "hero", "trait": "trait", "econ": "econ", "reroll": "econ", "item": "items", "combat": "combat",
         "units": "combat", "other": "combat"}


def calibrated(v, kind, round_idx=None):
    """Anchor-scale value -> measured scale: x scale, + the kind's measured offset, + its per-round change."""
    c = calibration()
    g = GROUP.get(kind, "combat")
    v = v * c.get("scale", 1.0) + c.get("kind_offset", {}).get(g, 0.0) \
        + (c.get("round_step", {}).get(g, 0.0) * round_idx if round_idx is not None else 0.0)
    lo, hi = c.get("bounds", {}).get(g, (None, None))
    # smooth bound at the kind's measured 10th / 90th percentile: ~v for small values, saturating at the bound
    if v < 0 and lo:
        return lo * math.tanh(v / lo)
    if v > 0 and hi:
        return hi * math.tanh(v / hi)
    return v


def _xp(set_name):
    c = json.loads((ROOT / "data" / "constants.json").read_text())[set_name]
    return {int(k): v for k, v in c["xp_to_next_level"].items()}, c


def level_curve(comp, details):
    """{level: avg place of its listed boards} from MetaTFT's level variants (details), else the comp's own."""
    lv = (details or {}).get("levels") or {}
    out = {int(k): sum(b[1] for b in v) / len(v) for k, v in lv.items() if v}
    return out


def econ_need(comp, details, set_name="TFTSet19"):
    """Places per gold of extra XP: sum over levels of P(ending there) x (gap to the next level's boards) / XP cost."""
    xp, _ = _xp(set_name)
    curve = level_curve(comp, details)
    share = (details or {}).get("level_share") or {str(k): v for k, v in (comp.get("final_level_share") or {}).items()}
    total = 0.0
    for L in (7, 8, 9):
        if L in curve and L + 1 in curve:
            total += float(share.get(str(L), share.get(L, 0)) or 0) * max(0.0, curve[L] - curve[L + 1]) / xp[L]
    return total


def reroll_need(static, comp):
    """Mean (2-star - 3-star) avg place over the comp's 1-3 cost carries (MetaTFT unit pages)."""
    units = meta.units(static["set"])
    cost = {u["name"]: u["cost"] for u in static["units"]}
    gaps = []
    for b in comp.get("board", []):
        st = (units.get(b["unit"]) or {}).get("stars", {})
        if b.get("items") and cost.get(b["unit"], 9) <= 3 and 2 in st and 3 in st and st[3]["avg_place"]:
            gaps.append(max(0.0, st[2]["avg_place"] - st[3]["avg_place"]))
    return sum(gaps) / len(gaps) if gaps else 0.0


def item_need(comp, details):
    """Mean (comp avg place - avg place with the item) over the comp's six most played items."""
    its = sorted((details or {}).get("items") or [], key=lambda x: -x[2])[:6]
    return sum(max(0.0, comp["avg_place"] - ap) for _, ap, _ in its) / len(its) if its else 0.0


@functools.lru_cache(maxsize=None)
def scales(static_key):
    """{comp: {econ, reroll, item}} each normalised to mean 1 over the comps (static_key: the set name)."""
    from unlocks import load_set
    from plans import pbe_comps
    static = load_set(static_key)
    det = meta.details(static_key)
    raw = {c["name"]: {"econ": econ_need(c, det.get(c["name"])), "reroll": reroll_need(static, c),
                       "item": item_need(c, det.get(c["name"]))} for c in pbe_comps(static)}
    arch = {c["name"]: ("fast9" if c["style"] == "Fast 9" else "reroll" if c["style"].startswith("lvl") else "fast8")
            for c in pbe_comps(static)}
    out = {n: {} for n in raw}
    for k in ("econ", "reroll", "item"):
        vals = [r[k] for r in raw.values() if r[k] > 0]
        mean = sum(vals) / len(vals) if vals else 1.0
        by_arch = {}
        for n, r in raw.items():
            by_arch.setdefault(arch[n], []).append(r[k] / mean if mean else 1.0)
        for n, r in raw.items():
            own = r[k] / mean if mean else 1.0
            group = sum(by_arch[arch[n]]) / len(by_arch[arch[n]])
            out[n][k] = min(SCALE_MAX, max(SCALE_MIN, SHRINK * group + (1 - SHRINK) * own))
    return out


def gold_in(summary):
    """Gold-equivalent an econ augment gives, from its summary's numbers (gold and XP count 1:1, as XP costs)."""
    nums = [int(n) for n, unit in re.findall(r"(\d+)\s*(gold|XP)", summary or "", re.I)]
    return sum(nums) or None


def trait_gain(static, comp, trait):
    """(reaches a new breakpoint?, place gap to it) if one more `trait` is added to the comp's final board."""
    from strength import trait_tiers
    info = {t["name"]: t for t in static["traits"]}.get(trait)
    if not info:
        return False, 0.0
    board = [{"unit": b["unit"], "stars": b.get("stars", 1)} for b in comp.get("board", [])]
    now = trait_tiers(static, board).get(trait, (0, 0))[0]
    count = sum(trait in next((u["traits"] for u in static["units"] if u["name"] == b["unit"]), []) for b in board)
    bps = info.get("breakpoints") or []
    nxt = [b for b in bps if b > count]
    if not nxt or nxt[0] != count + 1:
        return False, 0.0
    lv = meta.traits(static["set"])
    a, b = lv.get((trait, bps[now - 1])) if now else None, lv.get((trait, nxt[0]))
    return True, (a - b) if a and b else 0.0


@functools.lru_cache(maxsize=None)
def measured():
    """tools/kaggle_augments.py: placement effect per kind x round x fit and per tier, vs a combat augment taken in
    the same round (40,344 Master+ games, Sets 7-8, with end-state controls). {} if it hasn't been run."""
    f = ROOT / "data" / "models" / "augment_kaggle.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text())
    eff = dict(d.get("effects", {}))
    for k, (v, _) in (d.get("indirect") or {}).items():       # econ / reroll: add the mechanism back for on-plan picks
        if f"{k}|on" in eff:
            eff[f"{k}|on"] = [eff[f"{k}|on"][0] + v, eff[f"{k}|on"][1]]
    return eff


# within a kind, augments differ by strength: MetaTFT's expert letter mapped through the measured spread of augment
# outcomes (archived tactics.tools: 10th pct ~ -0.25 ... 90th ~ +0.3), at half weight because the list is Set 18's
EXPERT_PLACES = {"S": -0.25, "A": -0.12, "B": 0.0, "C": 0.12, "D": 0.3}
EXPERT_WEIGHT = 0.0    # tools/expert_letter_check.js: the current letters don't predict archived outcomes (S +0.06,
                       # A +0.05, B +0.01, C -0.04 vs the median, Set 12), so they carry no weight
MEASURED_KIND = {"hero": "hero", "trait": "trait", "econ_gold": "econ", "econ_xp": "econ", "reroll": "reroll",
                 "item": "items", "artifact_radiant": "items"}
ROUNDS = ("2-1", "3-2", "4-2")


def _measured_value(static, comp, arch, aug, cat, round_idx):
    """(places, kind, why) from measured effects, or None when there is no table or the kind isn't in it."""
    eff = measured()
    if not eff:
        return None
    info = meta.augments(static["set"]).get(aug) or {}
    tg, hero, trait = A.tags(aug, info.get("summary", ""), static, cat)
    kind = "hero" if hero else "trait" if trait else MEASURED_KIND.get(tg[0], "combat")
    fits, why = None, ""                                    # [(fit, weight)]: measured effects mixed by how likely
    if kind == "hero":                                     # the carry (2+ items), fielded without items, or not fielded
        holders = [u for u, its in (comp.get("items") or {}).items() if len(its) >= 2] + \
                  [b["unit"] for b in comp.get("board") or [] if len(b.get("items") or []) >= 2]
        fit = "carry" if hero in holders else "other" if hero in comp["units"] else "off"
        fits = [(fit, 1.0)]
        why = f"hero augment for {hero}" + {"carry": ", this comp's itemised carry", "other": ", fielded here but not itemised",
                                            "off": ", who this comp doesn't field"}[fit]
    elif kind == "trait":                                  # how deep the comp's final board takes the trait
        from strength import trait_tiers
        depth = trait_tiers(static, [{"unit": u, "stars": 1} for u in comp["units"]]).get(trait, (0, 0))[0]
        fit = "deep" if depth >= 2 else "light" if depth == 1 else "off"
        fits = [(fit, 1.0)]
        why = f"{trait} augment" + {"deep": ", a trait this comp takes deep", "light": ", a trait this comp only splashes",
                                    "off": "; this comp doesn't play it"}[fit]
    elif kind == "econ":                                   # this comp's measured chance of ending on level 9+
        share = comp.get("final_level_share") or {}
        p9 = sum(v for lv, v in share.items() if int(lv) >= 9) if share else (1.0 if arch == "fast9" else 0.0)
        fits = [("on", p9), ("off", 1 - p9)]
        why = f"econ augment; this comp ends on level 9+ {p9:.0%} of the time"
    elif kind == "reroll":                                 # a comp with a 3-star target (MetaTFT board)
        fit = "on" if any((b.get("stars") or 0) >= 3 for b in comp.get("board") or []) or arch == "reroll" else "off"
        fits = [(fit, 1.0)]
        why = "reroll augment" + (" on a comp that 3-stars a unit" if fit == "on" else f" on a {arch} line")
    else:
        why = f"{A.LABEL.get(tg[0], tg[0])} augment"
    rounds = [round_idx] if round_idx is not None else [0, 1, 2]
    vals = []
    for r in rounds:
        base = f"{kind}@{ROUNDS[min(r, 2)]}"
        if kind == "combat":
            vals.append(0.0)
            continue
        if not fits:
            vals.append((eff.get(base) or [0.0])[0])
            continue
        legacy = {"carry": "on", "other": "on", "deep": "on", "light": "on"}       # tables measured before the split
        vals.append(sum(w * (eff.get(f"{base}|{f}") or eff.get(f"{base}|{legacy.get(f, f)}") or [0.0])[0] for f, w in fits))
    v = sum(vals) / len(vals) + (eff.get(f"tier:{info.get('tier')}") or [0.0])[0] \
        + EXPERT_WEIGHT * EXPERT_PLACES.get(info.get("expert"), 0.0)
    when = f" at {ROUNDS[min(round_idx, 2)]}" if round_idx is not None else ""
    return v, kind, f"{why}{when} (measured in 40k Master+ games)"


def value(static, comp, plan, arch, aug, cat, details=None, round_idx=None, raw=False):
    """(places vs a combat augment, kind, why) for one augment on one comp; round_idx 0/1/2 = taken at 2-1/3-2/4-2.
    Measured effects (tools/kaggle_augments.py) when available; else the anchors, rescaled by tools/calibrate.py
    augments. raw: the anchor-scale value."""
    if not raw:
        m = _measured_value(static, comp, arch, aug, cat, round_idx)
        if m:
            return m
    v, kind, why = _value(static, comp, plan, arch, aug, cat, details)
    return (v, kind, why) if raw else (calibrated(v, kind, round_idx), kind, why)


def _value(static, comp, plan, arch, aug, cat, details=None):
    info = meta.augments(static["set"]).get(aug) or {}
    tg, hero, trait = A.tags(aug, info.get("summary", ""), static, cat)
    mult = TIER.get(info.get("tier"), 1.0)
    sc = scales(static["set"]).get(comp["name"], {})
    kind = tg[0]
    if hero:
        k = "hero_carry" if hero in plan.get("carries", []) else "hero_core" if hero in comp["units"] else "hero_off"
        return ANCHOR[k] * mult, "hero", {"hero_carry": f"hero augment for {hero}, this comp's carry",
                                          "hero_core": f"hero augment for {hero}, in this comp",
                                          "hero_off": f"hero augment for {hero}, who isn't in this comp"}[k]
    if trait:
        traits = {t for u in comp["units"] for t in next((x["traits"] for x in static["units"] if x["name"] == u), [])}
        if trait not in traits:
            return ANCHOR["trait_off"] * mult, "trait", f"{trait} augment; this comp doesn't play {trait}"
        bp, gap = trait_gain(static, comp, trait)
        if bp:
            return (ANCHOR["trait_bp"] - 0.3 * gap) * mult, "trait", f"{trait} augment reaches the next {trait} breakpoint (MetaTFT: {gap:+.2f} avg place there)"
        return ANCHOR["trait_in"] * mult, "trait", f"{trait} augment; this comp plays {trait}"
    if kind in ("econ_gold", "econ_xp"):
        e = gold_in(info.get("summary")) or ECON_GOLD.get(info.get("tier"), 18)
        s = sc.get("econ", 1.0)
        return ANCHOR["econ"] * (e / 18) * s, "econ", f"~{e} gold of econ; this comp's need for levels is {s:.1f}x the average comp"
    if kind == "reroll":
        s = sc.get("reroll", 1.0) if arch == "reroll" else 0.3 * sc.get("reroll", 1.0)
        return ANCHOR["reroll"] * mult * s, "reroll", f"reroll augment; {'reroll comp, ' if arch == 'reroll' else ''}3-star need {s:.1f}x average"
    if kind in ("item", "artifact_radiant"):
        s = sc.get("item", 1.0)
        base = ANCHOR["artifact"] if kind == "artifact_radiant" else ANCHOR["item"]
        return base * mult * s, "item", f"{A.LABEL.get(kind, kind)} augment; this comp's item need is {s:.1f}x average"
    if kind == "combat":
        f = ARCH_COMBAT.get(arch, 1.0)
        return ANCHOR["combat"] * mult * f, "combat", f"combat augment on a {arch} comp"
    if kind == "units":
        f = 1.0 if arch == "reroll" else 0.5
        return ANCHOR["units"] * mult * f, "units", "free units"
    return 0.0, kind, f"{A.LABEL.get(kind, kind)} augment"


def centred(static, comp, plan, arch, cat, details=None, raw=False):
    """Mean value of every offerable augment for this comp: subtracted so 0 = an average pick here."""
    vals = [value(static, comp, plan, arch, a, cat, details, raw=raw)[0] for a in meta.augments(static["set"])
            if (meta.augments(static["set"])[a].get("status") or "confirmed") in ("confirmed",)]
    return sum(vals) / len(vals) if vals else 0.0


@functools.lru_cache(maxsize=None)
def tempo_gold(win, set_name="TFTSet19", runs=2000, seed=7):
    """Gold-equivalent of a board that wins each stage-2/3 fight with probability `win`, against one that wins half:
    streak gold, PvP win gold and HP kept by 4-1 (HP_GOLD per HP). Monte Carlo over 10 PvP rounds."""
    _, c = _xp(set_name)
    streak_gold = {int(k): v for k, v in c["streak_gold"].items()}
    dmg = {int(k): v for k, v in c["stage_damage"].items()}

    def run(p, rng):
        gold = hp = 0.0
        streak = 0
        for r in range(10):
            stage = 2 if r < 4 else 3
            won = rng.random() < p
            streak = (streak + 1 if streak >= 0 else 1) if won else (streak - 1 if streak <= 0 else -1)
            gold += streak_gold.get(min(abs(streak), max(streak_gold)), 0) + (c["pvp_win_gold"] if won else 0)
            if not won:
                hp += dmg[stage] + 2 + stage                  # stage damage + a few surviving units
        return gold - HP_GOLD * hp

    rng = random.Random(seed)
    a = sum(run(win, rng) for _ in range(runs)) / runs
    rng = random.Random(seed)
    b = sum(run(0.5, rng) for _ in range(runs)) / runs
    return a - b


def tempo_value(win, comp, arch, set_name="TFTSet19"):
    """Places a board's early strength is worth to a comp: its gold-equivalent valued like an econ augment
    for fast 8/9 comps (a win streak funds levels); reroll comps take it at half (they roll at 3-2/4-1 anyway)."""
    g = tempo_gold(round(win, 2), set_name)
    s = scales(set_name).get(comp["name"], {}).get("econ", 1.0)
    f = 0.5 if arch == "reroll" else 1.0
    return ANCHOR["econ"] * (g / 18) * s * f, g
