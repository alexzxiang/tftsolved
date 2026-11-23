"""Set 19 board strength before Set 19 match data exists: the Set 18 board model (engine/board_model.py,
Plackett-Luce on crawled Master+ lobbies) carried onto Set 19 through MetaTFT's published averages.

Transfer: for Set 18 we have both the learned weights and the averages MetaTFT publishes (avg place of boards
holding a unit at a star level, reaching a trait tier, a unit with 3 items vs none). We fit how far a weight
sits from its kind's mean (a 4-cost 2-star, a 2nd trait tier, ...) per place of average-place gap, then:

    Set 19 weight = Set 18 kind mean + slope x (MetaTFT Set 19 gap, shrunk where MetaTFT's sample is small)

The output is a board_model file (data/board_model_TFTSet19.json): board_model.score works on it, and on launch
day `board_model.py fit 19 --prior 19` starts from it. All inputs are final-board averages (survivorship-
biased); the slope is fitted on the same kind of average, which absorbs part of that bias but not all.

    python3 -I engine/power.py build        # fit the transfer on Set 18, write the Set 19 model, run the checks
    python3 -I engine/power.py fight        # refit fight power (stars, board size) and the typical board per size
    python3 -I engine/power.py board Ziggs Lulu:2 Swain [--items "Lulu=Spear of Shojin,Blue Buff"] [--augments X]
"""
import datetime
import functools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import board_model as bm  # noqa: E402
import meta  # noqa: E402
from strength import trait_tiers  # noqa: E402
from unlocks import load_set  # noqa: E402

MIN_BOARDS = 30                 # Set 18 features with fewer boards stay out of the slope fit
SHARE_K = 0.02                  # a MetaTFT star share this small counts half (no game totals are published)
GAMES_K = 200                   # a MetaTFT trait tier with this many games counts half
STAR = 1.8                      # game rule: each star multiplies a unit's HP and attack damage by 1.8 (3-star = 3.24x)


def marginals(static, lobs):
    """The averages MetaTFT publishes, from crawled lobbies: {key: (avg place, boards)} for u:Unit*star,
    tier:Trait:k (highest tier reached) and items:Unit:n (completed items on the unit, 0-3)."""
    s, n = defaultdict(float), Counter()
    for lob in lobs:
        for place, _, board in lob:
            keys = {f"u:{u}*{st}" for u, st, _ in board} | {f"items:{u}:{min(len(it), 3)}" for u, _, it in board}
            keys |= {f"tier:{t}:{k}" for t, (k, _) in
                     trait_tiers(static, [{"unit": u, "stars": st} for u, st, _ in board]).items()}
            for k in keys:
                s[k] += place
                n[k] += 1
    return {k: (s[k] / n[k], n[k]) for k in n}


def fit_slope(pairs):
    """Weighted least squares through the origin, y = b x; also the weighted correlation. pairs: (x, y, weight)."""
    sw = sum(w for *_, w in pairs) or 1.0
    num, den = sum(w * x * y for x, y, w in pairs), sum(w * x * x for x, _, w in pairs) or 1.0
    vy = sum(w * y * y for _, y, w in pairs)
    return num / den, num / math.sqrt(den * vy) if vy else 0.0, sw


def centred(xs):
    """{key: value - weighted mean of its group}; xs: {key: (group, value, weight)}."""
    tot = defaultdict(lambda: [0.0, 0.0])
    for g, v, w in xs.values():
        tot[g][0] += v * w
        tot[g][1] += w
    return {k: v - tot[g][0] / tot[g][1] for k, (g, v, w) in xs.items() if tot[g][1]}


def cumulative(w, trait, k, kinds=None):
    """A trait's weight at tier k (the model stores one weight per tier step)."""
    src = kinds if kinds is not None else w
    return sum(src.get(f"t:step{s}" if kinds is not None else f"t:{trait}:{s}", 0.0) for s in range(1, k + 1))


def transfer(static18, model18, marg):
    """Slopes (weight per place of avg-place gap) for unit-stars, trait tiers and items, fitted on Set 18."""
    w, kinds = model18["weights"], model18["kinds"]
    ux = centred({k: (bm.kind(static18, k), ap, n) for k, (ap, n) in marg.items() if k.startswith("u:") and n >= MIN_BOARDS})
    units = fit_slope([(x, w.get(k, kinds[bm.kind(static18, k)]) - kinds[bm.kind(static18, k)], marg[k][1])
                       for k, x in ux.items()])
    tx = centred({k: (k.rsplit(":", 1)[1], ap, n) for k, (ap, n) in marg.items() if k.startswith("tier:") and n >= MIN_BOARDS})
    traits = fit_slope([(x, cumulative(w, k.split(":")[1], int(k.rsplit(":", 1)[1]))
                         - cumulative(None, None, int(k.rsplit(":", 1)[1]), kinds), marg[k][1]) for k, x in tx.items()])
    gaps = {u: (marg[f"items:{u}:3"], marg[f"items:{u}:0"]) for u in {k.split(":")[1] for k in marg if k.startswith("items:")}
            if f"items:{u}:3" in marg and f"items:{u}:0" in marg}
    ix = centred({u: ("all", a3[0] - a0[0], min(a3[1], a0[1])) for u, (a3, a0) in gaps.items()
                  if min(a3[1], a0[1]) >= MIN_BOARDS})
    items = fit_slope([(x, w.get(f"it:{u}", kinds["it"]) - kinds["it"], min(gaps[u][0][1], gaps[u][1][1])) for u, x in ix.items()])
    return {"units": units, "traits": traits, "items": items}


