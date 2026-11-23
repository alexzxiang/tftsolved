"""Back the line finder's estimates with data. Each check prints what it measured next to the prior it replaces.

  par      The typical board per level (engine/power.py PAR, a TFT-knowledge prior) measured from data:
           levels 8-10: Set 18 crawled final boards at that level that finished 4th-5th (the middle of the lobby);
           levels 4-7: MetaTFT's Set 19 openers weighted by pick rate (the boards a lobby actually fields), their
           missing slots filled with that level's typical 1-2 cost units. Writes "par" into the Set 19 model.
  needs    Are the per-comp "needs" engine/augvalue.py scales anchors by real? On Set 18 crawl clusters (comps grouped
           by their top trait), compare the marginal measure the model uses (MetaTFT-style averages) with a controlled
           one (least squares of placement within the cluster, holding board gold value and level fixed), and check
           split-half reliability of the marginal measure. A need that is unstable or unrelated to the controlled
           effect shouldn't scale anything.

  finetune The Set 19 board model refitted on MetaTFT's level 7-10 boards and their average places (see below).

    python3 -I tools/calibrate.py par
    python3 -I tools/calibrate.py needs
    python3 -I tools/calibrate.py finetune [--dry]
"""
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import board_model as bm  # noqa: E402
import power  # noqa: E402
from crawl import read_matches  # noqa: E402
from strength import trait_tiers  # noqa: E402
from unlocks import load_set, unit_resolver  # noqa: E402

MID_PLACES = (4, 5)
FILL = {4: (1, 1), 5: (1, 2), 6: (2, 1), 7: (2, 2)}    # (cost, stars) of an opener's unlisted slots at each level


def games(set_n=18):
    """[(match id, [participant dicts with resolved units])] for stored ranked lobbies of one set, deduplicated."""
    static = load_set(f"TFTSet{set_n}")
    name = unit_resolver(static)
    seen, out = set(), []
    for m in read_matches(ROOT / "data"):
        info = m["info"]
        mid = m.get("id") or m.get("metadata", {}).get("match_id")
        if info.get("tft_set_number") != set_n or info.get("queue_id") != 1100 or mid in seen:
            continue
        seen.add(mid)
        ps = []
        for p in info["participants"]:
            board = [(name(u["character_id"]), u["tier"], u.get("itemNames", [])) for u in p["units"] if name(u["character_id"])]
            ps.append(dict(p, board=board))
        out.append((mid, ps))
    return static, out


def kind_score(model, static, board):
    """A board's score with every unit, trait and item weight replaced by its kind's mean (a 'typical' board)."""
    f = bm.features(static, board, model["bis"])
    k, w = model["kinds"], model["weights"]
    return sum((w.get(x, 0.0) if x in bm.GLOBAL else k.get(bm.kind(static, x), 0.0)) * v for x, v in f.items())


def par():
    model18 = bm.load(18)
    static18, lobs = games(18)
    late = defaultdict(list)
    for _, ps in lobs:
        for p in ps:
            if p["placement"] in MID_PLACES and p["level"] >= 7:
                late[p["level"]].append(kind_score(model18, static18, p["board"]))
    static19 = load_set("TFTSet19")
    m19 = power._model(static19["set"])
    from plans import pbe_comps
    early = defaultdict(lambda: [0.0, 0.0])
    cost = {u["name"]: u["cost"] for u in static19["units"]}
    kinds = m19["kinds"]
    for c in pbe_comps(static19):
        for e in c.get("early", []):
            lv = e["level"]
            board = [{"unit": u, "stars": 2 if (cost.get(u, 9) == 1 and lv >= 5) or (cost.get(u, 9) == 2 and lv >= 6) else 1, "items": []}
                     for u in e["units"]]
            if not board or lv not in FILL:
                continue
            fc, fs = FILL[lv]
            n_items = power.PAR[lv][1]                     # completed items by that level: knowledge prior, not measured
            s = power.strength(static19, board, model=m19) + max(0, lv - len(board)) * kinds.get(f"u:cost{fc}*{fs}", 0.0) \
                + (kinds.get("it", 0.0) + 0.5 * kinds.get("bis", 0.0)) * n_items / 3
            early[lv][0] += c["pick_rate"] * s
            early[lv][1] += c["pick_rate"]
    measured = {lv: round(a / b, 3) for lv, (a, b) in early.items() if b}
    print("Set 18 crawl boards placing 4-5, by level:", {lv: (len(v), round(sum(v) / len(v), 2)) for lv, v in sorted(late.items())})
    measured.update({lv: round(sum(v) / len(v), 3) for lv, v in late.items() if len(v) >= 50 and lv >= 8})
    prior = {lv: round(power.par_score(dict(m19, par=None), lv), 3) for lv in range(3, 11)}
    print("level  prior (knowledge)  measured   source")
    for lv in range(3, 11):
        src = "MetaTFT openers, pick-weighted" if lv in early else f"Set 18 boards placing 4-5 (n={len(late.get(lv, []))})" if lv in late else "-"
        print(f"{lv:5}  {prior[lv]:17.2f}  {measured.get(lv, float('nan')):8.2f}   {src}")
    f = ROOT / "data" / "board_model_TFTSet19.json"
    m = json.loads(f.read_text())
    m["par"] = {str(k): v for k, v in measured.items()}
    m["par_source"] = "tools/calibrate.py par: levels 4-7 MetaTFT openers (pick-weighted, unlisted slots filled), 8-10 Set 18 boards placing 4th-5th"
    f.write_text(json.dumps(m))
    return measured, prior


