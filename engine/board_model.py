"""Learned board evaluator, set-specific: one value per unit at each star level, per trait tier step, and
per unit for its items (how much items on it matter, and how many are its best-in-slot).

    python3 -I engine/board_model.py fit 18                  # train on stored ranked lobbies of Set 18, report held-out
    python3 -I engine/board_model.py fit 19 --prior 18       # launch day: start from Set 18's learned kinds of weight
    python3 -I engine/board_model.py fit 19 --since 2026-12-16 --prior 19   # new patch: its lobbies + last patch's model
    python3 -I engine/board_model.py show 18                 # strongest units / trait tiers / item-hungry units

Listwise ranking: the Plackett-Luce likelihood of each lobby's whole finishing order on sparse features,
Adagrad SGD (replaced pairwise Bradley-Terry: as good or better on every held-out measure, 4x faster). Linear and readable: every weight is "how much
this adds to beating another board in the same lobby". Judged on held-out pairs eliminated in the same round:
final boards also encode how long a player survived, so all-pairs accuracy flatters expensive late boards.
Best-in-slot per unit = its most common items on top-4 boards (computed from training lobbies only).
Upgrade path once data is large: unit-pair interactions (factorization machine) or a tree ranker.
"""
import argparse
import datetime
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
from strength import trait_tiers  # noqa: E402

BIS_ITEMS = 3
L2 = 1e-3                           # shrinkage toward zero, per lobby, without a prior
PRIOR_LOBBIES = 100                 # a prior counts as much as ~100 lobbies (backtested 25-100 new lobbies: 25-200)
GLOBAL = ("units", "gold", "carry")


def lobbies(set_n, since=None):
    """[[(placement, last_round, board)]] for stored ranked lobbies of one set, oldest first;
    board = [(unit, stars, items)]. since: only lobbies played on or after that date (YYYY-MM-DD, UTC)."""
    from crawl import read_matches
    from unlocks import load_set, unit_resolver
    static = load_set(f"TFTSet{set_n}")                     # generated (data/pbe) or hand-made (data/manual)
    name = unit_resolver(static)
    start = since and datetime.datetime.fromisoformat(since).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    seen, out, unknown = set(), [], set()
    for m in read_matches(ROOT / "data"):
        info = m["info"]
        mid = m.get("id") or m.get("metadata", {}).get("match_id")
        if info.get("tft_set_number") != set_n or info.get("queue_id") != 1100 or mid in seen:
            continue
        if start and info.get("game_datetime", 0) < start:
            continue
        seen.add(mid)
        out.append((info.get("game_datetime", 0),
                    [(p["placement"], p["last_round"],
                      [(name(u["character_id"]), u["tier"], u.get("itemNames", [])) for u in p["units"]
                       if name(u["character_id"])]) for p in info["participants"]]))
        unknown |= {u["character_id"] for p in info["participants"] for u in p["units"] if not name(u["character_id"])}
    if unknown:
        print(f"note: {len(unknown)} unit ids not on the roster (summons/props or a naming gap): "
              f"{', '.join(sorted(unknown)[:8])}", file=sys.stderr)
    return static, [lob for _, lob in sorted(out, key=lambda x: x[0])]


def bis_table(lobs):
    """unit -> its most common items on top-4 boards."""
    seen = defaultdict(Counter)
    for lob in lobs:
        for place, _, board in lob:
            if place <= 4:
                for unit, _, items in board:
                    seen[unit].update(items)
    return {u: {i for i, n in c.most_common(BIS_ITEMS) if n >= 5} for u, c in seen.items()}


def features(static, board, bis):
    f = defaultdict(float)
    for unit, stars, items in board:
        f[f"u:{unit}*{stars}"] += 1
        f[f"it:{unit}"] += len(items) / 3                     # what items on this unit are worth
        f[f"bis:{unit}"] += sum(i in bis.get(unit, ()) for i in items) / 3
    for t, (k, _) in trait_tiers(static, [{"unit": u, "stars": s} for u, s, _ in board]).items():
        for step in range(1, k + 1):                           # cumulative: each weight = value of one more tier
            f[f"t:{t}:{step}"] = 1.0
    f["units"] = len(board) / 8
    cost = {u["name"]: min(u["cost"], 5) for u in static["units"]}
    f["gold"] = sum(cost.get(u, 1) * 3 ** (s - 1) for u, s, _ in board) / 30          # +0.4 pts held out
    carry = max(board, key=lambda x: (len(x[2]), cost.get(x[0], 1)), default=None)
    f["carry"] = (len(carry[2]) / 3) * carry[1] * cost.get(carry[0], 1) / 5 if carry else 0
    return dict(f)