def bis_transfer(static18=None, lobs=None, model18=None):
    """Slope (learned best-in-slot weight per place of best-build gap) on Set 18: for each unit, MetaTFT's kind of
    number -- avg place when it holds its most common 3-item build minus avg place when it's on the board -- against
    the unit's learned bis weight (centred on the kind mean). Returns (slope, corr, n units)."""
    if lobs is None:
        static18, lobs = bm.lobbies(18)
        model18 = bm.load(18)
    builds, places = defaultdict(Counter), defaultdict(list)
    held = defaultdict(lambda: defaultdict(list))
    for lob in lobs:
        for place, _, board in lob:
            for u, _, its in board:
                places[u].append(place)
                if len(its) == 3:
                    b = tuple(sorted(its))
                    builds[u][b] += 1
                    held[u][b].append(place)
    w, k = model18["weights"], model18["kinds"]
    rows = {}
    for u, c in builds.items():
        if f"bis:{u}" not in w or not c:
            continue
        b, n = c.most_common(1)[0]
        if n >= MIN_BOARDS:
            rows[u] = ("all", sum(held[u][b]) / n - sum(places[u]) / len(places[u]), n)
    gap = centred(rows)
    slope, corr, _ = fit_slope([(x, w[f"bis:{u}"] - k["bis"], rows[u][2]) for u, x in gap.items()])
    return slope, corr, len(gap)


def bis_weights(units, kinds, slope):
    """Set 19 per-unit best-in-slot weights: kind mean + slope x (MetaTFT's best build place change - the mean),
    the build being the unit's most played 3-item build, shrunk by its play rate."""
    rows = {}
    for n, u in units.items():
        bs = [b for b in u.get("builds") or [] if b.get("place_change") is not None]
        if bs:
            b = max(bs, key=lambda b: b.get("play_rate") or 0)
            rows[n] = ("all", b["place_change"], (b.get("play_rate") or 0) / ((b.get("play_rate") or 0) + SHARE_K))
    return {f"bis:{n}": round(kinds.get("bis", 0.0) + slope * x * rows[n][2], 4) for n, x in centred(rows).items()}


def bis19(u):
    """MetaTFT best-in-slot: the most played 3-item build, else the 3 most played of its top items."""
    builds = sorted((b for b in u["builds"] if len(b["items"]) == 3 and not any(i.endswith("Emblem") for i in b["items"])),
                    key=lambda b: -b["play_rate"])
    if builds:
        return sorted(builds[0]["items"])
    return sorted(i for i, _ in sorted(u["items"].items(), key=lambda x: x[1])[:3])


def build(set19="TFTSet19"):
    static18, lobs = bm.lobbies(18)
    model18 = bm.load(18)
    slopes = transfer(static18, model18, marginals(static18, lobs))
    static = load_set(set19)
    kinds, units = model18["kinds"], meta.units(set19)
    w = {k: model18["weights"][k] for k in bm.GLOBAL}
    # unit-stars: kind mean + slope x (MetaTFT avg place - its kind's mean), shrunk by the star's share
    rows = {f"u:{n}*{s}": (bm.kind(static, f"u:{n}*{s}"), st["avg_place"], st["share"] / (st["share"] + SHARE_K))
            for n, u in units.items() for s, st in u["stars"].items() if st["avg_place"]}
    gap = centred(rows)
    for k, x in gap.items():
        w[k] = kinds.get(rows[k][0], 0.0) + slopes["units"][0] * x * rows[k][2]
    # trait tiers: MetaTFT counts -> tiers, games-weighted; cumulative value per tier, then per step
    info = {t["name"]: t for t in static["traits"]}
    acc = defaultdict(lambda: [0.0, 0])
    for (t, c), ap in meta.traits(set19).items():
        k = sum(c >= b for b in (info.get(t) or {}).get("breakpoints") or [])
        g = meta.trait_games(set19).get((t, c), 0)
        if k and g:
            acc[(t, k)][0] += ap * g
            acc[(t, k)][1] += g
    trows = {f"{t}:{k}": (k, s / g, g) for (t, k), (s, g) in acc.items()}
    tgap = centred(trows)
    cum = {}
    for key, x in tgap.items():
        t, k = key.rsplit(":", 1)
        g = trows[key][2]
        cum[(t, int(k))] = cumulative(None, None, int(k), kinds) + slopes["traits"][0] * x * g / (g + GAMES_K)
    for (t, k), v in cum.items():
        w[f"t:{t}:{k}"] = v - cum.get((t, k - 1), cumulative(None, None, k - 1, kinds))
    # items on a unit: kind mean + slope x (its 3-item vs 0-item gap - the mean gap)
    irows = {n: ("all", ic[3]["avg_place"] - ic[0]["avg_place"], min(ic[3]["share"], ic[0]["share"]))
             for n, u in units.items() if (ic := {r["items"]: r for r in u["items_count"]}).keys() >= {0, 3}}
    for n, x in centred(irows).items():
        sh = irows[n][2]
        w[f"it:{n}"] = kinds["it"] + slopes["items"][0] * x * sh / (sh + SHARE_K)
    slopes["bis"] = bis_transfer(static18, lobs, model18)
    w.update(bis_weights(units, kinds, slopes["bis"][0]))
    model = {"set": set19, "weights": {k: round(v, 4) for k, v in w.items()}, "kinds": kinds,
             "bis": {n: bis19(u) for n, u in units.items()},
             "trained_on": f"Set 18 model ({model18['trained_on']}) + MetaTFT {set19} averages",
             "loss": "metatft-transfer", "prior": "18",
             "transfer": {k: {"slope": round(b, 4), "corr": round(r, 3)} for k, (b, r, _) in slopes.items()},
             "fitted": datetime.date.today().isoformat()}
    model["temperature"], model["temperature_pairs"] = temperature(18)
    (ROOT / "data" / f"board_model_{set19}.json").write_text(json.dumps(model))
    return model