def clusters(static, lobs, min_boards=150):
    """Boards grouped by their highest active trait tier (the comp they played)."""
    out = defaultdict(list)
    for _, ps in lobs:
        for p in ps:
            tiers = trait_tiers(static, [{"unit": u, "stars": s} for u, s, _ in p["board"]])
            if not tiers:
                continue
            top = max(tiers.items(), key=lambda x: (x[1][0] / x[1][1], x[1][0]))[0]
            out[top].append(p)
    return {k: v for k, v in out.items() if len(v) >= min_boards}


def gold_value(static, board):
    cost = {u["name"]: min(u["cost"], 5) for u in static["units"]}
    return sum(cost.get(u, 1) * 3 ** (s - 1) for u, s, _ in board)


def carry(board, static):
    cost = {u["name"]: u["cost"] for u in static["units"]}
    return max(board, key=lambda x: (len(x[2]), cost.get(x[0], 1)), default=None)


def ols(xs, ys):
    """Least squares with an intercept (normal equations, small k): coefficients for xs' columns."""
    k = len(xs[0]) + 1
    X = [[1.0] + list(x) for x in xs]
    A = [[sum(r[i] * r[j] for r in X) + (1e-6 if i == j else 0) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * y for r, y in zip(X, ys)) for i in range(k)]
    for i in range(k):                                     # Gaussian elimination
        piv = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[piv], b[i], b[piv] = A[piv], A[i], b[piv], b[i]
        for r in range(k):
            if r != i and A[i][i]:
                f = A[r][i] / A[i][i]
                A[r] = [a - f * c for a, c in zip(A[r], A[i])]
                b[r] -= f * b[i]
    return [b[i] / A[i][i] for i in range(1, k)]


def marginal_needs(static, ps, xp):
    """The model's measures (engine/augvalue.py), computed on Set 18 boards the way MetaTFT averages are."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    by_level = defaultdict(list)
    for p in ps:
        by_level[p["level"]].append(p["placement"])
    share = {L: len(v) / len(ps) for L, v in by_level.items()}
    avg = {L: sum(v) / len(v) for L, v in by_level.items() if len(v) >= 10}
    level = sum(share.get(L, 0) * max(0.0, avg[L] - avg[L + 1]) / xp[L] for L in (7, 8, 9) if L in avg and L + 1 in avg)
    star = defaultdict(list)
    for p in ps:
        c = carry(p["board"], static)
        if c and cost.get(c[0], 9) <= 3:
            star[c[1]].append(p["placement"])
    three = (sum(star[2]) / len(star[2]) - sum(star[3]) / len(star[3])) if len(star[2]) >= 10 and len(star[3]) >= 10 else None
    full, few = [], []
    for p in ps:
        c = carry(p["board"], static)
        (full if c and len(c[2]) >= 3 else few).append(p["placement"])
    items = (sum(few) / len(few) - sum(full) / len(full)) if len(full) >= 10 and len(few) >= 10 else None
    return {"level": level, "three": three, "items": items}


def controlled_needs(static, ps):
    """Within-cluster least squares of placement on [level 9+, carry 3-star, carry 3 items], holding gold value fixed."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    xs, ys = [], []
    for p in ps:
        c = carry(p["board"], static)
        xs.append([1.0 if p["level"] >= 9 else 0.0, 1.0 if c and c[1] >= 3 and cost.get(c[0], 9) <= 3 else 0.0,
                   1.0 if c and len(c[2]) >= 3 else 0.0, gold_value(static, p["board"]) / 30])
        ys.append(p["placement"])
    b = ols(xs, ys)
    return {"level": -b[0], "three": -b[1], "items": -b[2]}


def spearman(a, b):
    n = len(a)
    ra = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: a[i]))}
    rb = {i: r for r, i in enumerate(sorted(range(n), key=lambda i: b[i]))}
    return 1 - 6 * sum((ra[i] - rb[i]) ** 2 for i in range(n)) / (n * (n * n - 1)) if n > 2 else float("nan")


