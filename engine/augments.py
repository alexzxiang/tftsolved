# Augments and lines: which augments suit which archetype (fast 9, fast 8, reroll) and which plan.
#
# An augment is tagged by category (catalog entry, else keywords in its on-screen description, so cards
# never seen before still get tags). A plan's archetype comes from its roll level. Fit = how much the
# archetype wants that category, overridden for hero augments (only their unit's plans) and trait
# augments/emblems (only plans using the trait). Pre-game this is a static guide per plan (like
# tftflow's "augment setup" + "+1 tier conditions"); post-game it ranks the offers each augment round
# for the line taken. No live advice (docs/POLICY.md).
#
#   python3 -I engine/augments.py TFTSet19                 # setup + strong augments per plan
#   python3 -I engine/augments.py TFTSet19 STATE.jsonl     # review the augment offers of a recorded game
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from unlocks import load_set  # noqa: E402

LABEL = {"econ_gold": "Econ", "econ_xp": "XP", "reroll": "Reroll", "item": "Item", "emblem": "Emblem",
         "hero": "Hero", "combat": "Combat", "artifact_radiant": "Artifact/Radiant", "units": "Units",
         "other": "Other"}
# how much each archetype wants a category (tftflow Set 18 pattern: fast 9 = Econ + Econ + Item,
# reroll = Reroll/Combat + Item, fast 8 = flexible Econ/Item/Combat)
WANT = {
    "fast9": {"econ_xp": 1.0, "econ_gold": 1.0, "item": 0.6, "artifact_radiant": 0.6, "combat": 0.4,
              "units": 0.2, "reroll": 0.3},
    "fast8": {"econ_gold": 0.8, "item": 0.8, "artifact_radiant": 0.8, "combat": 0.7, "econ_xp": 0.5,
              "reroll": 0.4, "units": 0.4},
    "reroll": {"reroll": 1.0, "combat": 0.8, "item": 0.7, "artifact_radiant": 0.6, "econ_gold": 0.5,
               "units": 0.6, "econ_xp": 0.1},
}
SETUP = {"fast9": "Econ + Econ + Item", "fast8": "Econ/Item + Combat + Item", "reroll": "Reroll + Combat + Item"}
CATALOG = ROOT / "data/manual/augments.json"


def catalog(set_name):
    if not CATALOG.exists():
        return {}
    d = json.loads(CATALOG.read_text())
    return {a["name"].lower(): a for a in d.get(set_name, []) + d.get("recurring", [])}


def tags(name, desc, static, cat=None):
    """(category tags, hero unit, trait) for an augment. Catalog first, else keywords in its text."""
    e = (cat or {}).get((name or "").lower().rstrip("+").strip()) or (cat or {}).get((name or "").lower())
    if e:
        return [e["category"]] + [x for x in e.get("also", []) if x != e["category"]], e.get("hero_unit"), e.get("trait")
    text = f"{name} {desc}".lower()
    units = sorted((u["name"] for u in static["units"]), key=len, reverse=True)
    traits = sorted((t["name"] for t in static["traits"]), key=len, reverse=True)
    trait = next((t for t in traits if re.search(rf"\b{re.escape(t.lower())}\b", text)), None)
    hero = next((u for u in units if re.search(rf"\b(?:strongest|your) {re.escape(u.lower())}\b", text)), None)
    out = set()
    if hero:
        out.add("hero")
    if "emblem" in text or "crown" in text:
        out.add("emblem")
    if "artifact" in text or "radiant" in text:
        out.add("artifact_radiant")
    if re.search(r"anvil|component|\bitems?\b", text) and "emblem" not in out:
        out.add("item")
    if "reroll" in text:
        out.add("reroll")
    if re.search(r"\bxp\b|level", text):
        out.add("econ_xp")
    if re.search(r"\d+\s*gold|\bgold\b", text):
        out.add("econ_gold")
    if re.search(r"copy of each|gain (?:a|\d+) .*champion", text) and not hero:
        out.add("units")
    if re.search(r"team gains|attack damage|ability power|attack speed|combat start|health|armor|damage", text):
        out.add("combat")
    order = ["hero", "emblem", "artifact_radiant", "reroll", "econ_xp", "econ_gold", "item", "units", "combat"]
    return [x for x in order if x in out] or ["other"], hero, trait