def ranked(lob, static, bis):
    """[(last_round, features)] best first."""
    return [(rnd, features(static, board, bis)) for _, rnd, board in sorted(lob, key=lambda x: x[0])]


def dot(w, f):
    return sum(w.get(k, 0.0) * v for k, v in f.items())


def pl_grad(w, fs):
    """Gradient of -log P(finishing order) under Plackett-Luce, per feature; fs = board features best first.
    -log P = sum over places k of [log sum_{j>=k} exp(s_j) - s_k], s = w . features."""
    s = [dot(w, f) for f in fs]
    top = max(s)
    e = [math.exp(x - top) for x in s]
    tail = [sum(e[k:]) for k in range(len(e))]
    gs = [sum(e[j] / tail[k] for k in range(min(j + 1, len(e) - 1))) - (j < len(e) - 1) for j in range(len(e))]
    g = defaultdict(float)
    for gj, f in zip(gs, fs):
        for k, v in f.items():
            g[k] += gj * v
    return g


def train(lobs, prior=None, l2=None, epochs=20, lr=0.15, seed=1):
    """Adagrad SGD; lobs = [[features best first]]. Weights start at, and shrink toward, the prior (zero
    without one) with the weight of PRIOR_LOBBIES lobbies: a new patch moves them as far as its lobbies show,
    and the more lobbies it has, the further."""
    prior = prior or {}
    l2 = l2 if l2 is not None else PRIOR_LOBBIES / len(lobs) if prior else L2
    w, g2 = defaultdict(float, prior), defaultdict(lambda: 1e-8)
    data, rng = list(lobs), random.Random(seed)
    for _ in range(epochs):
        rng.shuffle(data)
        for ex in data:
            for k, g in pl_grad(w, ex).items():
                g += l2 * (w[k] - prior.get(k, 0.0))
                g2[k] += g * g
                w[k] -= lr * g / math.sqrt(g2[k])
    return dict(w)


def kind(static, k):
    """The family a feature backs off to when an older model has no weight for it."""
    if k.startswith("u:"):
        unit, stars = k[2:].rsplit("*", 1)
        cost = next((min(u["cost"], 5) for u in static["units"] if u["name"] == unit), 1)
        return f"u:cost{cost}*{stars}"
    if k.startswith("t:"):
        return "t:step" + k.rsplit(":", 1)[1]
    return k.split(":")[0]                                   # it, bis, or a global feature


def kinds(static, w):
    """Mean weight per kind: 3-cost 2-stars, 2nd trait tiers, items on a unit, ... (carried to the next set)."""
    by = defaultdict(list)
    for k, v in w.items():
        by[kind(static, k)].append(v)
    return {k: round(sum(v) / len(v), 4) for k, v in by.items()}


def prior_for(model, static, keys):
    """Per feature: the older model's own weight when it is the same set (a patch ago), else the older
    set's mean for that kind of feature (Set 18's 4-cost 2-stars -> Set 19's on launch day)."""
    same = model.get("set") == static["set"]
    return {k: model["weights"][k] if (same or k in GLOBAL) and k in model["weights"]
            else model.get("kinds", {}).get(kind(static, k), 0.0) for k in keys}


def rank_lobbies(lobs, static, bis):
    return [[f for _, f in ranked(lb, static, bis)] for lb in lobs]


def accuracy(w, static, lobs, bis):
    """Pair accuracy on held-out lobbies: all pairs; pairs eliminated in the same round (the honest test of
    strength at one moment); pairs of boards within 10% of each other's gold value (no "expensive wins")."""
    hit, n = Counter(), Counter()
    for lb in lobs:
        s = [(r, dot(w, f), f.get("gold", 0)) for r, f in ranked(lb, static, bis)]
        for i, (ri, si, gi) in enumerate(s):
            for rj, sj, gj in s[i + 1:]:
                for name, on in (("all", True), ("same_round", ri == rj), ("gold_matched", abs(gi - gj) <= 0.1 * max(gi, gj))):
                    if on:
                        n[name] += 1
                        hit[name] += si > sj
    return {k: (hit[k] / n[k], n[k]) for k in n}