def needs():
    static, lobs = games(18)
    xp = {int(k): v for k, v in json.loads((ROOT / "data" / "constants.json").read_text())["TFTSet18"]["xp_to_next_level"].items()}
    cl = clusters(static, lobs)
    rows = {}
    for name, ps in cl.items():
        rng = random.Random(1)
        half = [p for p in ps if rng.random() < 0.5]
        rest = [p for p in ps if p not in half]
        rows[name] = (marginal_needs(static, ps, xp), controlled_needs(static, ps),
                      marginal_needs(static, half, xp), marginal_needs(static, rest, xp))
    print(f"{len(cl)} Set 18 comp clusters (by top trait) with 150+ boards, {sum(len(v) for v in cl.values())} boards")
    report = {}
    for k in ("level", "three", "items"):
        ok = [n for n, r in rows.items() if all(x[k] is not None for x in r)]
        m = [rows[n][0][k] for n in ok]
        c = [rows[n][1][k] for n in ok]
        h1 = [rows[n][2][k] for n in ok]
        h2 = [rows[n][3][k] for n in ok]
        report[k] = {"clusters": len(ok), "marginal_vs_controlled": round(spearman(m, c), 3), "split_half": round(spearman(h1, h2), 3)}
        print(f"  {k:6} need over {len(ok)} clusters: Spearman(marginal, controlled) {report[k]['marginal_vs_controlled']:+.2f}; "
              f"split-half reliability of the marginal {report[k]['split_half']:+.2f}")
    out = ROOT / "data" / "models" / "calibration_needs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"report": report, "clusters": {n: [r[0], r[1]] for n, r in rows.items()}}, indent=1))
    return report


if __name__ == "__main__" and (len(sys.argv) < 2 or sys.argv[1] in ("par", "needs")):
    {"par": par, "needs": needs}[sys.argv[1] if len(sys.argv) > 1 else "par"]()


# ---------------------------------------------------------------------------------------------------------------
# finetune: the Set 19 board model (Set 18 weights moved by MetaTFT averages) refitted on MetaTFT's Set 19 boards.
# Each comp's level 7-10 boards come with the average place of the players who ended on them. Model:
#     avg place = a_level + b x prior score + sum over groups of theta_group x count      (ridge on theta only)
# groups: one per trait tier step (per-unit offsets overfit: see group()). Ridge strength by 5-fold cross-validation
# over comps (whole comps held out), judged on Spearman within level and mean absolute error against the
# prior-only fit. Applied only if held-out comps improve; theta (places) is added to the model's weights at the
# Plackett-Luce rate below. (theta / b was used before: b, the prior score's slope on avg place, is tiny because the
# transferred score barely predicts it, so dividing by it inflated trait weights ~10x -- Indie, whose boards average
# 7.37, ended at +2.18 -- and Set 19's trait part spread 4x wider than Set 18's.)
STAR_LATE = 9
PL_PLACES_PER_SCORE = 7 / 4   # Plackett-Luce, 8 players: P(i above j) = sigmoid(s_i - s_j), so expected place
                              # = 1 + sum over the 7 others of sigmoid(s_j - s_i): -7 x 1/4 places per score unit


def variant_boards(static):
    from plans import pbe_comps
    import meta
    cost = {u["name"]: u["cost"] for u in static["units"]}
    comps = {c["name"]: c for c in pbe_comps(static)}
    out = []
    for name, det in meta.details(static["set"]).items():
        c = comps.get(name)
        if not c:
            continue
        target = {b["unit"]: b.get("stars", 1) for b in c.get("board", [])}
        items = {b["unit"]: b.get("items", []) for b in c.get("board", []) if b.get("items")}
        for lv, boards in det["levels"].items():
            for units, avg in boards:
                if len(set(units)) != len(units):
                    continue                                 # MetaTFT lists a duplicate when a unit is fielded twice
                board = []
                for u in units:
                    if lv >= STAR_LATE:
                        st = target.get(u, 2 if cost.get(u, 9) <= 3 else 1)
                    else:
                        st = min(target.get(u, 2), 2) if cost.get(u, 9) <= 3 else 1
                    board.append((u, st, items.get(u, []) if lv >= 8 else []))
                out.append((name, lv, board, avg))
    return out


def group(k):
    """Trait tier steps only. Held-out comps (5-fold, ridge 30), 2026-11-21: traits only MAE 0.691 / Spearman 0.453;
    traits + per-unit offsets 0.706 / 0.410; units only 0.737 / 0.359. Unit offsets credit a whole comp's strength
    to its members (they always appear together), so they're left out."""
    return k if k.startswith("t:") else None


def solve(X, y, ridge_idx, lam):
    k = len(X[0])
    A = [[0.0] * k for _ in range(k)]
    b = [0.0] * k
    for row, t in zip(X, y):
        nz = [(i, v) for i, v in enumerate(row) if v]
        for i, vi in nz:
            b[i] += vi * t
            for j, vj in nz:
                A[i][j] += vi * vj
    for i in ridge_idx:
        A[i][i] += lam
    for i in range(k):
        A[i][i] += 1e-9
    for i in range(k):
        piv = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[piv], b[i], b[piv] = A[piv], A[i], b[piv], b[i]
        if not A[i][i]:
            continue
        inv = 1 / A[i][i]
        for r in range(k):
            if r != i and A[r][i]:
                f = A[r][i] * inv
                Ar, Ai = A[r], A[i]
                for j in range(i, k):
                    Ar[j] -= f * Ai[j]
                b[r] -= f * b[i]
    return [b[i] / A[i][i] if A[i][i] else 0.0 for i in range(k)]