@functools.lru_cache(maxsize=None)
def _model(set_name):
    return bm.load(set_name.removeprefix("TFTSet"))


def strength(static, board, augments=(), model=None):
    """board: [{"unit", "stars", "items": [...]}] -> score; only differences between boards mean anything."""
    model = model or _model(static["set"])
    # board only: augments are valued where they're measured (engine/augvalue.py), not as a guessed strength bonus
    return bm.score(model, static, [(b["unit"], b.get("stars", 1), [i for i in b.get("items") or []]) for b in board])


# --- fight power: what wins a fight between boards of any size (early boards especially) ---------------------------
# Lanchester square law: a team's fighting strength is its total effective HP x its total damage per second, and the
# chance of winning a fight is logistic in the log of the strength ratio. Stars scale both factors by STAR, so a
# 3-star is ~10x a 1-star in strength and a 1-unit board is a ninth of a 3-unit one. The endgame-trained ranking above
# is linear in board gold value, which is fine between 8-unit boards and wrong between a 1-unit and a 3-unit board.

@functools.lru_cache(maxsize=None)
def stat_bands():
    """Set 18 unit stats (CommunityDragon): {cost: (median attack damage x attack speed, {melee: median armor + MR})}.
    Riot's stat bands carry over between sets; Set 19's own HP per unit is in the audit (tftips + Blitz PBE data).
    Damage is by cost only: casters' damage is in their ability, which CommunityDragon's Set 18 file doesn't carry."""
    from statistics import median
    sets = json.loads((ROOT / "data" / "raw" / "cdragon" / "tft_latest.json").read_text())["setData"]
    champs = [c for c in next(s for s in sets if s.get("mutator") == "TFTSet18")["champions"]
              if 1 <= c.get("cost", 0) <= 5 and (c.get("stats") or {}).get("hp") and c.get("traits")]
    out, stats18 = {}, {}
    for c in champs:
        x = c["stats"]
        stats18[c["name"]] = stats18[c["apiName"]] = (c["cost"], x["hp"], (x.get("armor") or 0) + (x.get("magicResist") or 0),
                                                       (x.get("range") or 0) <= 2)
    for cost in range(1, 6):
        cs = [c["stats"] for c in champs if c["cost"] == cost]
        out[cost] = (median((x.get("damage") or 0) * (x.get("attackSpeed") or 0) for x in cs),
                     {m: median((x.get("armor") or 0) + (x.get("magicResist") or 0) for x in cs if ((x.get("range") or 0) <= 2) == m)
                      for m in (True, False)})
    return out, stats18


@functools.lru_cache(maxsize=None)
def _hp19(set_name):
    f = ROOT / "data" / "manual" / f"{set_name}.audit.json"
    return {u["name"]: (u.get("hp") or 0, u.get("melee", True)) for u in json.loads(f.read_text())["units"]} if f.exists() else {}


def unit_power(cost, hp, resist, stars, gamma=0.0):
    """(effective HP, damage per second) of one unit: HP x the average damage reduction of its armor and MR
    (100 / (100 + x)); damage = its cost band's attack damage x attack speed x cost^gamma (abilities, which the band
    misses, grow with cost: gamma is fitted, fight_fit); both x STAR per star above 1. Costs above 5 (7-cost Baron,
    Smeech) take the 5-cost band and their own cost^gamma."""
    dps, _ = stat_bands()[0][min(max(cost, 1), 5)]
    m = STAR ** (max(stars, 1) - 1)
    return hp * m * (1 + resist / 200), dps * max(cost, 1) ** gamma * m


def fight_units(static, board, gamma=0.0):
    """[(effective HP, dps)] for a Set 19 board (HP per unit from the audit; a missing HP takes its cost band's median)."""
    bands, _ = stat_bands()
    hp19 = _hp19(static["set"])
    cost = {u["name"]: u["cost"] for u in static["units"]}
    out = []
    for b in board:
        c = min(max(cost.get(b["unit"], 1), 1), 5)
        hp, melee = hp19.get(b["unit"], (0, True))
        if not hp:
            from statistics import median
            hp = median([h for n, (h, m) in hp19.items() if h and m == melee and min(cost.get(n, 9), 5) == c] or [700])
        out.append(unit_power(max(cost.get(b["unit"], 1), 1), hp, bands[c][1][melee], b.get("stars", 1), gamma))
    return out


def log_power(units):
    """ln(total effective HP x total damage per second): Lanchester fighting strength."""
    return math.log(max(sum(h for h, _ in units), 1.0) * max(sum(d for _, d in units), 1e-3)) if units else 0.0


PARTS = ("units", "items", "traits")


