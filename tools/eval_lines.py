"""Test the line finder on boards sampled from MetaTFT's own comps, and fit what those boards can teach it.

  fit    'Where your units lead' (engine/linefinder.py line_odds): the naive-Bayes floor, opener likelihood and
         temperature alpha, by log-likelihood on held-out sampled boards; then tau, the split-conformal cut-off on
         odds / best odds that keeps the comp a board came from in the realistic set 90% of the time; beta, the
         weight of a unit's evidence by its cost (cost^beta).
         Writes data/models/odds_calibration.json.
  eval   Runs the line finder on sampled openers and later boards, random boards and component sets: how often the
         source comp stays realistic and gets suggested, how big the realistic set is by units held, how varied the
         suggestions are, and whether a comp's own components lift it.
  carry  A comp's main carry (2-star, two listed items) among four filler units: is its comp suggested? And every
         artifact and emblem alone: do the suggestions play its usual holders / run its trait?

Sampled board: a MetaTFT comp drawn by pick rate; either one of its openers (its listed core units at that level,
the other slots filled with units drawn from everyone's openers by how often they're opened with) or a later board
(a random part of its final board, half the time plus one unit from anyone's openers).

    python3 -I tools/eval_lines.py fit
    python3 -I tools/eval_lines.py eval [--n 300]
    python3 -I tools/eval_lines.py comps        # is each comp a reasonable line? (flags)
    python3 -I tools/eval_lines.py carry        # carry among filler; artifacts and emblems alone
"""
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import linefinder as L  # noqa: E402
import meta  # noqa: E402
from plans import pbe_comps  # noqa: E402
from unlocks import load_set  # noqa: E402

COVER = 0.9          # the realistic set keeps the source comp this often (conformal level)
STRETCH_COVER = 0.99  # stretch lines (padding a short list) come from the wider set that keeps it this often
OUT = ROOT / "data" / "models" / "odds_calibration.json"


def setup():
    static = load_set("TFTSet19")
    comps = pbe_comps(static)
    details = meta.details(static["set"])
    tables, generic = L.odds_tables(static, comps, details)
    return static, comps, details, tables, generic


def family(comps):
    """{comp name: its MetaTFT family} (lolchess variants belong to their parent)."""
    return {c["name"]: c.get("parent") or c["name"] for c in comps}


def draw(rng, weights):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def sample(comps, generic, rng, kind=None):
    """(source comp, [units], 'opener' | 'late')."""
    meta_comps = {c["name"]: c for c in comps if c.get("source") != "lolchess"}
    c = meta_comps[draw(rng, {n: c.get("pick_rate") or 0.001 for n, c in meta_comps.items()})]
    kind = kind or ("opener" if c.get("early") and rng.random() < 0.55 else "late")
    if kind == "opener" and c.get("early"):
        e = rng.choice(c["early"])
        units = list(dict.fromkeys(e["units"]))[:e["level"]]
        while len(units) < e["level"]:
            u = draw(rng, generic)
            if u not in units:
                units.append(u)
        return c["name"], units, "opener"
    board = [b["unit"] for b in c.get("board") or []] or list(c["units"])
    units = rng.sample(board, rng.randint(min(3, len(board)), len(board)))
    if rng.random() < 0.5:
        u = draw(rng, generic)
        if u not in units:
            units.append(u)
    return c["name"], units, "late"