def design(static, model, rows, groups):
    levels = sorted({lv for _, lv, _, _ in rows})
    gi = {g: i for i, g in enumerate(groups)}
    X, y = [], []
    for _, lv, board, avg in rows:
        f = bm.features(static, board, model["bis"])
        s0 = bm.dot(model["weights"], f)
        x = [1.0 if lv == L else 0.0 for L in levels] + [s0] + [0.0] * len(groups)
        for kk, v in f.items():
            g = group(kk)
            if g in gi:
                x[len(levels) + 1 + gi[g]] += v
        X.append(x)
        y.append(avg)
    return X, y, len(levels)


def finetune(apply=True):
    static = load_set("TFTSet19")
    f = ROOT / "data" / "board_model_TFTSet19.json"
    model = bm.load(19)
    rows = variant_boards(static)
    counts = Counter(group(k) for _, _, b, _ in rows for k in bm.features(static, b, model["bis"]) if group(k))
    groups = sorted(g for g, n in counts.items() if n >= 8)
    X, y, nl = design(static, model, rows, groups)
    ridge = list(range(nl + 1, nl + 1 + len(groups)))
    comps = sorted({r[0] for r in rows})
    fold = {c: i % 5 for i, c in enumerate(comps)}

    def cv(lam, prior_only=False):
        pred = [None] * len(rows)
        for k in range(5):
            tr = [i for i, r in enumerate(rows) if fold[r[0]] != k]
            te = [i for i, r in enumerate(rows) if fold[r[0]] == k]
            cols = list(range(nl + 1)) if prior_only else list(range(len(X[0])))
            Xt = [[X[i][j] for j in cols] for i in tr]
            th = solve(Xt, [y[i] for i in tr], [j for j in range(len(cols)) if j > nl], lam)
            for i in te:
                pred[i] = sum(t * X[i][j] for t, j in zip(th, cols))
        mae = sum(abs(p - t) for p, t in zip(pred, y)) / len(y)
        rho = []
        for L in sorted({r[1] for r in rows}):
            idx = [i for i, r in enumerate(rows) if r[1] == L]
            rho.append(spearman([pred[i] for i in idx], [y[i] for i in idx]))
        return mae, sum(rho) / len(rho)

    base = cv(0.0, prior_only=True)
    print(f"{len(rows)} MetaTFT Set 19 boards from {len(comps)} comps; {len(groups)} unit/trait groups (8+ boards)")
    print(f"prior only (level offsets + transfer score): held-out MAE {base[0]:.3f} places, Spearman within level {base[1]:+.3f}")
    best = None
    for lam in (1, 3, 10, 30, 100):
        r = cv(lam)
        print(f"  ridge {lam:>4}: held-out MAE {r[0]:.3f}, Spearman within level {r[1]:+.3f}")
        if best is None or r[0] < best[1][0]:
            best = (lam, r)
    lam, (mae, rho) = best
    improved = mae < base[0] - 0.01
    print(f"best ridge {lam}: MAE {base[0]:.3f} -> {mae:.3f}, Spearman {base[1]:+.3f} -> {rho:+.3f}; "
          + ("applied to the Set 19 model" if improved and apply else "not applied (no held-out gain)" if not improved else "dry run"))
    if improved and apply:
        th = solve(X, y, ridge, lam)
        b = th[nl]
        delta = {g: -th[nl + 1 + i] / PL_PLACES_PER_SCORE for i, g in enumerate(groups)}
        m = json.loads(f.read_text())
        w = m["weights"]
        for g, d in delta.items():
            keys = [k for k in w if group(k) == g] or ([g] if g.startswith("t:") else [])
            for k in keys:
                w[k] = round(w.get(k, 0.0) + d, 4)
        m["finetune"] = {"boards": len(rows), "comps": len(comps), "ridge": lam, "groups": len(groups),
                         "held_out": {"prior_mae": round(base[0], 3), "mae": round(mae, 3), "prior_spearman": round(base[1], 3), "spearman": round(rho, 3)},
                         "slope_places_per_score": round(b, 3), "places_per_score_applied": round(PL_PLACES_PER_SCORE, 3),
                         "source": "tools/calibrate.py finetune (MetaTFT level 7-10 boards)"}
        f.write_text(json.dumps(m))
    return base, best


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "finetune":
    finetune("--dry" not in sys.argv)


