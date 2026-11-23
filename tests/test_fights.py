# Fight model: rows from recorded rounds, a prior-shrunk logistic fit, HP per loss, game dedup, tempo hookup.
#   python3 -I tests/test_fights.py
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import fights as F  # noqa: E402
import tempo as T  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
R = S["rules"]


def game(results, hp=100, lobby_level=None, start="2-1"):
    """States from 2-1 on: `results` are the PvP fights in order ('W'/'L'); a loss costs the rules' damage."""
    out, st, k, prev = [], start, 0, None
    while k < len(results) or (prev and F.round_type(prev["stage"]) == "pvp"):
        s = {"stage": st, "level": 6, "hp": hp, "lobby_level": lobby_level or {}, "lobby_hp": {}}
        if prev and F.round_type(prev["stage"]) == "pvp":
            won = results[k - 1] == "W"
            s["result"] = "win" if won else "loss"
            if not won:
                hp = max(0, hp - F.rules_loss(F.stage_key(prev["stage"])[0], R))
                s["hp"] = hp
        out.append(s)
        k += F.round_type(st) == "pvp"
        prev, st = s, next_stage(st)
    return out


def next_stage(st):
    s, r = F.stage_key(st)
    return f"{s + 1}-1" if r == 7 else f"{s}-{r + 1}"


# rows: one per PvP fight whose outcome shows next round; carousels and PvE rounds are not fights
g = game("WWLWL")
rows = F.rows(S, g, "g1")
assert [r["stage"] for r in rows] == ["2-1", "2-2", "2-3", "2-5", "2-6"], [r["stage"] for r in rows]
assert [r["won"] for r in rows] == [True, True, False, True, False]
assert rows[2]["hp_lost"] == F.rules_loss(2, R) and rows[0]["hp_lost"] == 0
assert rows[3]["form"] == (2 + 1) / (3 + 2)                      # 2 wins of the 3 fights known at 2-5

# no data: the prior exactly (the hand-set tempo model); the rules' damage exactly
assert F.fit_win([], {}) == [F.PRIOR[k] for k in F.FEATURES]
assert F.fit_loss([], R) == (1.0, 0)

# evidence moves the weights, more evidence moves them further: being above the lobby's level wins fights
random.seed(3)


def synthetic(n):
    out = []
    for _ in range(n):
        gap = random.choice([-2, -1, 0, 1, 2])
        p = 1 / (1 + F.math.exp(-1.5 * gap))
        out.append({"stage_n": 4, "form": 0.5, "level": 8 + gap, "lobby_level": 8, "strength": None,
                    "won": random.random() < p, "hp_lost": 0, "dead": False})
    return out


few, many = F.fit_win(synthetic(20), {}), F.fit_win(synthetic(600), {})
assert F.PRIOR["level_gap"] < few[2] < many[2] and abs(many[2] - 1.5) < 0.3, (few, many)

# HP per loss: losses at twice the rules' damage pull the ratio from 1 toward 2, more with more losses
loss = lambda n: [{"stage_n": 4, "won": False, "dead": False, "hp_lost": 2 * F.rules_loss(4, R)}] * n   # noqa: E731
assert 1 < F.fit_loss(loss(5), R)[0] < F.fit_loss(loss(50), R)[0] < 2

# a game read twice is used once (the read with the most of the lobby wins, then the newest)
with tempfile.TemporaryDirectory() as d:
    a, b, c = (Path(d) / x for x in ("a", "b", "c"))
    for p, states in ((a, game("WWLWL")), (b, game("WWLWL", lobby_level={"X": 5})), (c, game("LLLWW"))):
        p.mkdir()
        (p / "state.jsonl").write_text("".join(json.dumps(s) + "\n" for s in states))
    kept = F.games([a, b, c])
    assert sorted(kept) == ["b", "c"], sorted(kept)

# predictions: higher level than the lobby -> likelier win; a saved model drives tempo's chances and damage
m = {"w": dict(F.PRIOR), "norm": {"4": 2.0}, "hp_ratio": 1.5}
assert F.predict(m, 0.5, 9, 8, None, 4) > F.predict(m, 0.5, 8, 8, None, 4) > F.predict(m, 0.5, 7, 8, None, 4)
assert F.hp_loss(m, 4, R) == 1.5 * F.rules_loss(4, R)
board = [{"unit": u["name"], "stars": 1} for u in S["units"] if u["cost"] == 1 and not u.get("unlockable")][:6]
pre = {"stage": "4-2", "level": 7, "xp": 0, "hp": 60, "streak": -2, "p0": 0.4, "gold": 50, "board": board,
       "unlocked": [], "pressure": 1.0, "owned": {b["unit"]: 1 for b in board}}
strength = T.strength_fn(S)
hand = {o["option"]: o for o in T.evaluate(S, pre, R, strength)}
fitted = {o["option"]: o for o in T.evaluate(S, dict(pre, fight=(3.0, 1.0, 2 * F.rules_loss(4, R))), R, strength)}
assert fitted["save"]["hp_lost"] > hand["save"]["hp_lost"]          # twice the damage per loss costs more HP
print("ok")