def fit(n_train=4000, n_cal=2000, n_test=2000, seed=11):
    static, comps, details, tables, generic = setup()
    fam = family(comps)
    rng = random.Random(seed)
    data = [sample(comps, generic, rng) for _ in range(n_train + n_cal + n_test)]
    names = [c["name"] for c in comps]
    prior = [tables[n][0] for n in names]
    # per board, per comp: the units' (on its openers, base likelihood, cost)
    cost = {u["name"]: max(u["cost"], 1) for u in static["units"]}
    feats = [[[(*tables[n][1].get(u, (False, 0.0)), cost.get(u, 1)) for u in units] for n in names] for _, units, _ in data]
    truth = [fam[s] for s, _, _ in data]
    members = defaultdict(list)
    for i, n in enumerate(names):
        members[fam[n]].append(i)

    def scores(floor, op, beta=0.0):
        return [[sum(k ** beta * math.log(max(floor, op if o else 0.0, b)) for o, b, k in fc) for fc in f] for f in feats]

    def post(S, alpha, i):
        lp = [p + alpha * s for p, s in zip(prior, S[i])]
        top = max(lp)
        e = [math.exp(x - top) for x in lp]
        z = sum(e)
        return [x / z for x in e]

    def loglik(S, alpha, rows):
        return sum(math.log(max(1e-12, sum(post(S, alpha, i)[j] for j in members[truth[i]]))) for i in rows) / len(rows)
    train = range(n_train)
    best = None
    for floor in (0.05, 0.1, 0.2, 0.3, 0.4):
        for op in (0.5, 0.7, 0.9):
            for beta in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
                S = scores(floor, op, beta)
                for alpha in (0.3, 0.5, 0.7, 1.0, 1.4, 2.0, 2.5, 3.0):
                    ll = loglik(S, alpha, train)
                    if best is None or ll > best[0]:
                        best = (ll, floor, op, alpha, beta, S)
    ll, floor, op, alpha, beta, S = best
    # split conformal: score = family odds / best odds on the calibration boards; tau = the (1 - COVER) quantile
    cal = range(n_train, n_train + n_cal)
    ratios = []
    for i in cal:
        p = post(S, alpha, i)
        ratios.append(max(p[j] for j in members[truth[i]]) / max(p))
    ratios.sort()
    tau = ratios[max(0, math.floor((1 - COVER) * (len(ratios) + 1)) - 1)]
    tau_s = ratios[max(0, math.floor((1 - STRETCH_COVER) * (len(ratios) + 1)) - 1)]
    test = range(n_train + n_cal, len(data))
    hit1 = hit3 = cover = cover_s = 0
    size = defaultdict(list)
    for i in test:
        p = post(S, alpha, i)
        order = sorted(range(len(p)), key=lambda j: -p[j])
        fams = list(dict.fromkeys(fam[names[j]] for j in order))
        hit1 += fams[0] == truth[i]
        hit3 += truth[i] in fams[:3]
        top = max(p)
        cover += max(p[j] for j in members[truth[i]]) >= tau * top
        cover_s += max(p[j] for j in members[truth[i]]) >= tau_s * top
        size[min(len(data[i][1]), 9)].append(sum(x >= tau * top for x in p))
    n = len(test)
    base = loglik(scores(L.ODDS_FLOOR, L.ODDS_OPENER), 1.0, test)
    res = {"floor": floor, "opener": op, "alpha": alpha, "beta": beta, "tau": round(tau, 5), "cover": COVER,
           "tau_stretch": round(tau_s, 6), "cover_stretch": STRETCH_COVER,
           "test": {"boards": n, "loglik": round(loglik(S, alpha, test), 4), "loglik_before": round(base, 4),
                    "loglik_chance": round(math.log(1 / len(members)), 4),
                    "top1": round(hit1 / n, 3), "top3": round(hit3 / n, 3), "coverage": round(cover / n, 3),
                    "coverage_stretch": round(cover_s / n, 3),
                    "set_size_by_units": {k: round(sum(v) / len(v), 1) for k, v in sorted(size.items())}},
           "source": f"tools/eval_lines.py fit: {n_train} / {n_cal} / {n_test} boards sampled from MetaTFT openers and final "
                     f"boards (train / conformal calibration / test), seed {seed}"}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    return res


def shown_lines(res):
    """Suggested comps and the variants listed on their cards."""
    by = {r["name"]: r for r in res["comps"]}
    return [x for n in res["suggested"] for x in [n] + (by[n].get("variants") or [])]


