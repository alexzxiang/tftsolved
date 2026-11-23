"""Tempo: which lines your HP can carry you into. An absorbing Markov chain over (PvP round, HP).

Each comp has a power curve: its board at every PvP round from 2-1 to 7-6, built from MetaTFT -- its level then
(levelling), its units (openers' core units filled from its final board to level 7; from 8, the units its MetaTFT
level boards play most, so unlock carries arrive when those boards show them), its stars (openers' until its main
roll-down -- the stage MetaTFT shows its players spending the most rerolls -- then its final board's targets: a
reroll comp spikes at 3-2 / 4-1, a fast 9 comp at 5-x) and completed items (Set 18's count at that round).
engine/power.py's fight score (fitted on 1st vs 2nd final fights) turns each round into a win chance against the
lobby (every comp's curve, pick-weighted).

A player on a comp moves through the chain: a win keeps HP, a loss costs the rules' damage (stage damage + typical
survivors, x the HP-loss ratio measured on recorded games), HP <= 0 is out. Exact dynamic programming over integer
HP, no sampling. Each game also draws the player a strength offset u ~ N(0, sigma^2) for the whole game (hitting or
missing, augments, positioning: what the average curve can't see), integrated by 5-point Gauss-Hermite quadrature;
sigma is fitted by maximum likelihood so the lobby's knockouts by stage match Set 18's. Placement: 1 + opponents
alive when you go out (7 independent opponents from the same mixture; ties split).

Fit (python3 -I engine/survival.py fit -> data/models/survival_TFTSet19.json): sigma, then each comp's curve offset
so its chain from 2-1 reproduces MetaTFT's average place (a fixed point: the lobby is the same curves). The fight
model gives a curve's shape -- when a comp is strong -- and MetaTFT how strong it ends up.

What a scenario answers: the comp's expected place from YOUR round and HP minus a typical player's of that comp alive
at that round. MetaTFT's average stays the anchor; the chain moves it. A comp whose strength comes late (fast 9,
unlock carries) spends HP before it pays, so low HP hurts it more.

    python3 -I engine/survival.py fit       # sigma and the anchors
    python3 -I engine/survival.py check     # knockouts by stage vs Set 18, and the anchored curves
"""
import functools
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import meta  # noqa: E402
import power  # noqa: E402
from plans import pbe_comps  # noqa: E402
from review import SURVIVORS  # noqa: E402
from unlocks import load_set, round_type, stage_key  # noqa: E402

LAST_STAGE = 7      # game rule: the last stage a lobby normally reaches
ANCHOR_ITERS = 5    # fixed-point passes anchoring the curves to MetaTFT (the lobby moves with the offsets)
GH5 = ((-2.020182870456086, 0.011257411327720698), (-0.9585724646138185, 0.2220759220056126), (0.0, 0.5333333333333333),
       (0.9585724646138185, 0.2220759220056126), (2.020182870456086, 0.011257411327720698))   # Gauss-Hermite, N(0, 1)
FIT = ROOT / "data" / "models"


def rounds():
    return [f"{s}-{r}" for s in range(2, LAST_STAGE + 1) for r in range(1, 8) if round_type(f"{s}-{r}") == "pvp"]


def _rnd(s):
    return stage_key(s) if s else (1, 0)


@functools.lru_cache(maxsize=None)
def loss_hp(set_name):
    """HP lost on a loss at each PvP round: rules damage x the ratio measured on recorded games (engine/fights.py)."""
    rules = load_set(set_name)["rules"]
    f = ROOT / "data" / "models" / f"fights_{set_name}.json"
    ratio = json.loads(f.read_text()).get("hp_ratio", 1.0) if f.exists() else 1.0
    out = []
    for r in rounds():
        s = stage_key(r)[0]
        out.append(max(1, round((rules["stage_damage"][str(min(s, 8))] + SURVIVORS.get(s, 6) * rules["damage_per_surviving_unit"]) * ratio)))
    return out


