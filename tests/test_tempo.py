# Tempo evaluator: roll now or save, priced in interest vs HP.
#   python3 -I tests/test_tempo.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import tempo as T  # noqa: E402
T.fights.load = lambda name: None          # the hand-set model: tests don't depend on a locally fitted one
from review import review  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
ones = [u["name"] for u in S["units"] if u["cost"] == 1 and not u.get("unlockable")][:4]
twos = [u["name"] for u in S["units"] if u["cost"] == 2 and not u.get("unlockable")][:3]
board = [{"unit": u, "stars": 1} for u in ones + twos]
owned = [{"unit": u, "copies": 2, "stars": 1} for u in ones + twos]       # pairs: one copy from a 2-star


def game(hp, result, gold_after, n=3):
    """4-1 then n rounds of 4-2.. at level 7 with `result` each round, spending down to gold_after."""
    st = [{"stage": "4-1", "level": 7, "xp": [10, 60], "gold": 50, "hp": hp + 11 * n, "board": board, "owned": owned}]
    for k in range(n):
        st.append({"stage": f"4-{k + 2}", "level": 7, "xp": [12 + 2 * k, 60], "gold": gold_after, "hp": hp,
                   "result": result, "streak": {"type": result, "n": k + 1}, "board": board, "owned": owned})
    return st


# bleeding at 30 HP on a loss streak while banking 50+: rolling is called, with numbers
calls = [c for _, _, _, c in T.tempo_calls(S, game(30, "loss", 58)) if c]
assert calls and "you went 'save'" in calls[0] and "roll" in calls[0].split("'")[3], calls
# the same bank at 90 HP on a win streak: saving is right, nothing to call
assert not [c for _, _, _, c in T.tempo_calls(S, game(90, "win", 58)) if c]
# rolling is the right move at 30 HP: no call when that's what happened
assert not [c for _, _, _, c in T.tempo_calls(S, game(30, "loss", 4)) if c]

# options: rolling buys win chance and HP, and costs only interest (spent gold counts as kept)
pre = {"stage": "4-2", "level": 7, "xp": 12, "hp": 30, "streak": -2, "p0": 0.25, "gold": 60, "board": board,
       "owned": {o["unit"]: o["copies"] for o in owned}, "unlocked": [], "pressure": 1.0}
o = {x["option"]: x for x in T.evaluate(S, pre, S["rules"], T.strength_fn(S))}
assert o["roll to 0"]["p_win"] > o["save"]["p_win"] and o["roll to 0"]["hp_lost"] < o["save"]["hp_lost"]
assert 0 < o["save"]["gold_end"] - o["roll to 0"]["gold_end"] <= 3 * 5          # at most 5 interest a round
# on top of the lobby's HP, HP is cheaper: the same spot is valued closer to saving
top = T.evaluate(S, dict(pre, pressure=0.25), S["rules"], T.strength_fn(S))
gap = lambda opts: {x["option"]: x["value"] for x in opts}                        # noqa: E731
assert gap(top)["roll to 0"] - gap(top)["save"] < o["roll to 0"]["value"] - o["save"]["value"]
# the review carries the call in place of the rule-of-thumb SPEND/BLEED note at that round
notes = review(S, game(30, "loss", 58))
assert any(k == "TEMPO" for _, k, _ in notes) and not any(k in ("SPEND", "BLEED") and st == "4-2" for st, k, _ in notes)
print("ok")
