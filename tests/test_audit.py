# Parse-health audit: a clean game breaks no rule; each injected misread breaks its own field's rule.
#   python3 -I tests/test_audit.py
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import audit as A  # noqa: E402

S = A.load_set("TFTSet19")
trait = next(t["name"] for t in S["traits"] if t.get("counts") != "stars")
one = next(u["name"] for u in S["units"] if u["cost"] == 1)
off = next(u["name"] for u in S["units"] if u["cost"] <= 5 and S["shop_odds_by_level"][5][u["cost"] - 1] == 0)


def game():
    """2-1 .. 3-3 at level 6: 2 free XP a round (none at the carousel), a win streak, a steady board."""
    out, st, xp, streak = [], "2-1", 0, 0
    while st != "3-4":
        if A.round_type(st) != "carousel" and st != "2-1":
            xp += 2
        if A.round_type(st) == "pvp":
            streak += 1
        out.append({"stage": st, "level": 6, "xp": [xp, 36], "gold": 10, "hp": 100, "streak_n": streak,
                    "traits": [{"name": trait, "count": 7}], "units": [{"x": 0.1 * k, "y": 0.4} for k in range(6)],
                    "shop": [{"slot": 1, "unit": one}], "items_held": ["Recurve Bow"], "lobby_hp": {"A": 90}})
        st = A.next_stage(st)
    return out


def broken(states):
    out, _ = A.audit(S, states)
    return {f: [st for st, _ in bad] for f, (_, _, bad) in out.items() if bad}


assert broken(game()) == {}, broken(game())
g = game()
assert A.audit(S, g)[0]["xp"][0] > 5 and A.audit(S, g)[0]["streak"][0] > 5      # the checks did run

for field, stage, fault in [
        ("stage", "2-4", lambda s: None),                                  # a round never recorded
        ("xp", "2-6", lambda s: s["xp"].__setitem__(0, s["xp"][0] + 1)),   # 3 XP is no free 2 + 4s
        ("hp", "2-6", lambda s: s.update(hp=150)),                         # HP 100 -> 150
        ("streak", "2-6", lambda s: s.update(streak_n=9)),                 # 5 -> 9
        ("shop", "2-6", lambda s: s["shop"].append({"slot": 2, "unit": off})),   # a cost level 6 can't roll
        ("traits", "2-6", lambda s: s["traits"][0].update(count=1)),       # the panel half hidden
        ("items", "2-6", lambda s: s["items_held"].append("Chain Vest")),  # one round only
        ("lobby", "2-6", lambda s: s["lobby_hp"].update(A=100))]:          # 90 -> 100 for one player
    g = copy.deepcopy(game())
    k = next(i for i, s in enumerate(g) if s["stage"] == stage)
    if fault(g[k]) is None and field == "stage":
        del g[k]
    got = broken(g)
    assert field in got, (field, got)
    if field == "stage":
        assert got == {"stage": ["2-5"]}, got
    elif field in ("xp", "hp"):
        assert got[field] == [stage, A.next_stage(stage)], got           # up, then back down: both reads break
    else:
        assert got[field] == [stage], (field, got)

# small heals are Set 19 effects, not misreads
g = [dict(s, hp=103 if k else 100) for k, s in enumerate(game())]      # +3 at 2-2, kept
assert broken(g) == {}, broken(g)

# a read the rules file can't explain shows as a note, not a broken round
g = [dict(s, level=7, xp=[s["xp"][0], 64]) for s in game()]
assert broken(g) == {} and any("/64 at level 7" in n for n in A.audit(S, g)[1]), A.audit(S, g)[1]

assert A.blips([5, 5, 9, 5, 5, 6, 6]) == 1 and A.blips([1, 2, 3]) == 0
print("ok")
