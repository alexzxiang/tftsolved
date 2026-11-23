"""Plans: target boards and the unlocks they need. Which plan a game is heading for, and its reach.

    python3 -I engine/plans.py TFTSet19                       # list the plans
    python3 -I engine/plans.py TFTSet19 state.json 5-1        # plans this state fits, with reach by 5-1

Before live match data exists (Set 19 launches 2026-12-02) plans are STRUCTURAL, per docs/04: one per
band (origin with 4+ members), its members up to the highest breakpoint a level 8-9 board holds, capstone
unlocks always included. They say nothing about strength; after launch, clusters of real final boards
replace them (docs/06) and add placement values.
"""
import json
import sys
from math import ceil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reach import reach, shop_reach   # noqa: E402
from unlocks import Board, load_set    # noqa: E402

MAX_BOARD = 9
CORE_UNITS = 6         # PBE comps: units a plan needs; the rest of the listed board is flex


def build_plans(static):
    units = static["units"]
    locked = {u["unit"] for u in static["unlocks"]}
    gates = {u["unit"]: u.get("min_level") for u in static["unlocks"]}
    plans = []
    for t in static["traits"]:
        if t.get("kind") != "origin":
            continue
        members = sorted((u for u in units if t["name"] in u["traits"]),
                         key=lambda u: (u["name"] not in locked, -u["cost"], u["name"]))   # capstones first
        if len(members) < 4:
            continue
        bps = t.get("breakpoints") or [len(members)]
        stars = t.get("counts") == "stars"
        fits = [b for b in bps if (ceil(b / 2) if stars else b) <= min(len(members), MAX_BOARD - 1)]
        target = max(fits) if fits else bps[0]
        size = ceil(target / 2) if stars else min(target, len(members))
        core = members[:size]
        plans.append({
            "id": f"{t['name']}-{target}", "trait": t["name"], "target": target, "counts": t.get("counts", "units"),
            "core": [u["name"] for u in core],
            "unlocks": [u["name"] for u in core if u["name"] in locked],
            "carries": [u["name"] for u in sorted(core, key=lambda u: -u["cost"])[:2]],   # heuristic: priciest
            # level must cover the board size and every unlock's level gate (Smeech needs 9)
            "level": max([8, min(MAX_BOARD, len(core))] + [gates.get(u["name"]) or 0 for u in core]),
            "source": "structural",
        })
    gates = {u["unit"]: u.get("min_level") or 0 for u in static["unlocks"]}
    for name in ("synergy_plans", "metatft_synergy_plans"):    # boards from engine/strength.py search --save
        extra = Path(__file__).resolve().parent.parent / "data" / "manual" / f"{static['set']}.{name}.json"
        if extra.exists():
            for p in json.loads(extra.read_text()):
                unl = [u for u in p["core"] if u in gates]      # recomputed: data corrections flow through
                plans.append(dict(p, id=("PBE-weighted " if "metatft" in name else "") + p["id"], unlocks=unl,
                                  level=max([p["level"]] + [gates.get(u, 0) for u in unl])))
    plans += pbe_plans(static)
    return plans


def pbe_comps(static):
    """MetaTFT PBE comp averages, if saved (private, gitignored): [] otherwise. Names mapped to the roster:
    Akali is an unlock fork here ("Akali (K/DA)" / "Akali (True Damage)", by the comp's trait), "Nunu" is
    Nunu & Willump; summons on early boards (Beach Pop's instruments) aren't shop units and are dropped."""
    f = Path(__file__).resolve().parent.parent / "data" / "manual" / f"{static['set']}.metatft_pbe.json"
    if not f.exists():
        return []
    roster = {u["name"] for u in static["units"]}
    out = []
    extra = f.parent / f"{static['set']}.lolchess_comps.json"         # tools/import_lolchess.py: variants + new comps
    rows = json.loads(f.read_text())["comps"] + (json.loads(extra.read_text())["comps"] if extra.exists() else [])
    for c in rows:
        def name(u):
            if u == "Akali":
                return "Akali (True Damage)" if "True Damage" in c["name"] else "Akali (K/DA)"
            return {"Nunu": "Nunu & Willump"}.get(u, u)
        fix = lambda us: [name(u) for u in us if name(u) in roster]           # noqa: E731
        out.append(dict(c, units=fix(c["units"]),
                        board=[dict(b, unit=name(b["unit"])) for b in c.get("board", []) if name(b["unit"]) in roster],
                        early=[dict(e, units=fix(e["units"])) for e in c.get("early", [])]))
    return out