# ---------------------------------------------------------------------------------------------------------------
# augments: the anchors in engine/augvalue.py rescaled to measured augment outcomes. The last public augment stats
# (tactics.tools, archived on the Wayback Machine; Riot removed augments from match data on 2024-11-13), summarised
# in the browser with tools/augment_archive.js on 2026-11-21. Per set: 10/50/90th percentile of avg place over
# augments with 300+ picks; per kind: mean avg place and the change from taking it at 2-1 to taking it at 4-2.
AUGMENT_STATS = {
    "Set 12 (14.18b, 261 augments, 2.27M picks)": {"p10": 4.27, "p50": 4.50, "p90": 4.78,
        "kinds": {"hero": (4.716, None), "trait": (4.478, -0.132), "econ": (4.546, 0.19), "items": (4.546, 0.149), "combat": (4.498, -0.174)},
        "kind_p10_p90": {"hero": (4.29, 5.08), "trait": (4.06, 4.91), "econ": (4.34, 4.78), "items": (4.32, 4.73), "combat": (4.29, 4.69)}},
    "Set 11 (14.9, 232 augments)": {"p10": 4.23, "p50": 4.47, "p90": 4.80,
        "kinds": {"hero": (4.32, None), "trait": (4.528, -0.111), "econ": (4.529, 0.085), "items": (4.581, 0.141), "combat": (4.47, -0.186)},
        "kind_p10_p90": {"hero": (3.59, 4.68), "trait": (4.21, 4.97), "econ": (4.27, 4.82), "items": (4.32, 4.81), "combat": (4.24, 4.69)}},
}
KIND_GROUP = {"hero": "hero", "trait": "trait", "econ": "econ", "reroll": "econ", "item": "items", "combat": "combat",
              "units": "combat", "other": "combat"}


def augments_calibration():
    import augments as A
    import augvalue
    import meta
    from plans import pbe_comps, pbe_plans
    sets = list(AUGMENT_STATS.values())
    width = sum(s["p90"] - s["p10"] for s in sets) / len(sets)
    offset, step, bounds = {}, {}, {}
    for k in ("hero", "trait", "econ", "items", "combat"):
        bounds[k] = [round(sum(st["kind_p10_p90"][k][i] - st["p50"] for st in sets) / len(sets), 3) for i in (0, 1)]
        offset[k] = round(sum(s["kinds"][k][0] - s["p50"] for s in sets) / len(sets), 3)
        r = [s["kinds"][k][1] for s in sets if s["kinds"][k][1] is not None]
        step[k] = round(sum(r) / len(r) / 2, 3) if r else 0.0          # per round: 2-1 -> 3-2 -> 4-2 is two steps
    static = load_set("TFTSet19")
    cat = A.catalog(static["set"])
    plans = {p["id"][4:]: p for p in pbe_plans(static)}
    det = meta.details(static["set"])
    comps = [c for c in pbe_comps(static) if c["name"] in plans]
    arch = {c["name"]: ("fast9" if c["style"] == "Fast 9" else A.archetype(plans[c["name"]], static)) for c in comps}
    augs = [a for a, i in meta.augments(static["set"]).items() if (i.get("status") or "confirmed") == "confirmed"]
    centre = {c["name"]: augvalue.centred(static, c, plans[c["name"]], arch[c["name"]], cat, det.get(c["name"]), raw=True) for c in comps}
    best = []
    for a in augs:
        vals = [augvalue.value(static, c, plans[c["name"]], arch[c["name"]], a, cat, det.get(c["name"]), raw=True)[0] - centre[c["name"]]
                for c in comps]
        best.append(min(vals))                                        # the augment on the comp it suits best
    best.sort()
    model_width = best[int(0.9 * (len(best) - 1))] - best[int(0.1 * (len(best) - 1))]
    scale = round(width / model_width, 3) if model_width else 1.0
    out = {"scale": scale, "kind_offset": offset, "round_step": step, "bounds": bounds, "target_width_p10_p90": round(width, 3),
           "model_width_before": round(model_width, 3), "measured": AUGMENT_STATS,
           "source": "tactics.tools archived augment stats (Wayback), summarised by tools/augment_archive.js; tools/calibrate.py augments"}
    f = ROOT / "data" / "models" / "augment_calibration.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1))
    print(f"measured: augments' 10-90% spread {width:.2f} places; anchors' spread on each augment's best comp {model_width:.2f}"
          f" -> scale {scale}")
    print(f"kind offsets vs the median augment (+ = worse): {offset}")
    print(f"per round later (2-1 -> 3-2 -> 4-2): {step}")
    print(f"value bounds per kind (measured 10th-90th percentile vs the median augment): {bounds}")
    return out


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "augments":
    augments_calibration()


# ---------------------------------------------------------------------------------------------------------------
# items: what special items are worth OVER a normal completed item, measured on Set 18 crawled boards (Master+).
#   placement ~ level dummies + board gold value + total completed items + #artifacts and #radiants on a holder that
#               wants them or not + #emblems that reach a new trait tier / keep an active trait / activate nothing
#               + #best-in-slot items (main carry / second / tank) + #off-type items on the carry
# Total items soaks up "lived longer, got more items", so each special count reads as a premium over a normal item.
# Best-in-slot = a unit's three most common items over ALL boards (not top-4 ones: no placement leaks in).
BOOT = 60
ART_HOLDERS = 6     # an artifact's usual holders: its six most common (MetaTFT lists six per artifact on Set 19)


def item_class(name):
    if "Radiant" in name:
        return "radiant"
    if "Artifact" in name:
        return "artifact"
    if "Emblem" in name:
        return "emblem"
    return "normal"


def emblem_trait(name, traits):
    key = name.split("Emblem")[-1] or name.split("Emblem")[0]
    key = key.replace("DA_18_", "").replace("DA_", "").lower()
    return next((t for t in traits if t.replace(" ", "").lower() == key), None)


