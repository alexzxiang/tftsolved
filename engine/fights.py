"""Fight model, learned from recorded games: the chance you win a PvP round, and the HP a loss costs.

One row per PvP fight: what the screen showed in that round's planning phase (recent results, your level
against the lobby's from the player list badges, your board's strength against what boards at that stage
usually measure) and what happened (the next round's HP). Two models:
  win:  logistic regression on logit(recent form), level gap, relative strength. Its weights are pulled
        toward the hand-set tempo model (form 1, strength 3.0, level 0.5: guesses) by PRIOR_WEIGHT, so two
        games barely move it and twenty do.
  loss: HP lost per loss = ratio x rules damage (stage damage + typical survivors), the ratio shrunk toward
        1 by PRIOR_LOSSES pseudo-losses.
A game read several times is used once (the newest read). Leave-one-game-out scores both against the
hand-set models. The tempo evaluator uses the saved model when it exists.

    python3 -I engine/fights.py rows TFTSet19 [recordings/<dir> ...]    # the fight rows, one per line
    python3 -I engine/fights.py fit TFTSet19 [recordings/<dir> ...]     # -> data/models/fights_TFTSet19.json
"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from econ import damage  # noqa: E402
from lines import strength_fn  # noqa: E402
from review import SURVIVORS, lobby_so_far  # noqa: E402
from unlocks import infer_boards, load_set, round_type, stage_key  # noqa: E402

MODELS = ROOT / "data" / "models"
FORM_ROUNDS = 4             # recent PvP results behind "form" (as in tempo.py)
FEATURES = ("bias", "form", "level_gap", "strength")
PRIOR = {"bias": 0.0, "form": 1.0, "level_gap": 0.5, "strength": 3.0}   # the hand-set tempo model (+ a level guess)
PRIOR_WEIGHT = 8.0          # L2 pull toward PRIOR: about as strong as ~30 fights of evidence
PRIOR_LOSSES = 5            # pseudo-losses at the rules' damage
LEVEL_FRESH = 3            # a player's level badge counts for this many rounds after it was read
SAME_GAME = 0.8             # recordings sharing this share of (stage, HP) readings are the same game


def logit(p):
    return math.log(p / (1 - p))


def form(states, i):
    """Laplace-smoothed share of wins in the last FORM_ROUNDS fights known at round i."""
    res = [s["result"] for s in states[:i + 1] if s.get("result") in ("win", "loss")][-FORM_ROUNDS:]
    return (res.count("win") + 1) / (len(res) + 2)


def rules_loss(stage_n, rules):
    return damage(stage_n, SURVIVORS.get(stage_n, 6), rules)


def spots(static, states):
    """Per round: (form, your level, mean level of the other living players read in the last LEVEL_FRESH
    rounds, board strength or None). Older level reads go stale: players level every few rounds."""
    strength = strength_fn(static)
    boards = [s.get("board") or b for s, (b, _) in zip(states, infer_boards(static, states))]
    levels, out = {}, []
    for i, (s, lob) in enumerate(zip(states, lobby_so_far(states))):
        for n, lv in (s.get("lobby_level") or {}).items():
            levels[n] = (max(lv, levels.get(n, (0, 0))[0]), i)   # levels only rise
        alive = [lv for n, (lv, seen) in levels.items() if i - seen < LEVEL_FRESH and lob["lobby_hp"].get(n, 1) > 0]
        # strength only where the health bars were read: their star badges set the board's stars, and a
        # board scored without them (stars from the purchase ledger) isn't comparable (it reads ~40% weaker)
        b = boards[i] if s.get("units") else None
        out.append((form(states, i), s.get("level"), sum(alive) / len(alive) if alive else None,
                    strength([(x["unit"], x.get("stars", 1), None) for x in b]) if b else None))
    return out


def rows(static, states, game=""):
    """One row per PvP fight with a known outcome: round i's planning phase -> round i+1's HP."""
    out = []
    for i, (s, (f, lv, lobby_lv, st)) in enumerate(zip(states, spots(static, states))):
        nxt = states[i + 1] if i + 1 < len(states) else None
        if round_type(s["stage"]) != "pvp" or not nxt or nxt.get("result") not in ("win", "loss") or \
                None in (s.get("hp"), nxt.get("hp"), lv):
            continue
        out.append({"game": game, "stage": s["stage"], "stage_n": stage_key(s["stage"])[0], "form": round(f, 3),
                    "level": lv, "lobby_level": lobby_lv and round(lobby_lv, 2), "strength": st and round(st, 3),
                    "hp": s["hp"], "won": nxt["result"] == "win",
                    "hp_lost": s["hp"] - nxt["hp"] if nxt["result"] == "loss" else 0, "dead": nxt["hp"] <= 0})
    return out


def norms(rows_):
    """Mean board strength per stage: the yardstick for 'strong for this stage'."""
    by = {}
    for r in rows_:
        if r["strength"] is not None:
            by.setdefault(r["stage_n"], []).append(r["strength"])
    return {k: sum(v) / len(v) for k, v in by.items()}


def x_of(r, norm):
    n = norm.get(r["stage_n"])
    rel = (r["strength"] - n) / max(abs(n), 1.0) if r["strength"] is not None and n is not None else 0.0
    gap = r["level"] - r["lobby_level"] if r["lobby_level"] is not None else 0.0
    return [1.0, logit(r["form"]), gap, rel]


def p_win(w, x):
    z = sum(wi * xi for wi, xi in zip(w, x))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def solve(a, b):
    """Gaussian elimination for the small Newton step."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_win(rows_, norm, prior=PRIOR, weight=PRIOR_WEIGHT):
    """Penalised logistic regression by Newton's method: log loss + weight/2 * |w - prior|^2."""
    w0 = [prior[k] for k in FEATURES]
    w = w0[:]
    data = [(x_of(r, norm), 1.0 if r["won"] else 0.0) for r in rows_]
    for _ in range(25):
        g = [weight * (wi - pi) for wi, pi in zip(w, w0)]
        h = [[weight if i == j else 0.0 for j in range(len(w))] for i in range(len(w))]
        for x, y in data:
            p = p_win(w, x)
            for i in range(len(w)):
                g[i] += (p - y) * x[i]
                for j in range(len(w)):
                    h[i][j] += p * (1 - p) * x[i] * x[j]
        step = solve(h, g)
        w = [wi - si for wi, si in zip(w, step)]
        if max(map(abs, step)) < 1e-9:
            break
    return w