def evaluate(static, lobs, folds=5, prior_model=None, **kw):
    """k-fold by lobby; returns {metric: (accuracy, pairs)}."""
    hit, n = Counter(), Counter()
    for fold in range(folds):
        tr = [lb for i, lb in enumerate(lobs) if i % folds != fold]
        bis = bis_table(tr)                                          # no peeking at held-out lobbies
        data = rank_lobbies(tr, static, bis)
        prior = prior_for(prior_model, static, {k for fs in data for f in fs for k in f}) if prior_model else None
        w = train(data, prior=prior, **kw)
        for k, (a, m) in accuracy(w, static, [lb for i, lb in enumerate(lobs) if i % folds == fold], bis).items():
            hit[k], n[k] = hit[k] + a * m, n[k] + m
    return {k: (hit[k] / n[k], n[k]) for k in n}


def score(model, static, board):
    """board: [(unit, stars, [items])] -> strength score (only differences between boards mean anything)."""
    return dot(model["weights"], features(static, board, model["bis"]))


def load(set_n):
    p = ROOT / "data" / f"board_model_TFTSet{set_n}.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text())
    m["bis"] = {u: set(i) for u, i in m["bis"].items()}
    return m


def fit(set_n, since=None, prior=None):
    static, lobs = lobbies(set_n, since)
    if len(lobs) < 25:
        sys.exit(f"only {len(lobs)} stored ranked Set {set_n} lobbies{' since ' + since if since else ''}; "
                 f"crawl more first (tools/crawl.py --set {set_n})")
    pm = None
    if prior:
        pm = load(prior) if str(prior).isdigit() else json.loads(Path(prior).read_text())
        if not pm:
            sys.exit(f"no prior model {prior}: fit it first")
        if pm.get("set") == static["set"] and not since:
            sys.exit("a same-set prior was trained on these lobbies: pass --since (the patch date) so it isn't reused")
    acc = evaluate(static, lobs, prior_model=pm)
    print(f"Set {set_n}: {len(lobs)} lobbies{' since ' + since if since else ''}"
          f"{' + prior ' + str(prior) if pm else ''}; held out (5-fold by lobby):")
    for k in ("same_round", "gold_matched", "all"):
        print(f"  {k.replace('_', '-'):13} {acc[k][0]:.1%}  ({acc[k][1]} pairs)")
    bis = bis_table(lobs)
    data = rank_lobbies(lobs, static, bis)
    w = train(data, prior=prior_for(pm, static, {k for fs in data for f in fs for k in f}) if pm else None)
    w = {k: round(v, 4) for k, v in w.items() if abs(v) > 1e-4}
    out = ROOT / "data" / f"board_model_TFTSet{set_n}.json"
    out.write_text(json.dumps({"set": static["set"], "weights": w, "kinds": kinds(static, w),
                               "bis": {u: sorted(i) for u, i in bis.items()},
                               "trained_on": f"{len(lobs)} ranked lobbies" + (f" since {since}" if since else ""),
                               "loss": "plackett-luce", "prior": str(prior) if pm else None,
                               "held_out": {k: round(a, 4) for k, (a, _) in acc.items()},
                               "fitted": datetime.date.today().isoformat()}))
    print(f"-> {out.relative_to(ROOT)}")


def show(set_n):
    m = load(set_n)
    w = m["weights"]
    units = sorted(((v, k[2:]) for k, v in w.items() if k.startswith("u:")), reverse=True)
    print("strongest unit-stars:", ", ".join(f"{u} {v:+.2f}" for v, u in units[:10]))
    print("weakest unit-stars:  ", ", ".join(f"{u} {v:+.2f}" for v, u in units[-6:]))
    tiers = sorted(((v, k[2:]) for k, v in w.items() if k.startswith("t:")), reverse=True)
    print("best trait tiers:    ", ", ".join(f"{t} {v:+.2f}" for v, t in tiers[:8]))
    hungry = sorted(((v + w.get('bis:' + k[3:], 0), k[3:]) for k, v in w.items() if k.startswith("it:")), reverse=True)
    print("item-hungry units (value of a full BIS set):", ", ".join(f"{u} {v:+.2f}" for v, u in hungry[:8]))
    for v, u in hungry[:4]:
        print(f"  {u} BIS: {', '.join(i.replace('DA_', '').replace('TFT_Item_', '') for i in m['bis'].get(u, []))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fit", "show"])
    ap.add_argument("set", type=int)
    ap.add_argument("--since", help="only lobbies from this date on (YYYY-MM-DD): the current patch")
    ap.add_argument("--prior", help="older model to start from: a set number or a model .json")
    a = ap.parse_args()
    fit(a.set, a.since, a.prior) if a.cmd == "fit" else show(a.set)