def item_damage_kinds():
    """{item api name: 'AD' / 'AP' / 'hybrid' / 'tank'} from CommunityDragon recipes (engine/linefinder.py
    damage_type: Sword, Bow, Gloves are AD; Rod and Tear AP; Vest, Cloak, Belt tank)."""
    from linefinder import damage_type
    items = json.loads((ROOT / "data" / "raw" / "cdragon" / "tft_latest.json").read_text())["items"]
    api = {i["apiName"]: i for i in items if i.get("apiName")}
    out = {}
    for a, i in api.items():
        parts = [(api.get(c) or {}).get("name") for c in i.get("composition") or []]
        if len(parts) == 2 and all(parts):
            out[a] = damage_type(parts)
    return out


def items_calibration():
    static, lobs = games(18)
    dmg = item_damage_kinds()
    traits = [t["name"] for t in static["traits"]]
    info = {t["name"]: t for t in static["traits"]}
    unit_traits = {u["name"]: u["traits"] for u in static["units"]}
    freq, held_by = defaultdict(Counter), defaultdict(Counter)
    for _, ps in lobs:
        for p in ps:
            for u, _, its in p["board"]:
                freq[u].update(i for i in its if item_class(i) == "normal")
                for i in its:
                    if item_class(i) == "artifact":
                        held_by[i][u] += 1
    bis = {u: {i for i, _ in c.most_common(3)} for u, c in freq.items()}
    # who an artifact suits: its ART_HOLDERS most common holders (frequency, no placement: nothing leaks in); a
    # radiant suits a holder whose best-in-slot items include its normal version
    art_fit = {a: {u for u, _ in c.most_common(ART_HOLDERS)} for a, c in held_by.items()}
    normal_of = lambda r: r.replace("Radiant", "").rstrip("_")
    # a unit's damage type: what its best-in-slot items are (AD or AP), when they agree on one
    utype = {}
    for u, b in bis.items():
        k = Counter(dmg.get(i) for i in b)
        utype[u] = "AD" if k["AD"] > k["AP"] else "AP" if k["AP"] > k["AD"] else None
    # a unit's role from its best-in-slot items: damage (two or more AD / AP / hybrid items) or tank
    damage = {u: sum(dmg.get(i) in ("AD", "AP", "hybrid") for i in b) >= 2 for u, b in bis.items()}
    cost = {u["name"]: u["cost"] for u in static["units"]}

    def special_fit(u, i):
        """artifact: on one of its usual holders or not (a holder of the same kind measured no better: +0.17 vs +0.00,
        overlapping); radiant: its normal version is the holder's best-in-slot, or of the holder's damage type (a tank
        item on a tank), or neither"""
        if item_class(i) == "artifact":
            return "artifact_fit" if u in art_fit.get(i, ()) else "artifact_misfit"
        n = normal_of(i)
        if n in bis.get(u, ()):
            return "radiant_fit"
        k = dmg.get(n)
        on = (k in ("AD", "AP") and utype.get(u) == k) or (k == "hybrid" and damage.get(u)) or (k == "tank" and not damage.get(u))
        return "radiant_ontype" if on else "radiant_misfit"

    names = ["L7", "L8", "L9", "L10", "gold/30", "items", "artifact_fit", "artifact_misfit", "radiant_fit", "radiant_ontype", "radiant_misfit",
             "emblem_deeper", "emblem_activates", "emblem_active", "emblem_dead", "emblem_unread", "bis_main", "bis_second", "bis_tank", "offtype_carry"]
    X, y, lob_of = [], [], []
    for li, (_, ps) in enumerate(lobs):
        for p in ps:
            board = p["board"]
            carry = max(board, key=lambda x: len(x[2]), default=(None, 0, []))[0]
            all_items = [(u, i) for u, _, its in board for i in its]
            cls = Counter(item_class(i) for _, i in all_items)
            counts = Counter(t for u, _, _ in {(u, s, None) for u, s, _ in board} for t in unit_traits.get(u, []))
            # an emblem takes an active trait a tier deeper, activates a trait, keeps an active trait where it was
            # (the holder still gets the trait's bonus), or leaves its trait inactive; emblems whose trait can't be read
            # (or that the holder already has) apart
            em = Counter()
            for u, i in all_items:
                if item_class(i) != "emblem":
                    continue
                t = emblem_trait(i, traits)
                if not t or t in unit_traits.get(u, []):
                    em["unread"] += 1
                    continue
                bps = (info.get(t) or {}).get("breakpoints") or []
                before = sum(counts[t] >= b for b in bps)
                after = sum(counts[t] + 1 >= b for b in bps)
                counts[t] += 1
                em["deeper" if after > before and before else "activates" if after > before else "active" if after else "dead"] += 1
            fit = Counter(special_fit(u, i) for u, i in all_items if item_class(i) in ("artifact", "radiant"))
            nbis = sum(1 for u, i in all_items if i in bis.get(u, ()))
            # main carry: the damage unit holding the most items (dearer, higher-star first on ties); second: other
            # damage units; tanks: units whose best-in-slot items are tank items
            dmg_units = [(u, s, its) for u, s, its in board if damage.get(u)]
            main = max(dmg_units, key=lambda x: (len(x[2]), cost.get(x[0], 1) * x[1]), default=(None, 0, []))[0]
            role = lambda u: "main" if u == main else "second" if damage.get(u) else "tank"
            nb = Counter(role(u) for u, i in all_items if i in bis.get(u, ()))
            want = utype.get(carry)
            off = sum(1 for u, i in all_items if u == carry and want and dmg.get(i) == {"AD": "AP", "AP": "AD"}[want])
            lv = p["level"]
            X.append([float(v) for v in (lv == 7, lv == 8, lv == 9, lv >= 10, gold_value(static, board) / 30, len(all_items),
                                         fit["artifact_fit"], fit["artifact_misfit"], fit["radiant_fit"], fit["radiant_ontype"], fit["radiant_misfit"],
                                         em["deeper"], em["activates"], em["active"], em["dead"], em["unread"],
                                         nb["main"], nb["second"], nb["tank"], off)])
            y.append(p["placement"])
            lob_of.append(li)
    beta = ols(X, y)
    # 95% intervals: bootstrap over whole lobbies (placements within a lobby aren't independent)
    by_lob = defaultdict(list)
    for i, li in enumerate(lob_of):
        by_lob[li].append(i)
    ids = list(by_lob)
    rng = random.Random(7)
    boots = []
    for _ in range(BOOT):
        pick = [i for li in (rng.choice(ids) for _ in ids) for i in by_lob[li]]
        boots.append(ols([X[i] for i in pick], [y[i] for i in pick]))
    lo = [sorted(b[k] for b in boots)[int(0.025 * BOOT)] for k in range(len(names))]
    hi = [sorted(b[k] for b in boots)[int(0.975 * BOOT) - 1] for k in range(len(names))]
    out = {n: [round(b, 3), round(l, 3), round(h, 3)] for n, b, l, h in zip(names, beta, lo, hi)}
    # pooled best-in-slot premium (older readers): the per-item mean of the carry and other estimates
    tot = [sum(x[-4 + r] for x in X) for r in range(3)]                # BIS items on main / second / tank
    out["bis"] = [round(sum(tot[r] * out[k][j] for r, k in enumerate(("bis_main", "bis_second", "bis_tank"))) / max(1.0, sum(tot)), 3)
                  for j in range(3)]
    # an emblem in a trait the comp runs (deeper or already active: which one depends on the board's exact counts),
    # per-emblem mean of the two
    k = [names.index("emblem_deeper"), names.index("emblem_active")]
    tot = [sum(x[i] for x in X) for i in k]
    out["emblem_used"] = [round(sum(t * out[names[i]][j] for t, i in zip(tot, k)) / max(1.0, sum(tot)), 3) for j in range(3)]
    n = len(y)
    print(f"{n} Set 18 boards ({len(ids)} lobbies); {BOOT} bootstrap resamples over lobbies")
    for k in names[4:] + ["emblem_used"]:
        b, l, h = out[k]
        print(f"  {k:15} {b:+.3f}  [{l:+.3f}, {h:+.3f}]" + ("  premium over a normal item" if k not in ("items", "gold/30") else ""))
    f = ROOT / "data" / "models" / "item_calibration.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"effects": out, "boards": n, "lobbies": len(ids),
                             "source": "Set 18 crawl (Master+), tools/calibrate.py items; [estimate, 2.5%, 97.5%] places, - = better"}, indent=1))
    return out


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "items":
    items_calibration()