def rest_parts(model, static, board):
    """The ranking model's score without its board-value terms (gold, unit count), which fight power replaces, in
    three parts: units (identity and stars as learned), items (items, best-in-slot, the itemised carry), traits."""
    f = bm.features(static, board, model["bis"])
    out = {"units": 0.0, "items": 0.0, "traits": 0.0}
    for k, v in f.items():
        if k not in ("gold", "units"):
            out["units" if k.startswith("u:") else "traits" if k.startswith("t:") else "items"] += model["weights"].get(k, 0.0) * v
    return out


def rest_score(model, static, board):
    return sum(rest_parts(model, static, board).values())


def fight_parts(static, board, model=None):
    """A board's fight score (log-odds units) in parts: units & stars (k x ln(fight power) + T x the ranking model's
    unit weights), items and traits (T x the ranking model's weights); the score is their sum."""
    model = model or _model(static["set"])
    c = model["fight"]
    b = [(x["unit"], x.get("stars", 1), list(x.get("items") or [])) for x in board]
    r = rest_parts(model, static, b)
    off = c.get("off_type", 0.0) * off_type_items(b, model["bis"], item_kinds19()) if c.get("off_type") else 0.0
    T = c["T"] if isinstance(c["T"], dict) else dict.fromkeys(PARTS, c["T"])
    return {"units": c["k"] * log_power(fight_units(static, board, c.get("gamma", 0.0))) + T["units"] * r["units"],
            "items": T["items"] * r["items"] + off, "traits": T["traits"] * r["traits"]}


def count_z(static, board, n_items, model=None):
    """Fight score of a board whose completed items are a count, not named (a typical board): items valued at the
    average item weight plus half the best-in-slot weight, spread over the board, as lobby_at and fight_par do."""
    model = model or _model(static["set"])
    k, fit = model["kinds"], model["fight"]
    T = fit["T"] if isinstance(fit["T"], dict) else dict.fromkeys(PARTS, fit["T"])
    r = rest_parts(model, static, [(x["unit"], x["stars"], []) for x in board])
    r["items"] += (k.get("it", 0.0) + 0.5 * k.get("bis", 0.0)) * n_items / 3
    return fit["k"] * log_power(fight_units(static, board, fit.get("gamma", 0.0))) + sum(T[x] * r[x] for x in PARTS)


def fight_z(static, board, model=None):
    """Fight score of a board (log-odds units): k x ln(fight power) + T x the rest of the ranking model."""
    return sum(fight_parts(static, board, model).values())


def fight_breakdown(static, board, model=None):
    """Where a board stands against the typical board of its size, part by part: each part's gap alone, as points of
    win chance (sigmoid(gap) - 0.5); also completed items held vs typical."""
    model = model or _model(static["set"])
    fp = (model.get("fight") or {}).get("par") or {}
    if not fp or not board:
        return None
    par = fp[str(min(len(board), max(int(x) for x in fp)))]
    mine = fight_parts(static, board, model)
    return {"parts": {k: round(1 / (1 + math.exp(-(mine[k] - par[k]))) - 0.5, 3) for k in mine},
            "items": sum(len(x.get("items") or []) for x in board), "typical_items": par["n_items"]}


def solve(A, b):
    """x with A x = b (Gaussian elimination, partial pivoting); A small and positive definite here."""
    n = len(b)
    M = [row[:] + [v] for row, v in zip(A, b)]
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[piv] = M[piv], M[i]
        for r in range(i + 1, n):
            f = M[r][i] / M[i][i]
            M[r] = [a - f * c for a, c in zip(M[r], M[i])]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def off_type_items(board, bis, kind):
    """Items on a unit of the other damage type to its own (its type: what most of its best-in-slot items are, AD
    or AP): an AD item on an AP carry. board: [(unit, stars, items)]; bis: {unit: items}; kind: {item: type}."""
    n = 0
    for u, _, its in board:
        ks = Counter(kind.get(i) for i in bis.get(u, ()))
        t = "AD" if ks["AD"] > ks["AP"] else "AP" if ks["AP"] > ks["AD"] else None
        n += sum(kind.get(i) == {"AD": "AP", "AP": "AD"}.get(t) for i in its) if t else 0
    return n


@functools.lru_cache(maxsize=None)
def item_kinds19():
    """{Set 19 completed item: AD / AP / hybrid / tank} from recipes (engine/linefinder.py damage_type)."""
    import linefinder
    _, build = linefinder.recipes()
    return {v: linefinder.damage_type(list(k) * (2 if len(k) == 1 else 1)) for k, v in build.items()}


