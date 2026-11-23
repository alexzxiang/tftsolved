# Review-mode alerts on a scripted Set 19 game.
#   python3 -I tests/test_alerts.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from alerts import review  # noqa: E402
from unlocks import load_set  # noqa: E402

S19 = load_set("TFTSet19")


def U(name, stars=1, items=0):
    return {"unit": name, "stars": stars, "items": ["X"] * items}


game = [
    # Stage 2: two rerolls done, 10 gold: Seraphine is a free action until the 2-4 carousel
    {"stage": "2-1", "level": 4, "gold": 10, "board": [U("Ziggs"), U("Olaf")],
     "counters": {"rerolls_before_2_carousel": 2}},
    # Window missed
    {"stage": "2-5", "level": 5, "gold": 20, "board": [U("Ziggs"), U("Olaf")],
     "counters": {"rerolls_before_2_carousel": 2}},
    # Ziggs 2-star with no item and a component on the bench: Kobuko is one slam away
    {"stage": "3-2", "level": 6, "gold": 30, "board": [U("Ziggs", 2), U("Olaf", 2)], "item_bench": ["BFSword"],
     "counters": {"rerolls_before_2_carousel": 2}},
    # Xayah bought but benched while the Gu Feng counters wait
    {"stage": "4-1", "level": 7, "gold": 40, "board": [U("Lucian", 2), U("Olaf", 2), U("Ziggs", 2, 1)],
     "bench": [U("Xayah")], "counters": {"xayah_ally_damage": 0, "rerolls_before_2_carousel": 2}},
    # Fielded late: 16000 left at ~3000/round over 4 rounds is under even odds by 5-1
    {"stage": "4-5", "level": 8, "gold": 30, "board": [U("Xayah", 2, 3), U("Lucian", 2), U("Olaf", 2)],
     "counters": {"xayah_ally_damage": 9000, "rerolls_before_2_carousel": 2},
     "counter_history": {"xayah_ally_damage": [0, 3000, 6000, 9000]}},
]

timeline = review(S19, game)
for stage, items in timeline:
    for unit, kind, msg in items:
        print(f"{stage:<6}{kind:<11}{unit:<22}{msg}")
got = {(stage, unit, kind) for stage, items in timeline for unit, kind, _ in items}

assert ("2-1", "Seraphine", "FREE") in got
assert ("2-5", "Seraphine", "DEAD") in got
assert ("3-2", "Kobuko", "FREE") in got
assert ("4-1", "Wukong", "START NOW") in got
assert ("4-5", "Wukong", "CLOSING") in got
# reported once per change: Seraphine's DEAD does not repeat at later stages
assert sum(1 for s, u, k in got if u == "Seraphine" and k == "DEAD") == 1
# untargeted chase unlocks and save-up/level deadlines stay quiet
assert not any(u in ("Mordekaiser", "Pyke", "Smeech") for s, u, k in got), got
print("ok")
