# Post-game tempo review on scripted logs: a bleed-out it must call, a clean game it must leave alone.
#   python3 -I tests/test_review.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from review import review  # noqa: E402
import fights  # noqa: E402
fights.load = lambda name: None             # hand-set tempo model: tests don't depend on a locally fitted one
from unlocks import load_set  # noqa: E402

S19 = load_set("TFTSet19")


def S(stage, level, gold, hp, rerolls=0):
    return {"stage": stage, "level": level, "gold": gold, "hp": hp, "xp": [0, 0],
            "counters": {"rerolls": rerolls}}


# Shaped like the 2026-05-08 game: banked through stage 3 while losing, level 8 at 4-1, out with 33 gold
bleed = [S("3-1", 5, 30, 80), S("3-2", 5, 40, 74), S("3-3", 6, 50, 66), S("3-5", 6, 52, 55),
         S("3-6", 7, 56, 46), S("4-1", 8, 33, 11)]
rows = review(S19, bleed)
for r in rows:
    print(*r)
kinds = {(st, k) for st, k, _ in rows}
assert ("3-2", "LEVEL") in kinds                 # level 5 at 3-2 with 40 gold
assert any(k == "BLEED" for _, k in kinds)       # three losses in a row under 60 HP on 50+ gold
assert any(k == "SPEND" for _, k in kinds)       # 11 HP at stage 4 with 33 gold
assert ("4-1", "OUT") not in kinds and ("4-1", "STREAK") not in kinds   # SPEND already says it
assert any("the next loss likely ends your game" in m for _, _, m in rows)

# A clean standard game: on the line, HP held, gold spent at the right time -> no tempo notes
clean = [S("3-2", 6, 30, 82), S("3-5", 6, 50, 78), S("4-1", 7, 50, 74), S("4-2", 8, 12, 72), S("4-5", 8, 30, 66)]
assert not [r for r in review(S19, clean) if r[1] in ("LEVEL", "SPEND", "BLEED", "CAP", "OUT", "STREAK")], review(S19, clean)

# A reroll comp sitting at level 5 on purpose is not told to level
reroll = [S("3-1", 5, 30, 80, 0), S("3-2", 5, 20, 78, 8), S("3-5", 5, 30, 77, 12)]
assert not [r for r in review(S19, reroll) if r[1] == "LEVEL"]

# lobby HP: falling into the bottom two of the lobby's HP is said once, and HP notes carry the rank
from review import hp_rank  # noqa: E402
lob = {"a": 90, "b": 80, "c": 70, "d": 65, "e": 60, "f": 30, "g": 0}           # g is out
assert hp_rank({"hp": 40, "lobby_hp": lob}) == (6, 7) and hp_rank({"hp": 40, "lobby_hp": {"a": 90}}) is None
seq = [{"stage": "3-5", "level": 7, "gold": 12, "hp": 45, "lobby_hp": lob},
       {"stage": "3-6", "level": 7, "gold": 14, "hp": 40, "lobby_hp": lob}]
low = [n for n in review(S19, seq) if n[1] == "LOW"]
assert len(low) == 1 and low[0][2].startswith("6th of 7 in HP at 3-5"), low
assert not [n for n in review(S19, [dict(x, hp=75) for x in seq]) if n[1] == "LOW"]

# leading the lobby's HP: no "roll before you're out" (the others go first), and no exit suspected at the end
lead = {"a": 21, "b": 17, "c": 6, "d": 0, "e": 0, "f": 0, "g": 0}
end = [{"stage": "5-6", "level": 8, "gold": 52, "hp": 43, "lobby_hp": lead},
       {"stage": "7-1", "level": 9, "gold": 11, "hp": 8, "lobby_hp": {"a": 3, "b": 0, "c": 0}}]   # rest: as before
assert not [n for n in review(S19, end) if n[1] in ("SPEND", "OUT")]
assert {"SPEND", "OUT"} <= {n[1] for n in review(S19, [dict(x, lobby_hp=None) for x in end])}

# holding a buildable pair of components through lost rounds: one SLAM note per stage, naming the item
from review import recipes, slam_notes  # noqa: E402
if recipes()[1]:                                     # needs the CommunityDragon item data (data/raw, gitignored)
    def r(stage, result, held):
        return {"stage": stage, "result": result, "hp": 60, "items_held": held}
    pair = ["B.F. Sword", "Sparring Gloves"]
    notes = slam_notes([r("3-1", "loss", pair), r("3-2", "loss", pair), r("3-3", "loss", pair)])
    assert len(notes) == 1 and notes[0][0] == "3-2" and "Infinity Edge" in notes[0][2], notes
    assert not slam_notes([r("3-1", "win", pair), r("3-2", "win", pair)])                   # winning: fine to wait
    assert not slam_notes([r("3-1", "loss", ["B.F. Sword"]), r("3-2", "loss", ["B.F. Sword"])])  # nothing to build
    assert not slam_notes([r("3-1", "loss", pair), r("3-2", "loss", ["B.F. Sword"])])       # slammed after one
print("ok")