def _board_at(static, c, det, lv, rolled):
    """Comp c's board at level lv: to level 7, its opener's core units at that level filled from its final board,
    cheapest first (MetaTFT lists core units only); from 8, the units most played in MetaTFT's level boards (final-board
    order on ties), so unlock carries arrive when its boards show them. Stars: openers' (1-costs 2-star from level 5,
    2-costs from 6, else 1), then the final board's targets once it has rolled down."""
    cost = {u["name"]: u["cost"] for u in static["units"]}
    target = {b["unit"]: b.get("stars", 1) for b in c.get("board") or []}
    order = [b["unit"] for b in c.get("board") or []] or list(c["units"])
    if lv <= 7 or not (det.get("levels") or {}).get(lv):
        es = sorted(c.get("early") or [], key=lambda e: e["level"])
        core = list(dict.fromkeys((([e for e in es if e["level"] <= lv] or es or [{"units": []}])[-1])["units"]))[:lv]
        units = core + sorted((u for u in order if u not in core), key=lambda u: cost.get(u, 9))[:lv - len(core)]
        board = [{"unit": u, "stars": 2 if (cost.get(u, 9) == 1 and lv >= 5) or (cost.get(u, 9) == 2 and lv >= 6) else 1,
                  "items": []} for u in units]
    else:
        n = Counter(u for us, _ in det["levels"][lv] for u in us)
        units = sorted(n, key=lambda u: (-n[u], order.index(u) if u in order else 99))[:lv]
        board = [{"unit": u, "stars": 2 if cost.get(u, 9) <= 3 else 1, "items": []} for u in units]
    if rolled:
        board = [dict(x, stars=max(x["stars"], target.get(x["unit"], x["stars"]))) for x in board]
    return board


@functools.lru_cache(maxsize=None)
def curves(set_name):
    """({comp: [fight score at each PvP round]}, {comp: pick weight}, {comp: main roll-down round})."""
    static, model = load_set(set_name), power._model(set_name)
    prof = model["fight"].get("rounds") or {}
    dets = meta.details(set_name)
    out, w, roll = {}, {}, {}
    for c in pbe_comps(static):
        det = dets.get(c["name"]) or {}
        if c.get("source") == "lolchess" or not c.get("levelling"):
            continue
        rr = [x for x in det.get("levelling") or [] if x[1] and x[2] is not None]
        roll[c["name"]] = max(rr, key=lambda x: x[2])[1] if rr else None
        zs = []
        for r in rounds():
            lv = max((e["level"] for e in c["levelling"] if e["stage"] is None or _rnd(e["stage"]) <= _rnd(r)), default=3)
            rolled = roll[c["name"]] is not None and _rnd(r) >= _rnd(roll[c["name"]])
            board = _board_at(static, c, det, lv, rolled)
            known = [k for k in prof if _rnd(k) <= _rnd(r)]
            items = prof[max(known, key=_rnd)]["items"] if known else power.PAR[min(max(lv, 3), 10)][1]
            zs.append(power.count_z(static, board, items, model))
        out[c["name"]], w[c["name"]] = zs, c.get("pick_rate") or 0.01
    return out, w, roll


def _win(cv, w, zs):
    """Chance to win each PvP round with fight scores zs against the lobby: the mean over every comp's curve,
    pick-weighted, of sigmoid(score gap)."""
    tot = sum(w.values())
    return [sum(w[n] / (1 + math.exp(-(z - cv[n][i]))) for n in cv) / tot for i, z in enumerate(zs)]


def chain(p, dmg, start, hp_dist):
    """Exact DP: from {hp: prob} at round index `start`, win round i with p[i] or lose dmg[i] HP.
    Returns ([P(out at round i)], P(alive after the last round), {round index: {hp: prob alive there}})."""
    dist, out, seen = dict(hp_dist), [0.0] * len(p), {}
    for i in range(start, len(p)):
        seen[i] = dist
        nxt = defaultdict(float)
        for h, q in dist.items():
            nxt[h] += q * p[i]
            if h - dmg[i] <= 0:
                out[i] += q * (1 - p[i])
            else:
                nxt[h - dmg[i]] += q * (1 - p[i])
        dist = nxt
    return out, sum(dist.values()), seen


def _mixed(cv, w, zs, dmg, sigma, start=0, hp_dist=None):
    """[(quadrature weight, win chances, chain result)] over the game's strength offset u (Gauss-Hermite)."""
    out = []
    for x, wt in (GH5 if sigma else ((0.0, 1.0),)):
        p = _win(cv, w, [z + sigma * x for z in zs])
        out.append((wt, p, chain(p, dmg, start, hp_dist or {100: 1.0})))
    return out


def _lobby(cv, w, dmg, sigma):
    """Opponents: P(an opponent is out at round i), P(alive at the end), from every comp's chain from 2-1 at 100 HP."""
    tot = sum(w.values())
    out, end = [0.0] * len(dmg), 0.0
    for n, zs in cv.items():
        for wt, _, (o, e, _) in _mixed(cv, w, zs, dmg, sigma):
            out = [a + w[n] / tot * wt * b for a, b in zip(out, o)]
            end += w[n] / tot * wt * e
    return out, end