def evaluate(n=300, seed=5):
    static, comps, details, tables, generic = setup()
    fam = family(comps)
    rng = random.Random(seed)
    roster = [u["name"] for u in static["units"] if u["cost"] <= 5]
    best4 = {c["name"] for c in sorted(comps, key=lambda c: c["avg_place"])[:4]}
    out = defaultdict(list)
    sugg = Counter()
    for _ in range(n):
        src, units, kind = sample(comps, generic, rng)
        res = L.find(static, {"units": [{"unit": u, "stars": 1} for u in units]})
        real = [r["name"] for r in res["comps"] if r.get("reachable")]
        out[f"{kind}: source realistic"].append(any(fam[x] == fam[src] for x in real))
        shown = shown_lines(res)
        out[f"{kind}: source suggested"].append(any(fam[x] == fam[src] for x in shown))
        out[f"{kind}: realistic set size ({min(len(units), 9)} units)"].append(len(real))
        out["suggestions = the 4 best comps overall"].append(set(res["suggested"]) == best4)
        sugg.update(res["suggested"])
    for k in (2, 4, 6, 8):
        for _ in range(n // 8):
            units = rng.sample(roster, k)
            res = L.find(static, {"units": [{"unit": u, "stars": 1} for u in units]})
            out[f"random {k} units: realistic set size"].append(sum(1 for r in res["comps"] if r.get("reachable")))
    # components: the source comp's carry best-in-slot recipes (two items' worth) vs none, same board
    _, build = L.recipes()
    recipe = {v: list(k) * (2 if len(k) == 1 else 1) for k, v in build.items()}
    plans = {p["id"][4:]: p for p in L.pbe_plans(static)}
    for _ in range(n // 3):
        src, units, _ = sample(comps, generic, rng, kind="opener")
        p = plans.get(src)
        holders = list((p or {}).get("items") or {})
        if not holders:
            continue
        parts = [x for i in p["items"][holders[0]][:2] for x in recipe.get(i, [])]
        inp = {"units": [{"unit": u, "stars": 1} for u in units]}
        b = L.find(static, dict(inp, items=parts))
        g = {r["name"]: r["gains"]["items"] for r in b["comps"]}
        out["components: source's item gain, share of comps it beats or ties"].append(
            sum(g[src] >= v for v in g.values()) / len(g))
        out["components: source suggested (with its components)"].append(any(fam[x] == fam[src] for x in shown_lines(b)))
    print(f"{n} sampled boards (seed {seed}); MetaTFT's 4 best comps: {sorted(best4)}")
    for k, v in out.items():
        x = sum(v) / len(v)
        print(f"  {k:62} {x:6.2f}" + ("" if all(isinstance(e, bool) for e in v) else "  (mean)") + f"  n={len(v)}")
    print(f"  distinct comps suggested: {len(sugg)} of {len(comps)}; most suggested: {sugg.most_common(6)}")
    return out, sugg


def carry_check(n=150, seed=9):
    """Boards a pro reads by their carry, and special items alone.
    carry among filler: a MetaTFT comp's main carry, 2-star and holding its two listed items, plus four random units
    from other comps -- is the comp's family suggested? Artifact alone: do the suggested comps play one of its usual
    holders (MetaTFT)? Emblem alone: do they run its trait (at their star levels)?"""
    static, comps, details, tables, generic = setup()
    fam = family(comps)
    rng = random.Random(seed)
    plans = {p["id"][4:]: p for p in L.pbe_plans(static)}
    roster = [u["name"] for u in static["units"] if u["cost"] <= 5]
    meta_comps = [c for c in comps if c.get("source") != "lolchess" and (plans.get(c["name"]) or {}).get("items")]
    out = defaultdict(list)
    for _ in range(n):
        c = rng.choice(meta_comps)
        p = plans[c["name"]]
        carry = L.main_carry_first(c["name"], list(p["items"]))[0]
        filler = rng.sample([u for u in roster if u not in c["units"]], 4)
        res = L.find(static, {"units": [{"unit": carry, "stars": 2, "items": p["items"][carry][:2]}] +
                                       [{"unit": u, "stars": 1} for u in filler]})
        out["carry among filler: source suggested"].append(any(fam[x] == fam[c["name"]] for x in shown_lines(res)))
        out["carry among filler: realistic set size"].append(sum(1 for r in res["comps"] if r.get("reachable")))
        out["carry among filler: first card carries it"].append(
            bool(res["suggested"]) and any(a["unit"] == carry for a in next(r for r in res["comps"] if r["name"] == res["suggested"][0])["anchors"]))
    for a, d in L.meta.artifacts(static["set"]).items():
        res = L.find(static, {"items": [a]})
        by = {r["name"]: r for r in res["comps"]}
        out["artifact alone: suggests something"].append(bool(res["suggested"]))
        if res["suggested"]:
            out["artifact alone: every suggestion plays a usual holder"].append(all(set(d["holders"]) & set(by[x]["units"]) for x in res["suggested"]))
    for e in L.catalog(static)["emblems"]:
        t = e[:-len(" Emblem")]
        res = L.find(static, {"items": [e]})
        by = {r["name"]: r for r in res["comps"]}
        runs = lambda x: t in L.trait_tiers(static, [{"unit": u, "stars": plans[x]["stars"].get(u, 1)} for u in by[x]["units"]])
        out["emblem alone: suggests something"].append(bool(res["suggested"]))
        if res["suggested"]:
            out["emblem alone: every suggestion runs its trait"].append(all(runs(x) for x in res["suggested"]))
    print(f"{n} carry boards (seed {seed}), every artifact and emblem alone")
    for k, v in out.items():
        print(f"  {k:62} {sum(v) / len(v):6.2f}" + ("" if all(isinstance(e, bool) for e in v) else "  (mean)") + f"  n={len(v)}")
    return out


def audit_comps():
    """Is each comp a reasonable line? Flags: a final board under 7 or over 10 units; the trait it's named after not
    active on its board; no itemised carry; no openers or levelling (pivot advice has nothing to go on); a main carry
    gated by a condition only the game tracks; a near-duplicate of another comp.
    Returns {comp: [flags]}."""
    static, comps, details, tables, generic = setup()
    from strength import trait_tiers
    locks = {u["unit"]: u for u in static["unlocks"]}
    flags = {}
    for c in comps:
        f = []
        n = len(c["units"])
        if not 7 <= n <= 10:
            f.append(f"final board has {n} units")
        tiers = trait_tiers(static, [{"unit": u, "stars": 1} for u in c["units"]])
        named = next((t for t in sorted(tiers, key=len, reverse=True) if c["name"].startswith(t)), None)
        trait_names = [t["name"] for t in static["traits"]]
        word = next((t for t in sorted(trait_names, key=len, reverse=True) if c["name"].startswith(t)), None)
        if word and tiers.get(word, (0, 0))[0] == 0:
            f.append(f"{word} not active on its final board")
        carries = [b for b in c.get("board") or [] if len(b.get("items") or []) >= 2]
        if not carries:
            f.append("no itemised carry listed")
        if not c.get("early"):
            f.append("no openers")
        if not c.get("levelling"):
            f.append("no levelling")
        main = L.main_carry_first(c["name"], [b["unit"] for b in carries] or c["units"][:1])[0]
        if main in locks and next(iter(locks[main]["when"])) in ("counter", "window", "streak", "all_of", "gold_end_combat"):
            f.append(f"main carry {main} unlocks by an in-game condition: {L.describe(locks[main]['when'])}")
        for o in comps:
            if o["name"] < c["name"]:
                j = len(set(c["units"]) & set(o["units"])) / len(set(c["units"]) | set(o["units"]))
                if j >= 0.8:
                    f.append(f"{round(j * 100)}% the same units as {o['name']}")
        flags[c["name"]] = f
    for name, f in sorted(flags.items(), key=lambda x: -len(x[1])):
        if f:
            print(f"  {name:34} " + "; ".join(f))
    print(f"{sum(1 for f in flags.values() if not f)} of {len(flags)} comps raise no flag")
    return flags


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if cmd == "fit":
        fit()
        L.odds_calibration.cache_clear()
    elif cmd == "comps":
        audit_comps()
    elif cmd == "carry":
        carry_check()
    else:
        evaluate(int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 300)