def pbe_plans(static):
    """Real comps with placement data: the plans that say how strong a board actually is."""
    from strength import trait_tiers
    locked = {u["unit"]: u.get("min_level") or 0 for u in static["unlocks"]}
    traits = {t["name"]: t for t in static["traits"]}
    out = []
    for c in pbe_comps(static):
        tiers = trait_tiers(static, [{"unit": u} for u in c["units"]])
        main = max(((tr, k, n) for tr, (k, n) in tiers.items() if n > 1), key=lambda x: (x[1] / x[2], x[1]),
                   default=(None, 0, 1))
        bps = (traits.get(main[0]) or {}).get("breakpoints") or [1]
        roll = c["style"].split()[-1]
        out.append({
            "id": f"PBE {c['name']}", "trait": main[0], "target": bps[main[1] - 1] if main[0] else 1,
            # MetaTFT lists defining units first; the tail is flex slots a player fills with what they hit
            "counts": (traits.get(main[0]) or {}).get("counts", "units"), "core": c["units"][:CORE_UNITS],
            "flex": c["units"][CORE_UNITS:],
            "unlocks": [u for u in c["units"][:CORE_UNITS] if u in locked],
            # carries: the units the page lists items for (else the first two); their items are Set 19 best-in-slot
            "carries": [b["unit"] for b in c.get("board", []) if b["items"]][:3] or c["units"][:2],
            "items": {b["unit"]: b["items"] for b in c.get("board", []) if b["items"]},
            "stars": {b["unit"]: b["stars"] for b in c.get("board", [])},
            # the most common board per level of players who ended in this comp: how the line starts
            "early": {e["level"]: e["units"] for e in c.get("early", [])},
            "level_by": {x["level"]: x["stage"] for x in c.get("levelling", []) if x["stage"]},
            "level": max([8, min(MAX_BOARD, len(c["units"]))] + [locked.get(u, 0) for u in c["units"]]),
            "roll_level": int(roll) if roll.isdigit() else None,
            "style": c["style"],
            "avg_place": c["avg_place"], "win_rate": c["win_rate"], "pick_rate": c["pick_rate"], "tier": c["tier"],
            "source": "MetaTFT PBE comp averages (private)"})
    return out


def unlock_payoff(static):
    """unlock -> (pick-weighted avg place of PBE comps that field it, number of comps). Lower is better."""
    out = {}
    for u in static["unlocks"]:
        cs = [c for c in pbe_comps(static) if u["unit"] in c["units"]]
        if cs:
            w = sum(c["pick_rate"] for c in cs) or 1
            out[u["unit"]] = (round(sum(c["avg_place"] * c["pick_rate"] for c in cs) / w, 2), len(cs))
    return out


EARLY_LEVELS = 7        # up to this level a line is also judged by its early boards (MetaTFT: levels 4-7)


def match(static, state, plans):
    """[(plan, progress 0-1)] best first. Progress: band count vs target (trait panel or owned units),
    the share of core units held (benched ones count half), or, while the level is EARLY_LEVELS or below,
    the share of the line's early board for that level that you hold (endgame boards and the boards that
    lead to them differ: K/DA players open Neeko/Gragas/Evelynn), whichever is highest."""
    b = Board(static, state)
    level = state.get("level") or 0
    held = set(b.fielded) | b.bench
    out = []
    for p in plans:
        early = (p.get("early") or {}).get(min(max(level, 4), EARLY_LEVELS)) if level <= EARLY_LEVELS else None
        early_fit = len(held & set(early)) / len(early) if early else 0
        # a one-unit trait (target 1, e.g. R&B from Rell) says nothing about the line: core units only
        band = b.count(p["trait"]) / p["target"] if (p["target"] or 0) > 1 else 0
        # fielded core units count fully, benched ones half (the purchase ledger over-counts the bench)
        core = (len(set(b.fielded) & set(p["core"])) + 0.5 * len(b.bench & set(p["core"]))) / len(p["core"])
        out.append((p, round(min(1.0, max(band, core, early_fit)), 2)))
    return sorted(out, key=lambda x: (-x[1], x[0].get("avg_place", 9)))   # equal fit: the stronger plan first


FOCUS = Path(__file__).resolve().parent.parent / "data" / "focus.json"


def focus(static):
    """The comps the player chose to focus on (pre-game, static: allowed in game by Riot's rules)."""
    if not FOCUS.exists():
        return []
    ids = json.loads(FOCUS.read_text()).get(static["set"], [])
    return [p for p in build_plans(static) if p["id"] in ids]


def set_focus(static, ids):
    plans = {p["id"]: p for p in build_plans(static)}
    bad = [i for i in ids if i not in plans]
    if bad:
        raise SystemExit(f"unknown plan id(s): {bad}; see --suggest")
    data = json.loads(FOCUS.read_text()) if FOCUS.exists() else {}
    data[static["set"]] = ids
    FOCUS.write_text(json.dumps(data, indent=1))


def targets(static, state, min_fit=0.4):
    """Unlocks to chase: those of the focused comps if the player picked some, else of plans the board fits."""
    chosen = focus(static)
    if chosen:
        return sorted({u for p in chosen for u in p["unlocks"]})
    return sorted({u for p, fit in match(static, state, build_plans(static)) if fit >= min_fit for u in p["unlocks"]})