def fit_loss(rows_, rules):
    """HP lost per loss as a multiple of the rules' damage, shrunk toward 1 (fights that killed are capped)."""
    obs = [r["hp_lost"] / rules_loss(r["stage_n"], rules) for r in rows_ if not r["won"] and not r["dead"]]
    return (PRIOR_LOSSES + sum(obs)) / (PRIOR_LOSSES + len(obs)), len(obs)


def scores(w, norm, ratio, rows_, rules):
    """(log loss, HP-lost mean absolute error on losses) of a model on rows."""
    ll = [-math.log(max(1e-9, p if r["won"] else 1 - p)) for r in rows_ for p in [p_win(w, x_of(r, norm))]]
    err = [abs(r["hp_lost"] - ratio * rules_loss(r["stage_n"], rules)) for r in rows_ if not r["won"] and not r["dead"]]
    return (sum(ll) / len(ll) if ll else None), (sum(err) / len(err) if err else None)


def held_out(rows_, rules):
    """Leave one game out: the hand-set model (form only, rules damage) vs the fitted one."""
    games = sorted({r["game"] for r in rows_})
    hand = [PRIOR["bias"], PRIOR["form"], 0.0, 0.0]
    tot = {"hand": [[], []], "fitted": [[], []]}
    for g in games:
        train, test = [r for r in rows_ if r["game"] != g], [r for r in rows_ if r["game"] == g]
        norm = norms(train)
        for name, w, ratio in (("hand", hand, 1.0), ("fitted", fit_win(train, norm), fit_loss(train, rules)[0])):
            ll, err = scores(w, norm, ratio, test, rules)
            tot[name][0] += [ll] * len(test) if ll is not None else []
            tot[name][1] += [err] if err is not None else []
    return {k: {"log_loss": round(sum(a) / len(a), 3) if a else None, "hp_mae": round(sum(b) / len(b), 1) if b else None}
            for k, (a, b) in tot.items()} if len(games) > 1 else None