# ---------------------------------------------------------------------------------------------------------------
# tempo: how much a stronger early board is worth. Across MetaTFT's comps, pick-weighted least squares of the comp's
# avg place on its openers' mean round win rate (levels 4-6), bootstrap over comps. Comps whose openers win more end
# better; comp quality confounds it, so read it as an upper bound for one player's board.
def tempo_calibration():
    from plans import pbe_comps
    static = load_set("TFTSet19")
    rows = []
    for c in pbe_comps(static):
        if c.get("source") == "lolchess":            # its openers are its MetaTFT parent's: counted there
            continue
        e = {x["level"]: x["round_win_rate"] for x in c.get("early", [])}
        early = [e[lv] for lv in (4, 5, 6) if lv in e]
        if early:
            arch = "fast9" if c["style"] == "Fast 9" else "reroll" if c["style"].startswith("lvl") else "fast8"
            rows.append((sum(early) / len(early), c["avg_place"], c["pick_rate"], arch))

    def wls(rs):
        w = [r[2] for r in rs]
        W = sum(w)
        mx = sum(a * r[0] for a, r in zip(w, rs)) / W
        my = sum(a * r[1] for a, r in zip(w, rs)) / W
        sxx = sum(a * (r[0] - mx) ** 2 for a, r in zip(w, rs))
        return sum(a * (r[0] - mx) * (r[1] - my) for a, r in zip(w, rs)) / sxx if sxx else 0.0

    rng = random.Random(3)
    out = {}
    for name, rs in [("all", rows)] + [(a, [r for r in rows if r[3] == a]) for a in ("fast9", "fast8", "reroll")]:
        bs = sorted(wls([rng.choice(rs) for _ in rs]) for _ in range(1000))
        out[name] = [round(wls(rs), 3), round(bs[25], 3), round(bs[974], 3), len(rs)]
        print(f"  {name:7} {out[name][0]:+.2f} places per +1.0 opener round win rate  [{out[name][1]:+.2f}, {out[name][2]:+.2f}]  ({len(rs)} comps)")
    fit = rwr_fit(static)
    print(f"  round win rate given the board score's gap: sigmoid({fit['scale']} x gap + {fit['bias']}) on {fit['openers']} "
          f"openers (corr {fit['corr']:+.2f}): a typical board's expected round win rate {fit['typical']:.2f}")
    f = ROOT / "data" / "models" / "tempo_calibration.json"
    f.write_text(json.dumps({"slope": out, "rwr_fit": fit,
                             "source": "MetaTFT Set 19 PBE comps (openers' round win rates vs avg place; and vs engine/power.py "
                                       "fight score gap to the typical board), tools/calibrate.py tempo"}, indent=1))
    return out