def logistic(xs):
    """Maximum-likelihood weights (no intercept) for P(first board better) = sigmoid(w . x); Newton's method.
    xs: [feature tuple], each oriented so the better-placed board comes first. Returns (weights, log-lik per pair)."""
    n = len(xs[0])
    w = [0.0] * n
    for _ in range(25):
        g, H = [0.0] * n, [[1e-9 * (i == j) for j in range(n)] for i in range(n)]
        for x in xs:
            p = 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, x))))
            for i in range(n):
                g[i] += (1 - p) * x[i]
                for j in range(n):
                    H[i][j] += p * (1 - p) * x[i] * x[j]
        step = solve(H, g)
        w = [a + b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return w, sum(-math.log1p(math.exp(-sum(a * b for a, b in zip(w, x)))) for x in xs) / len(xs)


def fight_fit(set_n=18):
    """gamma, k and T by maximum likelihood on Set 18 final fights: the last combat of a lobby is 1st's board against
    2nd's, so the winner is the stronger board in a real fight between the two (2,810 lobbies). Boards knocked out in
    the same earlier round are ordered by HP left, not by a fight between them; that label flattened every weight
    (k 0.85 vs 1.51 here) and is kept only for comparison. k, T by logistic regression at each gamma on a 0.05 grid."""
    import calibrate
    static, lobs = bm.lobbies(set_n)
    model = bm.load(set_n)
    bands, s18 = stat_bands()
    kind18 = calibrate.item_damage_kinds()
    finals, rounds = [], []                     # (unit stats, rest, ranking score, off-type items) per board

    def row(board):
        return ([(s18[u], st) for u, st, _ in board if u in s18], rest_parts(model, static, board),
                bm.score(model, static, board), off_type_items(board, model["bis"], kind18))
    for lob in lobs:
        top = sorted(lob, key=lambda x: x[0])
        if len(top) >= 2 and top[0][0] == 1 and top[1][0] == 2 and top[0][1] == top[1][1]:
            finals.append((row(top[0][2]), row(top[1][2])))
        rounds.append([(rnd, place, row(board)) for place, rnd, board in lob])

    def x(a, b, gamma):
        pa, pb = (log_power([unit_power(s[0], s[1], s[2], st, gamma) for s, st in r[0]]) for r in (a, b))
        return (pa - pb, *(a[1][k] - b[1][k] for k in PARTS), a[2] - b[2], a[3] - b[3])

    def same_round(gamma):
        return [x(a[2], b[2], gamma) if a[1] < b[1] else x(b[2], a[2], gamma) for sc in rounds
                for i, a in enumerate(sc) for b in sc[i + 1:] if a[0] == b[0] and a[1] != b[1] and a[2][0] and b[2][0]]
    fits = []
    for g in [v / 20 for v in range(0, 31)]:
        ps = [x(a, b, g) for a, b in finals if a[0] and b[0]]
        w, ll = logistic([(v[0], *v[1:4], v[5]) for v in ps])
        fits.append((ll, g, w, len(ps)))
    ll, g, w, n = max(fits, key=lambda f: f[0])
    _, old = logistic([(v[4],) for v in (x(a, b, g) for a, b in finals if a[0] and b[0])])
    k, tu, ti, tt, o = w
    sr = same_round(g)
    _, ll_sr = logistic([(v[0], *v[1:4], v[5]) for v in sr])
    return {"gamma": g, "k": round(k, 4), "T": {"units": round(tu, 4), "items": round(ti, 4), "traits": round(tt, 4)},
            "off_type": round(o, 4), "pairs": n, "label": "1st vs 2nd: the final fight", "loglik": round(ll, 4),
            "loglik_gamma0": round(next(f[0] for f in fits if f[1] == 0), 4),
            "ranking_loglik": round(old, 4), "chance_loglik": round(-math.log(2), 4),
            "same_round_pairs": len(sr), "same_round_loglik_refit": round(ll_sr, 4)}


def _opener(static, early, level):
    """A comp's board at a level up to 7 from its MetaTFT openers: the listed core units of its opener at that level (the
    nearest one below, or level 4's), the rest filled with the level's typical units as tools/calibrate.py par fills
    them; 1-costs 2-star from level 5, 2-costs from 6. Returns (board, completed items per PAR)."""
    import calibrate                                       # tools/; FILL lives with the par it was measured for
    cost = {u["name"]: u["cost"] for u in static["units"]}
    es = sorted(early, key=lambda e: e["level"])
    e = ([x for x in es if x["level"] <= max(level, 4)] or es)[-1]
    fc, fs = calibrate.FILL[min(max(level, 4), 7)]
    filler = next(u["name"] for u in static["units"] if u["cost"] == fc)
    b = [{"unit": u, "stars": 2 if (cost.get(u, 9) == 1 and level >= 5) or (cost.get(u, 9) == 2 and level >= 6) else 1, "items": []}
         for u in e["units"][:level]]
    return b + [{"unit": filler, "stars": fs, "items": []}] * max(0, level - len(b)), PAR[min(max(level, 3), 10)][1]


def fight_par(static, model):
    """{units on board: fight score of the typical board that size}, pick-weighted over MetaTFT's Set 19 boards:
    openers at levels 4-7 (unlisted slots filled as tools/calibrate.py par fills them; 1-costs 2-star from level 5,
    2-costs from 6; completed items per PAR) and comps' final boards (8+ units, with their stars and items).
    Boards under 4 units: the level-4 typical board's average slot, times the number of units; 8 or more: the final
    boards' average slot (all final boards, 7 to 10 units), times the number of units (reroll comps end on 8 with
    3-stars, so per-size means of final boards aren't monotone)."""
    import calibrate
    from plans import pbe_comps
    k = model["kinds"]
    acc = defaultdict(lambda: [0.0] * 7)          # sum of pick x (ehp, dps, unit / item / trait weights, items), sum of picks
    for c in pbe_comps(static):
        if c.get("source") == "lolchess":
            continue
        boards = []
        for e in c.get("early", []):
            if e["level"] in calibrate.FILL:
                boards.append((*_opener(static, [e], e["level"]), False))
        if c.get("board"):
            boards.append(([{"unit": x["unit"], "stars": x.get("stars", 1), "items": x.get("items", [])} for x in c["board"]], 0, True))
        for b, n_items, final in boards:
            us = fight_units(static, b, model["fight"].get("gamma", 0.0))
            r = rest_parts(model, static, [(x["unit"], x["stars"], x["items"]) for x in b])
            r["items"] += (k.get("it", 0.0) + 0.5 * k.get("bis", 0.0)) * n_items / 3
            n, per = ("final", len(b)) if final else (len(b), 1)                 # finals: per slot
            a = acc[n]
            vals = (sum(h for h, _ in us), sum(d for _, d in us), r["units"], r["items"], r["traits"],
                    n_items or sum(len(x["items"]) for x in b))
            for i, v in enumerate(vals):
                a[i] += c["pick_rate"] * v / per
            a[6] += c["pick_rate"]
    fit = model["fight"]
    mean = {n: [v / a[6] for v in a[:6]] for n, a in acc.items() if a[6]}

    T = fit["T"] if isinstance(fit["T"], dict) else dict.fromkeys(PARTS, fit["T"])

    def part(h, d, ru, ri, rt, items, n=1.0):              # n: slots, when h ... items are per slot
        p = {"units": fit["k"] * math.log(h * n * d * n) + T["units"] * ru * n, "items": T["items"] * ri * n,
             "traits": T["traits"] * rt * n}
        return {**{x: round(v, 4) for x, v in p.items()}, "z": round(sum(p.values()), 4), "n_items": round(items * n, 1)}
    par = {n: part(*m) for n, m in mean.items() if n != "final"}
    for base, sizes, per in ((4, (1, 2, 3), 4), ("final", (8, 9, 10), 1)):
        if base in mean:
            for n in sizes:
                par[n] = part(*[v / per for v in mean[base]], n=n if per == 1 else n)
    return {str(n): par[n] for n in sorted(par)}


def round_profile(set_n=18, min_boards=30):
    """{round: {"boards", "items", "stars": {cost: mean}}}: Set 18 boards knocked out at each round (placements 2-8):
    completed items on board and mean star level by cost. Few players go out before 4-2, so it starts there."""
    import calibrate
    static, lobs = calibrate.games(set_n)
    cost = {u["name"]: min(u["cost"], 5) for u in static["units"]}
    acc = defaultdict(lambda: [0, 0, defaultdict(list)])
    for _, ps in lobs:
        for p in ps:
            if p["placement"] == 1:
                continue
            r = p["last_round"]
            key = "1-%d" % r if r <= 4 else "%d-%d" % (2 + (r - 5) // 7, (r - 5) % 7 + 1)
            a = acc[key]
            a[0] += 1
            a[1] += sum(len(x[2]) for x in p["board"])
            for u, st, _ in p["board"]:
                a[2][cost.get(u, 1)].append(st)
    return {k: {"boards": n, "items": round(i / n, 2), "stars": {str(c): round(sum(v) / len(v), 3) for c, v in sorted(s.items())}}
            for k, (n, i, s) in sorted(acc.items()) if n >= min_boards}


def _rnd(s):
    a, b = s.split("-")
    return int(a), int(b)


@functools.lru_cache(maxsize=None)
def lobby_at(set_name, rnd):
    """The lobby at a round: [(pick rate, fight parts, completed items, level)] for each MetaTFT comp at the level it has
    then (MetaTFT levelling). Before Set 18's measured rounds (4-2 on): its opener at that level, stars and items as
    fight_par has them. From 4-2: its opener (level 7 or less) or final board, with Set 18's star level by cost and
    completed items at that round (nearest measured round at or before it)."""
    from plans import pbe_comps
    static, model = load_set(set_name), _model(set_name)
    k, fit = model["kinds"], model["fight"]
    prof = fit.get("rounds") or {}
    known = [r for r in prof if _rnd(r) <= _rnd(rnd)]
    p = prof[max(known, key=_rnd)] if known else None
    cost = {u["name"]: u["cost"] for u in static["units"]}
    out = []
    for c in pbe_comps(static):
        if c.get("source") == "lolchess" or not c.get("levelling"):
            continue
        lv = max((e["level"] for e in c["levelling"] if e["stage"] is None or _rnd(e["stage"]) <= _rnd(rnd)), default=3)
        if lv <= 7 or not c.get("board"):
            board, n_items = _opener(static, c.get("early") or [], lv)
        else:
            board, n_items = [dict(x, items=[]) for x in c["board"]], 0
        if p:                                              # measured: items and stars at this round
            n_items = p["items"]
            fight_board = [dict(x, stars=p["stars"].get(str(min(cost.get(x["unit"], 1), 5)), x["stars"])) for x in board]
        else:
            fight_board = board
        r = rest_parts(model, static, [(x["unit"], x["stars"], []) for x in board])
        r["items"] += (k.get("it", 0.0) + 0.5 * k.get("bis", 0.0)) * n_items / 3
        T = fit["T"] if isinstance(fit["T"], dict) else dict.fromkeys(PARTS, fit["T"])
        parts = {"units": fit["k"] * log_power(fight_units(static, fight_board, fit.get("gamma", 0.0))) + T["units"] * r["units"],
                 "items": T["items"] * r["items"], "traits": T["traits"] * r["traits"]}
        out.append((c["pick_rate"], parts, n_items, lv))
    return out


def vs_lobby(static, board, rnd, model=None):
    """Chance to beat a board from the lobby at a round (pick-weighted over the comps: the mean of sigmoid(score gap)),
    and each part's gap alone against the lobby's mean part."""
    model = model or _model(static["set"])
    lobby = lobby_at(static["set"], rnd)
    if not lobby or not board:
        return None
    mine = fight_parts(static, board, model)
    z = sum(mine.values())
    w = sum(pk for pk, *_ in lobby)
    mean = {part: sum(pk * ps[part] for pk, ps, *_ in lobby) / w for part in mine}
    return {"win": sum(pk / (1 + math.exp(-(z - sum(ps.values())))) for pk, ps, *_ in lobby) / w,
            "parts": {part: round(1 / (1 + math.exp(-(mine[part] - mean[part]))) - 0.5, 3) for part in mine},
            "items": sum(len(x.get("items") or []) for x in board),
            "typical_items": round(sum(pk * n for pk, _, n, _ in lobby) / w, 1),
            "typical_level": round(sum(pk * lv for pk, *_, lv in lobby) / w, 1)}


def fight_build(set19="TFTSet19"):
    f = ROOT / "data" / f"board_model_{set19}.json"
    m = json.loads(f.read_text())
    m["fight"] = fight_fit()
    _model.cache_clear()
    m["fight"]["par"] = fight_par(load_set(set19), dict(bm.load(set19.removeprefix("TFTSet")), fight=m["fight"]))
    m["fight"]["rounds"] = round_profile()
    m["fight"]["source"] = ("engine/power.py fight: k, T by maximum likelihood on Set 18 final fights (1st vs 2nd, "
                            "Set 18 unit stats); par from MetaTFT Set 19 openers and final boards, pick-weighted")
    f.write_text(json.dumps(m))
    _model.cache_clear()
    return m["fight"]


# ponytail: the typical board at each level in an average lobby (TFT knowledge, not fitted): (cost, stars) per
# slot, completed items, trait tiers reached (1st, 2nd, 3rd). Fit from recorded games' boards once there are some.
PAR = {3: ([(1, 2), (1, 1), (2, 1)], 1, (1, 0, 0)),
       4: ([(1, 2), (1, 2), (2, 1), (2, 1)], 1, (2, 0, 0)),
       5: ([(1, 2), (1, 2), (2, 2), (2, 1), (3, 1)], 2, (2, 1, 0)),
       6: ([(1, 2), (2, 2), (2, 2), (2, 1), (3, 1), (3, 1)], 3, (3, 1, 0)),
       7: ([(1, 2), (2, 2), (2, 2), (3, 2), (3, 1), (3, 1), (4, 1)], 4, (3, 2, 0)),
       8: ([(2, 2), (2, 2), (3, 2), (3, 2), (3, 1), (4, 1), (4, 1), (4, 1)], 6, (4, 2, 1)),
       9: ([(2, 2), (3, 2), (3, 2), (4, 2), (4, 1), (4, 1), (4, 1), (5, 1), (5, 1)], 7, (4, 3, 1)),
       10: ([(3, 2), (3, 2), (4, 2), (4, 2), (4, 2), (4, 1), (5, 1), (5, 1), (5, 1), (5, 1)], 8, (5, 3, 2))}


def par_score(model, level):
    """The model's score for the typical board at a level: measured (tools/calibrate.py par) where the model has it,
    else from the knowledge prior PAR through its kinds of weight (board_model.features)."""
    measured = model.get("par") or {}
    if str(min(max(level, 3), 10)) in measured:
        return measured[str(min(max(level, 3), 10))]
    slots, items, tiers = PAR[min(max(level, 3), 10)]
    k, w = model["kinds"], model["weights"]
    score = sum(k.get(f"u:cost{c}*{st}", 0.0) for c, st in slots)
    holders = [3] * (items // 3) + ([items % 3] if items % 3 else [])
    score += sum(k.get("it", 0.0) * n / 3 + k.get("bis", 0.0) * 0.5 * n / 3 for n in holders)
    score += sum(n * sum(k.get(f"t:step{s}", 0.0) for s in range(1, t + 1)) for t, n in enumerate(tiers, 1))
    gold = sum(c * 3 ** (st - 1) for c, st in slots) / 30
    carry = max(slots, key=lambda x: x[0] * x[1])
    return score + w.get("units", 0) * len(slots) / 8 + w.get("gold", 0) * gold \
        + w.get("carry", 0) * (min(items, 3) / 3) * carry[1] * carry[0] / 5


def temperature(set_n=18):
    """Scale T for P(A beats B) = sigmoid(T x score gap), fitted on Set 18 boards eliminated in the same round
    (the honest test of strength at one moment; the raw Plackett-Luce gap is overconfident there)."""
    static, lobs = bm.lobbies(set_n)
    model = bm.load(set_n)
    gaps = []
    for lob in lobs:
        s = [(rnd, place, bm.score(model, static, board)) for place, rnd, board in lob]
        gaps += [(a[2] - b[2]) * (1 if a[1] < b[1] else -1) for i, a in enumerate(s) for b in s[i + 1:] if a[0] == b[0] and a[1] != b[1]]
    best = max((sum(-math.log1p(math.exp(-t * g)) for g in gaps), t) for t in [x / 20 for x in range(1, 41)])
    return best[1], len(gaps)


def win_chance(static, board, augments=(), model=None):
    """P(this board beats the typical board of its size): fight score vs the typical board's (fight_par), else the
    ranking model's score gap at its endgame temperature (before engine/power.py fight has run)."""
    model = model or _model(static["set"])
    fp = (model.get("fight") or {}).get("par") or {}
    if fp and board:
        n = str(min(len(board), max(int(x) for x in fp)))
        return 1 / (1 + math.exp(-(fight_z(static, board, model) - fp[n]["z"])))
    d = strength(static, board, augments, model) - par_score(model, len(board))
    return 1 / (1 + math.exp(-model.get("temperature", 1.0) * d))


def spearman(a, b):
    ra = {i: r for r, i in enumerate(sorted(range(len(a)), key=lambda i: a[i]))}
    rb = {i: r for r, i in enumerate(sorted(range(len(b)), key=lambda i: b[i]))}
    n = len(a)
    return 1 - 6 * sum((ra[i] - rb[i]) ** 2 for i in range(n)) / (n * (n * n - 1)) if n > 2 else 0.0


def checks(static, model):
    """Riot's design targets, and rank agreement with MetaTFT's comp and level-variant average places."""
    k = model["kinds"]
    out = [("2-star 4-cost > 2-star 3-cost (kinds)", k["u:cost4*2"] > k["u:cost3*2"]),
           ("3-star 5-cost above every other kind", k.get("u:cost5*3", 0) >= max(v for x, v in k.items() if x.startswith("u:")))]
    from plans import pbe_comps
    comps = [c for c in pbe_comps(static) if c.get("board")]
    sc = [strength(static, [{"unit": b["unit"], "stars": b.get("stars", 1), "items": b.get("items", [])} for b in c["board"]],
                   model=model) for c in comps]
    out.append((f"final boards of {len(comps)} comps: Spearman(strength, -avg place)",
                round(spearman(sc, [-c["avg_place"] for c in comps]), 3)))
    for lv, rows in sorted(level_boards(static).items()):
        if len(rows) > 5:
            s = [strength(static, [{"unit": u, "stars": 1} for u in us], model=model) for us, _ in rows]
            out.append((f"level {lv} variants ({len(rows)}): Spearman(strength, -avg place)",
                        round(spearman(s, [-ap for _, ap in rows]), 3)))
    return out


def level_boards(static):
    by = defaultdict(list)
    for comp, levels in meta.variants(static["set"]).items():
        for lv, boards in levels.items():
            by[lv] += boards
    return by


def parse_board(args):
    items, augs, board, skip = {}, [], [], False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("--items", "--augments"):
            skip = True
            if a == "--items":
                for pair in args[i + 1].split(";"):
                    u, _, its = pair.partition("=")
                    items[u.strip()] = [x.strip() for x in its.split(",")]
            else:
                augs = [x.strip() for x in args[i + 1].split(",")]
            continue
        u, _, s = a.partition(":")
        board.append({"unit": u, "stars": int(s or 1)})
    for b in board:
        b["items"] = items.get(b["unit"], [])
    return board, augs


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    static = load_set("TFTSet19")
    if cmd == "build":
        m = build()
        import calibrate                                  # tools/: refit on MetaTFT's Set 19 boards, then measure par
        calibrate.finetune()
        calibrate.par()
        _model.cache_clear()
        fight_build()
        lobby_at.cache_clear()
        for k, v in m["transfer"].items():
            print(f"transfer {k:6}: {v['slope']:+.3f} weight per place of avg-place gap (Set 18 corr {v['corr']:+.2f})")
        print(f"win-chance temperature {m['temperature']} (fitted on {m['temperature_pairs']} same-round Set 18 pairs)")
        for name, ok in checks(static, bm.load(19)):
            print(f"  {name}: {ok}")
    elif cmd == "bis":                                   # patch per-unit best-in-slot weights into the Set 19 model
        slope, corr, n = bis_transfer()
        f = ROOT / "data" / "board_model_TFTSet19.json"
        m = json.loads(f.read_text())
        bw = bis_weights(meta.units("TFTSet19"), m["kinds"], slope)
        m["weights"].update(bw)
        m.setdefault("transfer", {})["bis"] = {"slope": round(slope, 4), "corr": round(corr, 3)}
        f.write_text(json.dumps(m))
        _model.cache_clear()
        print(f"bis transfer: {slope:+.3f} weight per place of best-build gap (Set 18 corr {corr:+.2f}, {n} units); "
              f"{len(bw)} Set 19 units, weights {min(bw.values()):.2f} .. {max(bw.values()):.2f}")
    elif cmd == "fight":
        f = fight_build()
        print(f"fight score = {f['k']} x ln(effective HP x dps) + {f['T']} x the ranking model's unit / item / trait weights "
              f"+ {f['off_type']} per off-type item; damage x cost^{f['gamma']} "
              f"({f['pairs']} Set 18 final fights, 1st vs 2nd: log-lik/pair {f['loglik']} (gamma 0: {f['loglik_gamma0']}) "
              f"vs ranking model {f['ranking_loglik']}, chance {f['chance_loglik']})")
        print("typical board by size (fight score, completed items):", {n: (v["z"], v["n_items"]) for n, v in f["par"].items()})
        print("Set 18 boards by round (items, 4-cost stars):", {r: (v["items"], v["stars"].get("4")) for r, v in f["rounds"].items()})
        lobby_at.cache_clear()
    elif cmd == "board":
        board, augs = parse_board(sys.argv[2:])
        print(f"strength {strength(static, board, augs):.2f}")


if __name__ == "__main__":
    main()