def games(dirs):
    """{name: states}: each recording's freshest state file, one recording per game (the newest)."""
    found = []
    for d in dirs:
        files = [f for f in (d / "state.replay.jsonl", d / "state.jsonl") if f.exists()]
        if files:
            f = max(files, key=lambda f: f.stat().st_mtime)
            states = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
            found.append((f.stat().st_mtime, d.name, states, {(s["stage"], s.get("hp")) for s in states}))
    kept = []
    # the read that saw the most: unit bars (stars), then the lobby's levels, then the newest
    for mtime, name, states, sig in sorted(found, key=lambda f: (sum(bool(s.get("units")) for s in f[2]),
                                                                 sum(bool(s.get("lobby_level")) for s in f[2]), f[0]),
                                           reverse=True):
        if not any(len(sig & k[3]) >= SAME_GAME * min(len(sig), len(k[3])) for k in kept):
            kept.append((mtime, name, states, sig))
    return {name: states for _, name, states, _ in kept}


def fit(static, dirs):
    rules = static["rules"]
    data = [r for name, states in games(dirs).items() for r in rows(static, states, name)]
    if not data:
        sys.exit("no fights with known outcomes in these recordings")
    norm = norms(data)
    w, (ratio, losses) = fit_win(data, norm), fit_loss(data, rules)
    model = {"set": static["set"], "games": sorted({r["game"] for r in data}), "fights": len(data), "losses": losses,
             "w": dict(zip(FEATURES, [round(x, 3) for x in w])), "prior": PRIOR, "prior_weight": PRIOR_WEIGHT,
             "norm": {str(k): round(v, 3) for k, v in sorted(norm.items())}, "hp_ratio": round(ratio, 3),
             "held_out": held_out(data, rules), "fitted": time.strftime("%Y-%m-%d")}
    MODELS.mkdir(parents=True, exist_ok=True)
    (MODELS / f"fights_{static['set']}.json").write_text(json.dumps(model, indent=1))
    return model


def load(set_name):
    f = MODELS / f"fights_{set_name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def predict(model, f, level, lobby_level, strength, stage_n):
    """P(win this round) at a spot (the features of spots())."""
    norm = {int(k): v for k, v in model["norm"].items()}
    r = {"stage_n": stage_n, "form": f, "level": level, "lobby_level": lobby_level, "strength": strength}
    return p_win([model["w"][k] for k in FEATURES], x_of(r, norm))


def hp_loss(model, stage_n, rules):
    return model["hp_ratio"] * rules_loss(stage_n, rules)


def main():
    cmd, static = sys.argv[1], load_set(sys.argv[2])
    dirs = [Path(d) for d in sys.argv[3:]] or sorted(d for d in (ROOT / "recordings").iterdir() if d.is_dir())
    if cmd == "rows":
        for name, states in games(dirs).items():
            for r in rows(static, states, name):
                print(json.dumps(r))
    elif cmd == "fit":
        m = fit(static, dirs)
        print(f"{m['fights']} fights ({m['losses']} losses) from {len(m['games'])} games: {', '.join(m['games'])}")
        print("  win model (prior in brackets): " + ", ".join(f"{k} {v:+.2f} [{PRIOR[k]:+.1f}]" for k, v in m["w"].items()))
        print(f"  HP per loss: {m['hp_ratio']:.2f} x rules damage")
        if m["held_out"]:
            h, f = m["held_out"]["hand"], m["held_out"]["fitted"]
            print(f"  leave-one-game-out: log loss {h['log_loss']} hand-set -> {f['log_loss']} fitted (0.693 = coin flip); "
                  f"HP per loss error {h['hp_mae']} -> {f['hp_mae']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