def plan_reach(static, state, plan, by):
    """P(own every core unit and have its unlocks) by `by`, per policy. Unlock chances multiply in
    (treated as independent); an unknown one is reported, not assumed."""
    b = Board(static, state)
    # what you still need to find: inferred board units the ledger never saw are guesses, not owned copies
    owned = {n for n, u in b.fielded.items() if u.get("owned", True)} | b.bench | set(state.get("unlocked", []))
    need = [u for u in plan["core"] if u not in owned and u not in plan["unlocks"]]
    shop = shop_reach(static, state, {u: 1 for u in need}, {}, lambda c: all(c.get(u, 0) >= 1 for u in need), by) \
        if need else {"standard": 1.0, "roll_now": 1.0}
    rows = {r["unit"]: r for r in reach(static, state, by, only=set(plan["unlocks"]) - owned)}
    unknown, out = [], dict(shop)
    for name, r in rows.items():
        p = r["p"]
        if p is None:
            unknown.append(name)
            continue
        for k in out:
            out[k] *= p[k] if isinstance(p, dict) else p
    return {"p": out, "missing_units": need, "unlocks": {n: (r["status"], r["p"]) for n, r in rows.items()},
            "unknown": unknown, "upper_bound": bool(unknown)}   # unknown unlock chances: p is only a ceiling


FALLBACK_PLACE = 5.0   # ponytail: placement when a line isn't reached (roughly a failed line); fit on recordings


def expected_place(plan, r, policy="standard"):
    """P(reach) x the plan's PBE placement + the rest x a fallback. None without placement data.
    With unknown unlock chances, p is a ceiling, so this is a lower (optimistic) bound."""
    if "avg_place" not in plan:
        return None
    p = r["p"][policy]
    return p * plan["avg_place"] + (1 - p) * FALLBACK_PLACE


def fmt(p, upper=False):
    le = "<=" if upper else ""
    return f"{le}{p['standard']:.0%} / {le}{p['roll_now']:.0%}"


if __name__ == "__main__":
    static = load_set(sys.argv[1])
    plans = build_plans(static)
    if sys.argv[2:3] == ["--suggest"]:
        import augments as A
        cat = A.catalog(sys.argv[1])
        pbe = sorted((p for p in plans if "avg_place" in p), key=lambda p: p["avg_place"])
        if not pbe:
            print("no PBE placement data saved; showing structural plans")
        for p in (pbe or plans)[:12]:
            roll = f" roll@{p['roll_level']}" if p.get("roll_level") else ""
            place = f"{p['tier']} {p['avg_place']:.2f}{roll}" if "avg_place" in p else "structural"
            print(f"  {p['id']:<32}{place:<16} unlocks: {', '.join(p['unlocks']) or '-'}")
            kind = A.archetype(p, static)
            strong = A.strong_augments(static, p, cat)
            print(f"  {'':<32}{kind:<16} augments: {A.SETUP[kind]}"
                  + (f"; strong: {', '.join(strong[:5])}" if strong else ""))
        print('pick with: python3 -I engine/plans.py TFTSet19 --focus "PLAN ID" "PLAN ID"')
        sys.exit()
    if sys.argv[2:3] == ["--focus"]:
        if len(sys.argv) > 3:
            set_focus(static, sys.argv[3:])
        chosen = focus(static)
        print("focus:", ", ".join(p["id"] for p in chosen) or "none (alerts follow the plans your board fits)")
        sys.exit()
    if sys.argv[2:3] == ["--clear"]:
        set_focus(static, [])
        print("focus cleared")
        sys.exit()
    if sys.argv[2:3] == ["--unlocks"]:
        pay = unlock_payoff(static)
        print("unlock payoff: pick-weighted avg place of PBE comps that field it (lower is better)")
        for u in sorted(static["unlocks"], key=lambda u: pay.get(u["unit"], (9,))[0]):
            avg, n = pay.get(u["unit"], (None, 0))
            print(f"  {u['unit']:<22}" + (f"{avg:4.2f} in {n} comp(s)" if avg else "not in any listed comp"))
        sys.exit()
    if len(sys.argv) < 3:
        for p in plans:
            place = f" PBE {p['avg_place']:.2f}" if "avg_place" in p else ""
            print(f"{p['id']:<28} L{p['level']}{place}  core {', '.join(p['core'])}  | unlocks {', '.join(p['unlocks']) or '-'}")
        sys.exit()
    state, by = json.loads(Path(sys.argv[2]).read_text()), sys.argv[3]
    print(f"{'plan':<30}{'fit':>5}{'PBE':>6}{'exp':>6}  {'P by ' + by + ' (standard / roll now)':<34}blockers")
    shortlist = [(p, prog, plan_reach(static, state, p, by)) for p, prog in match(static, state, plans)[:8]]
    shortlist.sort(key=lambda x: expected_place(x[0], x[2]) or 9)        # best expected placement first
    for p, prog, r in shortlist[:6]:
        block = [f"{n} {s}" for n, (s, _) in r["unlocks"].items() if s not in ("READY", "UNLOCKED")]
        note = f"; unknown: {', '.join(r['unknown'])}" if r["unknown"] else ""
        place = f"{p['avg_place']:6.2f}" if "avg_place" in p else "     -"
        e = expected_place(p, r)
        exp = (f"{'<' if r['upper_bound'] else ' '}{e:5.2f}" if e else "     -")
        print(f"{p['id']:<30}{prog:>5.0%}{place}{exp}  {fmt(r['p'], r['upper_bound']):<34}{', '.join(block) or '-'}{note}")