def _place(lob, death, alive_end, after=0):
    """(expected place, P(top 4)) for a player out at round i with probability death[i] (alive to the end with
    alive_end), against 7 independent opponents from the lobby, given they're alive at round index `after`."""
    o, e = lob
    alive0 = sum(o[after:]) + e
    exp = top4 = 0.0
    for i, q in list(enumerate(death)) + [(len(death), alive_end)]:
        if not q:
            continue
        s = (sum(o[i + 1:]) + e + 0.5 * o[i]) / alive0 if i < len(o) else 0.5 * e / alive0    # outlives me (ties half)
        exp += q * (1 + 7 * s)
        top4 += q * sum(math.comb(7, k) * s ** k * (1 - s) ** (7 - k) for k in range(4))
    return exp, top4


def _start_place(cv, w, zs, dmg, sigma, lob):
    return sum(wt * _place(lob, o, e)[0] for wt, _, (o, e, _) in _mixed(cv, w, zs, dmg, sigma))


def anchor(set_name, sigma, iters=ANCHOR_ITERS):
    """Each comp's curve offset so its chain from 2-1 reproduces MetaTFT's average place (bisection per comp; the
    lobby is the same curves, so a fixed point over a few passes). Returns (offsets, max place error)."""
    cv0, w, _ = curves(set_name)
    dmg = loss_hp(set_name)
    target = {c["name"]: c["avg_place"] for c in pbe_comps(load_set(set_name)) if c["name"] in cv0}
    b = dict.fromkeys(cv0, 0.0)
    for _ in range(iters):
        cv = {c: [z + b[c] for z in zs] for c, zs in cv0.items()}
        lob = _lobby(cv, w, dmg, sigma)
        for c, zs in cv0.items():
            lo, hi = -8.0, 8.0
            for _ in range(22):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if _start_place(cv, w, [z + mid for z in zs], dmg, sigma, lob) > target[c] else (lo, mid)
            b[c] = (lo + hi) / 2
    cv = {c: [z + b[c] for z in zs] for c, zs in cv0.items()}
    lob = _lobby(cv, w, dmg, sigma)
    return b, max(abs(_start_place(cv, w, cv[c], dmg, sigma, lob) - target[c]) for c in cv)


def knockouts(set_name, offsets, sigma):
    """{stage: share of knockouts} the chain predicts for the lobby (stages 2-6: in the chain the game doesn't end
    when one player is left, so its stage 7 isn't comparable)."""
    cv0, w, _ = curves(set_name)
    cv = {c: [z + offsets.get(c, 0.0) for z in zs] for c, zs in cv0.items()}
    o, _ = _lobby(cv, w, loss_hp(set_name), sigma)
    st = Counter()
    for i, q in enumerate(o):
        if stage_key(rounds()[i])[0] <= 6:
            st[stage_key(rounds()[i])[0]] += q
    tot = sum(st.values()) or 1.0
    return {s: v / tot for s, v in st.items()}


def set18_knockouts():
    import calibrate
    _, lobs = calibrate.games(18)
    real = Counter()
    for _, ps in lobs:
        for pl in ps:
            r = pl["last_round"]
            s = 2 + (r - 5) // 7 if r > 4 else 1
            if pl["placement"] > 1 and s <= 6:
                real[s] += 1
    return real


def fit(set_name="TFTSet19"):
    """sigma by maximum likelihood on Set 18's knockouts by stage (multinomial, stages 2-6; offsets from a sigma-0
    anchoring while searching), then the anchors at that sigma. Writes data/models/survival_<set>.json."""
    real = set18_knockouts()
    n = sum(real.values())
    b0, _ = anchor(set_name, 0.0, iters=3)
    best = None
    for sg in [x / 4 for x in range(0, 11)]:
        k = knockouts(set_name, b0, sg)
        ll = sum(real[s] * math.log(max(k.get(s, 0.0), 1e-9)) for s in real) / n
        print(f"  sigma {sg:.2f}: log-lik/knockout {ll:.4f}  stages 4/5/6 {k.get(4, 0):.1%} {k.get(5, 0):.1%} {k.get(6, 0):.1%}")
        if best is None or ll > best[0]:
            best = (ll, sg)
    ll, sg = best
    b, err = anchor(set_name, sg)
    k = knockouts(set_name, b, sg)
    doc = {"sigma": sg, "loglik": round(ll, 4), "offsets": {c: round(v, 4) for c, v in b.items()}, "max_place_error": round(err, 4),
           "knockouts": {"chain": {str(s): round(v, 4) for s, v in sorted(k.items())},
                         "set18": {str(s): round(v / n, 4) for s, v in sorted(real.items())}, "set18_players": n},
           "source": "engine/survival.py fit: sigma by multinomial ML on Set 18 knockout stages (placements 2-8, stages 2-6); "
                     "offsets anchor each comp's chain to its MetaTFT average place"}
    (FIT / f"survival_{set_name}.json").write_text(json.dumps(doc, indent=1))
    anchored.cache_clear()
    print(f"sigma {sg} (log-lik {ll:.4f}); anchored to MetaTFT within {err:.3f} places; offsets {min(b.values()):+.2f} .. {max(b.values()):+.2f}")
    return doc


