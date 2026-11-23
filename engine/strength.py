"""Relative board strength: a score where higher means "beats lower-scored boards more often than not".

    python3 -I engine/strength.py fit          # learn weights from cached matches, report held-out accuracy
    python3 -I engine/strength.py score TFTSet19 "Xayah:2:3,Lucian:2,Kayn,..."   # unit:stars:items

Features are set-agnostic (gold value, stars, trait tiers reached, items), computed from our own static
data, so weights learned on Set 17/18 lobbies apply to Set 19 boards. Fit is pairwise within a lobby
(Bradley-Terry): P(board i beats board j) = sigmoid(w . (x_i - x_j)), using final placements.
Caveat: final boards also encode survival time (players out early had less time to build), so this
measures "end-state board quality", not a same-round fight; calibrate on recordings later.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from unlocks import load_set  # noqa: E402

WEIGHTS = ROOT / "data" / "strength_weights.json"
QUALITY = ["gold_value", "units", "carry_stars", "items", "carry_quality", "three_stars"]   # learned
FEATURES = QUALITY + ["synergy"]
# Synergy prior (hand-set, not fitted): on traits needing several units, tier k is worth k, so reaching
# tier k scores 1+2+..+k. Deep verticals beat tier-1 splashes, as trait bonuses grow by tier. Solo traits
# score 0 (a unit's own power is in its cost). 160 final boards proved too few and too survival-confounded
# to learn trait values: fitted, they rewarded solo traits and penalised verticals.


def trait_tiers(static, board):
    """{trait: (tier reached, number of tiers)} for traits active on this board (unique units only)."""
    units = {u["name"]: u for u in static["units"]}
    best = {}
    for b in board:
        if b["unit"] in units and b.get("stars", 1) >= best.get(b["unit"], 0):
            best[b["unit"]] = b.get("stars", 1)
    out = {}
    for t in static["traits"]:
        bps = t.get("breakpoints") or []
        if not bps:
            continue
        members = [n for n in best if t["name"] in units[n]["traits"]]
        n = sum(best[m] for m in members) if t.get("counts") == "stars" else len(members)
        tier = sum(n >= b for b in bps)
        if tier:
            out[t["name"]] = (tier, len(bps))
    return out


def features(static, board):
    """board: [{"unit", "stars", "items": int or list}] -> feature dict."""
    units = {u["name"]: u for u in static["units"]}
    b = [x for x in board if x["unit"] in units]
    cost = lambda x: min(units[x["unit"]]["cost"], 5)        # noqa: E731  (7-costs priced as 5 + their own power)
    items = lambda x: x["items"] if isinstance(x.get("items"), int) else len(x.get("items") or [])  # noqa: E731
    stars = lambda x: x.get("stars", 1)                      # noqa: E731
    top = sorted(b, key=lambda x: -cost(x))[:3]
    carry = max(b, key=lambda x: (items(x), cost(x)), default=None)
    tiers = trait_tiers(static, b)
    return {
        "gold_value": sum(units[x["unit"]]["cost"] * 3 ** (stars(x) - 1) for x in b) / 10,
        "units": len(b),
        "carry_stars": sum(stars(x) for x in top) / max(len(top), 1),
        # solo traits (one breakpoint) are kept apart so they can't pass for synergy
        "shared_tiers": sum(t for t, n in tiers.values() if n > 1),
        "solo_traits": sum(1 for t, n in tiers.values() if n == 1),
        "vertical": max((t / n for t, n in tiers.values() if n > 1), default=0),
        "synergy": sum(t * (t + 1) / 2 for t, n in tiers.values() if n > 1),
        # per-trait depth (tier reached / tiers): set-specific, for learning which traits are actually strong
        **{f"T:{name}": t / n for name, (t, n) in tiers.items()},
        "items": sum(items(x) for x in b),
        "carry_quality": (items(carry) / 3) * stars(carry) * cost(carry) / 5 if carry else 0,
        "three_stars": sum(stars(x) == 3 for x in b),
    }


def load_lobbies():
    """[(set_number, [(placement, last_round, features)])] from every stored ranked match: crawled
    (data/crawl/**, gzip) and the user's own (data/matches/)."""
    sys.path.insert(0, str(ROOT / "tools"))
    from crawl import read_matches
    statics, lobbies, seen = {}, [], set()
    for m in read_matches(ROOT / "data"):
        info = m["info"]
        mid = m.get("id") or m.get("metadata", {}).get("match_id")
        if mid in seen or info.get("queue_id") != 1100:
            continue
        seen.add(mid)
        n = info["tft_set_number"]
        if n not in statics:
            from unlocks import unit_resolver
            try:
                s = load_set(f"TFTSet{n}")                  # generated or hand-made static data
                statics[n] = (s, unit_resolver(s))
            except FileNotFoundError:
                statics[n] = None
        if statics[n] is None:
            continue
        s, name = statics[n]
        rows = []
        for p in info["participants"]:
            board = [{"unit": name(u["character_id"]), "stars": u["tier"], "items": len(u.get("itemNames", []))}
                     for u in p["units"] if name(u["character_id"])]
            rows.append((p["placement"], p["last_round"], features(s, board)))
        lobbies.append((n, rows))
    return lobbies


def pairs(rows, keys):
    for pi, ri, xi in rows:
        for pj, rj, xj in rows:
            if pi < pj:
                yield [xi[k] - xj[k] for k in keys], ri == rj


def solve(A, b):
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def fit(lobbies, keys=FEATURES, l2=0.05, iters=25):
    """Pairwise logistic regression by Newton's method on standardised features (converges in ~10 steps)."""
    X = [d for _, rows in lobbies for d, _ in pairs(rows, keys)]
    k = len(keys)
    scale = [max(1e-9, math.sqrt(sum(x[i] ** 2 for x in X) / len(X))) for i in range(k)]
    X = [[x[i] / scale[i] for i in range(k)] for x in X]
    w, n = [0.0] * k, len(X)
    for _ in range(iters):                                  # every pair is "i beat j": label 1
        g = [l2 * wi for wi in w]
        H = [[l2 if i == j else 0.0 for j in range(k)] for i in range(k)]
        for x in X:
            z = sum(a * b for a, b in zip(w, x))
            p = 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))
            for i in range(k):
                g[i] -= (1 - p) * x[i] / n
                for j in range(i, k):
                    H[i][j] += p * (1 - p) * x[i] * x[j] / n
        for i in range(k):
            for j in range(i):
                H[i][j] = H[j][i]
        step = solve(H, g)
        w = [wi - s for wi, s in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return {key: wi / s for key, wi, s in zip(keys, w, scale)}


def score(weights, feats):
    return sum(weights[k] * feats[k] for k in weights)


def evaluate(lobbies, keys, folds=5):
    """Held out by lobby (leave-one-out when there are few lobbies, else k folds): share of within-lobby
    pairs ordered correctly, for all pairs and for same-round pairs (boards alive at the same moment)."""
    folds = len(lobbies) if len(lobbies) <= 30 else folds
    right = total = right_same = total_same = 0
    for f in range(folds):
        test = [lb for i, lb in enumerate(lobbies) if i % folds == f]
        w = fit([lb for i, lb in enumerate(lobbies) if i % folds != f], keys)
        for _, rows in test:
            for d, same in pairs(rows, keys):
                ok = sum(w[k] * v for k, v in zip(keys, d)) > 0
                right, total = right + ok, total + 1
                if same:
                    right_same, total_same = right_same + ok, total_same + 1
    return right / total, (right_same / total_same if total_same else None), total, total_same


BUDGET = {7: 18, 8: 24, 9: 32}     # ponytail: typical 1-star board cost by level; tune on recordings


def search(static, level, weights, restarts=60, seed=1, budget=None):
    """High-synergy boards of `level` units, all 1-star, gold value <= budget. Hill climbing with restarts.
    Respects level gates and exclusive unlocks. Returns [(score, board names, traits, unlocks needed)]."""
    import random
    rng = random.Random(seed)
    gates = {u["unit"]: (u.get("min_level") or 0, set(u.get("excludes", []))) for u in static["unlocks"]}
    pool = [u["name"] for u in static["units"]
            if gates.get(u["name"], (0,))[0] <= level and (u["cost"] <= 5 or level >= 9)]
    cost = {u["name"]: u["cost"] for u in static["units"]}
    budget = budget or BUDGET.get(level, 24)

    def ok(b):
        return sum(cost[n] for n in b) <= budget and not any(gates.get(n, (0, set()))[1] & set(b) for n in b)

    own = ROOT / "data" / f"trait_weights_{static['set']}.json"                       # from our crawl
    comp = ROOT / "data" / "manual" / f"{static['set']}.metatft_trait_weights.json"   # from PBE comp averages
    learned = own if own.exists() else comp
    tw = json.loads(learned.read_text()) if learned.exists() else None

    def val(b):
        # with learned per-trait weights for this set (strength.py traits): value of the traits reached;
        # without them: the generic synergy prior (tier k worth k), which does NOT predict winning
        f = features(static, [{"unit": n} for n in b])
        trait_value = sum(tw.get(k[2:], 0) * v for k, v in f.items() if k.startswith("T:")) if tw else f["synergy"]
        clash = sum(v for k, v in f.items() if k[2:] in banned and k.startswith("T:"))     # explore other traits
        return trait_value + 0.1 * f["gold_value"] - 2 * clash if ok(b) else -1e9

    seen, out = set(), []
    banned = set()                                   # main traits already found: push later climbs elsewhere
    for r in range(restarts):
        if r and r % 6 == 0 and out:
            best = max(out, key=lambda o: o[0])
            banned.add(max(((tr, k / n) for tr, (k, n) in best[2].items() if n > 1), key=lambda x: x[1], default=(None,))[0])
        b = rng.sample(pool, level)
        while not ok(b):
            b = rng.sample(sorted(pool, key=lambda n: cost[n])[:40], level)
        cur, improved = val(b), True
        while improved:
            improved = False
            for i in rng.sample(range(level), level):
                for n in rng.sample(pool, len(pool)):
                    if n in b:
                        continue
                    nb = b[:i] + [n] + b[i + 1:]
                    v = val(nb)
                    if v > cur + 1e-9:
                        b, cur, improved = nb, v, True
                        break
        key = frozenset(b)
        if key not in seen:
            seen.add(key)
            out.append((cur, sorted(b, key=lambda n: -cost[n]), trait_tiers(static, [{"unit": n} for n in b]),
                        sorted(n for n in b if n in gates)))
    def main(o):
        return max(((tr, k / n) for tr, (k, n) in o[2].items() if n > 1), key=lambda x: x[1], default=("-",))[0]
    out = [(val(o[1]) if not banned else o[0], *o[1:]) for o in out]
    banned.clear()                                                 # rescore without the exploration penalty
    out = sorted(((val(o[1]), *o[1:]) for o in out), key=lambda x: -x[0])
    distinct, mains = [], set()
    for o in out:                                   # best board per main trait, no near-duplicates
        if main(o) not in mains and all(len(set(o[1]) & set(d[1])) < 6 for d in distinct):
            distinct.append(o)
            mains.add(main(o))
    return distinct


if __name__ == "__main__":
    if sys.argv[1:2] == ["fit"]:
        lob = load_lobbies()
        print(f"{len(lob)} lobbies, {sum(len(r) for _, r in lob)} boards")
        noitem = lambda ks: [k for k in ks if "item" not in k and k != "carry_quality"]   # noqa: E731
        traits = ["shared_tiers", "solo_traits", "vertical"]
        for name, keys in [("gold value only", ["gold_value"]), ("synergy prior only", ["synergy"]),
                           ("quality, no items", noitem(QUALITY)), ("quality+synergy, no items", noitem(FEATURES)),
                           ("quality", QUALITY), ("quality + synergy", FEATURES),
                           ("quality + learned traits", QUALITY + traits)]:
            acc, same, n, ns = evaluate(lob, keys)
            print(f"  {name:<27} held-out pair accuracy {acc:.1%} ({n} pairs); same-round pairs {same:.0%} ({ns})")
        lt = fit(lob, QUALITY + traits)
        print("learned trait weights (per unit of feature):", {k: round(lt[k], 3) for k in traits})
        w = fit(lob)
        WEIGHTS.write_text(json.dumps({"weights": w, "no_items": fit(lob, noitem(FEATURES)),
                                       "trained_on": f"{len(lob)} lobbies (Set 17/18 ranked, cached)"}, indent=1))
        print("weights:", {k: round(v, 3) for k, v in w.items()})
    elif sys.argv[1:2] == ["traits"]:
        # per-trait value within one set: quality + one depth feature per trait, held out on 20% of lobbies
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 18
        lob = [lb for lb in load_lobbies() if lb[0] == n]
        if len(lob) < 25:
            sys.exit(f"only {len(lob)} stored ranked Set {n} lobbies; crawl more first (tools/crawl.py --set {n})")
        tkeys = sorted({k for _, rows in lob for _, _, f in rows for k in f if k.startswith("T:")})
        common = [k for k in tkeys if sum(1 for _, rows in lob for _, _, f in rows if f.get(k)) >= 40]
        for _, rows in lob:
            for _, _, f in rows:
                for k in common:
                    f.setdefault(k, 0.0)
        keys = QUALITY + common
        test, train = lob[::5], [lb for i, lb in enumerate(lob) if i % 5]
        held = lambda w, ks: sum(sum(w[k] * v for k, v in zip(ks, d)) > 0 for _, r in test for d, _ in pairs(r, ks)) \
            / sum(1 for _, r in test for _ in pairs(r, ks))   # noqa: E731
        print(f"Set {n}: {len(lob)} lobbies, {len(common)} traits seen on 40+ boards")
        print(f"  held-out pairs: quality {held(fit(train, QUALITY), QUALITY):.1%}, "
              f"quality + per-trait {held(fit(train, keys), keys):.1%}")
        w = fit(lob, keys)
        tw = sorted(((w[k], k[2:]) for k in common), reverse=True)
        print("  strongest traits (weight per full trait depth):", ", ".join(f"{name} {v:+.2f}" for v, name in tw[:8]))
        print("  weakest traits:", ", ".join(f"{name} {v:+.2f}" for v, name in tw[-6:]))
        out = ROOT / "data" / f"trait_weights_TFTSet{n}.json"
        out.write_text(json.dumps({name: round(v, 4) for v, name in tw}, indent=1))
        print(f"  -> {out.relative_to(ROOT)}")
    elif sys.argv[1:2] == ["comp-traits"]:
        # Set 19 before our own crawl: trait values from MetaTFT's PBE comp averages (private, gitignored).
        # Weighted ridge regression of (4.5 - avg place) on trait depth; 43 comps vs ~40 traits -> rough prior.
        s = load_set(sys.argv[2])
        src = ROOT / "data" / "manual" / f"{sys.argv[2]}.metatft_pbe.json"
        comps = json.loads(src.read_text())["comps"]
        F = [features(s, [{"unit": u} for u in c["units"]]) for c in comps]
        # solo traits (Teemo's Hype Man, Malzahar's Composer...) always come with their band in these comps,
        # so they'd share the band's credit and the search would sprinkle those units everywhere: bands only
        solo = {x["name"] for x in s["traits"] if (x.get("breakpoints") or [0]) == [1]}
        keys = sorted({k for f in F for k in f if k.startswith("T:") and k[2:] not in solo})
        X = [[f.get(k, 0.0) for k in keys] for f in F]
        y = [4.5 - c["avg_place"] for c in comps]
        wt = [c["pick_rate"] for c in comps]
        lam = 1.0
        A = [[sum(wt[r] * X[r][i] * X[r][j] for r in range(len(X))) + (lam if i == j else 0) for j in range(len(keys))]
             for i in range(len(keys))]
        b = [sum(wt[r] * X[r][i] * y[r] for r in range(len(X))) for i in range(len(keys))]
        w = solve(A, b)
        tw = sorted(((v, k[2:]) for v, k in zip(w, keys)), reverse=True)
        out = ROOT / "data" / "manual" / f"{sys.argv[2]}.metatft_trait_weights.json"
        out.write_text(json.dumps({name: round(v, 4) for v, name in tw}, indent=1))
        print("strongest:", ", ".join(f"{n} {v:+.2f}" for v, n in tw[:8]))
        print("weakest:  ", ", ".join(f"{n} {v:+.2f}" for v, n in tw[-6:]))
        print(f"-> {out.relative_to(ROOT)} (derived from MetaTFT data: private)")
    elif sys.argv[1:2] == ["search"]:
        s, level = load_set(sys.argv[2]), int(sys.argv[3])
        found = search(s, level, None)[:8]
        if "--save" in sys.argv:
            private = not (ROOT / "data" / f"trait_weights_{sys.argv[2]}.json").exists() and \
                (ROOT / "data" / "manual" / f"{sys.argv[2]}.metatft_trait_weights.json").exists()
            # boards found with MetaTFT-derived weights are derived from their data: keep them private too
            out = ROOT / "data" / "manual" / f"{sys.argv[2]}.{'metatft_' if private else ''}synergy_plans.json"
            plans = []
            for sc, b, traits, need in found:
                main = max(((k, n, tr) for tr, (k, n) in traits.items() if n > 1), key=lambda x: (x[0] / x[1], x[0]))
                tb = next(x for x in s["traits"] if x["name"] == main[2])
                second = sorted((tr for tr, (k, n) in traits.items() if n > 1 and tr != main[2]),
                                key=lambda tr: -traits[tr][0])[:1]
                plans.append({"id": f"{main[2]}-{tb['breakpoints'][main[0] - 1]}" + (f"+{second[0]}" if second else ""),
                              "trait": main[2], "target": tb["breakpoints"][main[0] - 1], "counts": tb.get("counts", "units"),
                              "core": b, "unlocks": need, "carries": b[:2], "level": level, "synergy": sc,
                              "source": "synergy search (structural prior, no strength data)"})
            seen = {}
            for pl in plans:                                   # same trait pair twice -> -b, -c ...
                n = seen[pl["id"]] = seen.get(pl["id"], 0) + 1
                if n > 1:
                    pl["id"] += "-" + "abcdefgh"[n - 1]
            out.write_text(json.dumps(plans, indent=1, ensure_ascii=False))
            print(f"saved {len(plans)} plans -> {out.relative_to(ROOT)}")
        for sc, b, traits, need in found:
            active = ", ".join(f"{t} {k}/{n}" for t, (k, n) in sorted(traits.items(), key=lambda x: -x[1][0]) if n > 1)
            print(f"{sc:6.2f}  {', '.join(b)}\n        traits: {active}\n        unlocks: {', '.join(need) or '-'}")
    elif sys.argv[1:2] == ["score"]:
        s = load_set(sys.argv[2])
        board = []
        for tok in sys.argv[3].split(","):
            name, *rest = tok.split(":")
            board.append({"unit": name.strip(), "stars": int(rest[0]) if rest else 1, "items": int(rest[1]) if len(rest) > 1 else 0})
        f = features(s, board)
        w = json.loads(WEIGHTS.read_text())["weights"]
        print(json.dumps(f), "\nscore", round(score(w, f), 2), "| traits", trait_tiers(s, board))