def rwr_fit(static):
    """How MetaTFT's real round win rate of an opener follows the board score's gap to the typical board of its size
    (engine/power.py fight): RWR = sigmoid(scale x gap + bias), pick-weighted cross-entropy on every MetaTFT opener
    (its listed units, filled as par fills them). The tempo slope was measured per unit of RWR, so a board's gap goes
    through this first: a weak link (small scale) means early strength moves places little."""
    import power
    from plans import pbe_comps
    m = power._model(static["set"])
    T, k, par = m["fight"]["T"], m["kinds"], m["fight"]["par"]
    rows = []
    for c in pbe_comps(static):
        if c.get("source") == "lolchess":
            continue
        for e in c.get("early", []):
            if e["level"] not in FILL or e.get("round_win_rate") is None:
                continue
            b, n_items = power._opener(static, [e], e["level"])
            parts = power.fight_parts(static, b)
            parts["items"] += T["items"] * (k.get("it", 0.0) + 0.5 * k.get("bis", 0.0)) * n_items / 3
            rows.append((sum(parts.values()) - par[str(len(b))]["z"], e["round_win_rate"], c.get("pick_rate") or 0.01))
    sig = lambda x: 1 / (1 + math.exp(-x))

    def ll(a, b):
        return sum(w * (r * math.log(sig(a * g + b)) + (1 - r) * math.log(1 - sig(a * g + b))) for g, r, w in rows)
    _, a, b = max((ll(a / 100, b / 100), a / 100, b / 100) for a in range(0, 201, 2) for b in range(-100, 101, 2))
    mg = sum(g for g, _, _ in rows) / len(rows)
    mr = sum(r for _, r, _ in rows) / len(rows)
    sg = math.sqrt(sum((g - mg) ** 2 for g, _, _ in rows) / len(rows))
    sr = math.sqrt(sum((r - mr) ** 2 for _, r, _ in rows) / len(rows))
    corr = sum((g - mg) * (r - mr) for g, r, _ in rows) / len(rows) / (sg * sr) if sg and sr else 0.0
    return {"scale": a, "bias": b, "openers": len(rows), "corr": round(corr, 3), "typical": round(sig(b), 3)}


# tiers: cut points between tier letters from MetaTFT's own letters (midpoints between neighbouring letters' avg-place
# ranges); OP and S+ split MetaTFT's S letter at its own 25th and 50th percentile.
def tier_calibration():
    from plans import pbe_comps
    static = load_set("TFTSet19")
    by = defaultdict(list)
    for c in pbe_comps(static):
        by[c["tier"]].append(c["avg_place"])
    order = [t for t in ("S", "A", "B", "C", "D") if by.get(t)]
    cuts = {}
    s = sorted(by["S"])
    cuts["OP"] = round(s[max(0, int(0.25 * (len(s) - 1)))], 2)
    cuts["S+"] = round(s[int(0.5 * (len(s) - 1))], 2)
    ours = {"S": "S", "A": "A", "B": "B", "C": "C"}
    for a, b in zip(order, order[1:]):
        if a in ours:
            cuts[ours[a]] = round((max(by[a]) + min(by[b])) / 2, 3)
    print("MetaTFT letters:", {t: (min(v), max(v), len(v)) for t, v in by.items()})
    print("cut points (expected avg place at most):", cuts)
    f = ROOT / "data" / "models" / "tier_calibration.json"
    f.write_text(json.dumps({"cuts": cuts, "source": "MetaTFT PBE comp letters, tools/calibrate.py tiers"}, indent=1))
    return cuts


def expert_map():
    import meta
    import re as _re
    a = meta.augments("TFTSet19")
    print(json.dumps({_re.sub(r"[^a-z0-9]", "", n.replace("+", "plus").lower()): x["expert"] for n, x in a.items() if x.get("expert")}))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in ("tempo", "tiers", "expert-map"):
    {"tempo": tempo_calibration, "tiers": tier_calibration, "expert-map": expert_map}[sys.argv[1]]()