def archetype(plan, static=None):
    """reroll: rolls at level 7 or below. fast9: needs level 9 to find its board (3+ five-costs in its
    core, or a unit gated at level 9+). Otherwise fast8 (roll at 8, finish at 9: MetaTFT's "Standard")."""
    if (plan.get("roll_level") or 8) <= 7:
        return "reroll"
    if static:
        units = {u["name"]: u for u in static["units"]}
        gates = {u["unit"]: u.get("min_level") or 0 for u in static["unlocks"]}
        core = plan.get("core", [])
        if sum(units.get(n, {}).get("cost") == 5 for n in core) >= 3 or any(gates.get(n, 0) >= 9 for n in core):
            return "fast9"
    return "fast8"


def plan_traits(static, plan):
    units = {u["name"]: u for u in static["units"]}
    return {t for n in plan.get("core", []) + plan.get("flex", []) for t in units.get(n, {}).get("traits", [])}


def fit(static, plan, aug_tags, hero, trait):
    """0..1.5: how well one augment suits a plan."""
    if hero:
        return 1.5 if hero in plan.get("carries", []) else 1.2 if hero in plan.get("core", []) else 0.0
    if trait:
        return 1.2 if trait == plan.get("trait") else 0.8 if trait in plan_traits(static, plan) else 0.1
    want = WANT[archetype(plan, static)]
    first, *rest = aug_tags                          # primary category in full, side effects at half
    return max([want.get(first, 0.2)] + [0.5 * want.get(t, 0.2) for t in rest])


def strong_augments(static, plan, cat):
    """Catalog augments that lift this plan the most: hero augments for its units, its trait's
    emblems/augments ("+1 tier conditions")."""
    out = []
    for a in cat.values():
        tg, hero, trait = tags(a["name"], a.get("summary", ""), static, cat)
        f = fit(static, plan, tg, hero, trait)
        if f >= 1.2:
            out.append((f, a["name"]))
    return [n for _, n in sorted(out, reverse=True)]


def review_offers(static, state, plans_ranked, cat):
    """For each augment round of a recorded game: the final offer ranked for the line(s) in play."""
    out = []
    for r in state.get("augment_offers", []):
        cards = [c for c in r.get("final", []) if c]
        rows = []
        for c in cards:
            tg, hero, trait = tags(c, r.get("desc", {}).get(c, ""), static, cat)
            score = max((fit(static, p, tg, hero, trait) for p in plans_ranked), default=0)
            rows.append({"name": c, "tags": list(tg), "hero": hero, "trait": trait, "fit": round(score, 2)})
        out.append({"stage": r["stage"], "cards": sorted(rows, key=lambda x: -x["fit"]), "picked": r.get("picked"),
                    "rerolled_away": [n for n in r.get("offered", []) if n not in cards]})
    return out


if __name__ == "__main__":
    import plans as P
    static = load_set(sys.argv[1])
    cat = catalog(sys.argv[1])
    ps = P.build_plans(static)
    if len(sys.argv) < 3:
        for p in (P.focus(static) or [p for p in ps if "avg_place" in p][:8]):
            strong = strong_augments(static, p, cat)
            print(f"{p['id']:28} {archetype(p, static):7} setup: {SETUP[archetype(p, static)]}"
                  + (f"   strong: {', '.join(strong[:6])}" if strong else ""))
        sys.exit()
    states = [json.loads(x) for x in Path(sys.argv[2]).read_text().splitlines() if x.strip()]
    by_stage = {s["stage"]: s for s in states}
    for a in states[-1].get("augment_offers", []):
        st = by_stage.get(a["stage"]) or states[-1]
        line = [p for p, _ in P.match(static, st, ps)[:2]]              # the lines the board was on then
        r = review_offers(static, {"augment_offers": [a]}, line, cat)[0]
        print(f"{r['stage']}  line: {', '.join(p['id'] for p in line)} ({', '.join(archetype(p, static) for p in line)})")
        for c in r["cards"]:
            extra = f" hero:{c['hero']}" if c["hero"] else f" trait:{c['trait']}" if c["trait"] else ""
            took = "  <- taken" if c["name"] == r["picked"] else ""
            print(f"     {c['fit']:.2f}  {c['name']:24} {'/'.join(LABEL.get(t, t) for t in c['tags'])}{extra}{took}")
        if r["rerolled_away"]:
            print(f"     rerolled away: {', '.join(r['rerolled_away'])}")