@functools.lru_cache(maxsize=None)
def anchored(set_name):
    """(curves + offsets, weights, roll-down rounds, lobby, sigma) from the saved fit; without one, sigma 0 and
    anchors computed now."""
    cv0, w, roll = curves(set_name)
    f = FIT / f"survival_{set_name}.json"
    if f.exists():
        d = json.loads(f.read_text())
        sigma, b = d["sigma"], d["offsets"]
    else:
        sigma, (b, _) = 0.0, anchor(set_name, 0.0)
    cv = {c: [z + b.get(c, 0.0) for z in zs] for c, zs in cv0.items()}
    return cv, w, roll, _lobby(cv, w, loss_hp(set_name), sigma), sigma


@functools.lru_cache(maxsize=None)
def scenario(set_name, comp, rnd, hp):
    """{"places": expected place from (rnd, hp) minus a typical player's of this comp alive at rnd (+ = worse),
    "top4": the same for P(top 4), "online": its main roll-down (MetaTFT: the stage its players spend the most
    rerolls), "survive": your chance to reach it alive (None once it's past), "typical_hp": its players' mean HP
    at rnd}. The game's strength offset is integrated over its prior: your HP, average luck from here. None for a
    comp without MetaTFT levelling."""
    cv, w, roll, lob, sigma = anchored(set_name)
    if comp not in cv:
        return None
    R, dmg = rounds(), loss_hp(set_name)
    i0 = next((i for i, r in enumerate(R) if _rnd(r) >= _rnd(rnd)), len(R) - 1)
    on = next((i for i, r in enumerate(R) if roll.get(comp) and _rnd(r) >= _rnd(roll[comp])), None)
    e1 = t1 = e0 = t0 = surv = 0.0
    typ_hp = den = 0.0
    for wt, p, (_, _, seen) in _mixed(cv, w, cv[comp], dmg, sigma):
        typ = seen.get(i0) or {100: 1.0}
        alive = sum(typ.values()) or 1.0
        mine = chain(p, dmg, i0, {max(1, int(round(hp))): 1.0})
        base = chain(p, dmg, i0, {h: q / alive for h, q in typ.items()})
        a, b = _place(lob, mine[0], mine[1], i0)
        e1, t1 = e1 + wt * a, t1 + wt * b
        a, b = _place(lob, base[0], base[1], i0)
        e0, t0 = e0 + wt * alive * a, t0 + wt * alive * b          # typical: weighted by being alive at rnd
        den += wt * alive
        typ_hp += wt * sum(h * q for h, q in typ.items())
        if on is not None and on > i0:
            surv += wt * (1 - sum(mine[0][i0:on]))
    return {"places": round(e1 - e0 / den, 3), "top4": round(t1 - t0 / den, 3), "online": roll.get(comp),
            "survive": round(surv, 3) if on is not None and on > i0 else None, "typical_hp": round(typ_hp / den, 1)}


def check(set_name="TFTSet19"):
    """Knockouts by stage the chain predicts vs Set 18's, and each comp's anchored curve."""
    cv, w, roll, _, sigma = anchored(set_name)
    f = FIT / f"survival_{set_name}.json"
    d = json.loads(f.read_text()) if f.exists() else {}
    real = set18_knockouts()
    n = sum(real.values())
    k = knockouts(set_name, d.get("offsets") or {}, sigma)
    print(f"sigma {sigma}; anchored within {d.get('max_place_error')} places. Knockouts by stage (placements 2-8): Set 18 vs the chain")
    for s in range(2, 7):
        print(f"  stage {s}: {real[s] / n:6.1%}   {k.get(s, 0):6.1%}")
    R = rounds()
    print("anchored curves (u = 0): win chance vs the lobby at 3-2 / 4-2 / 5-2, main roll-down")
    for c in sorted(cv, key=lambda c: -w[c])[:12]:
        p = _win(cv, w, cv[c])
        print(f"  {c:28} roll {str(roll.get(c)):5} win {p[R.index('3-2')]:.2f} {p[R.index('4-2')]:.2f} {p[R.index('5-2')]:.2f}")


if __name__ == "__main__" and sys.argv[1:2] == ["check"]:
    check()
elif __name__ == "__main__" and sys.argv[1:2] == ["fit"]:
    fit()
