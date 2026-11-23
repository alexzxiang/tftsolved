# Engine arithmetic, with the exact hit-chance DP checked against a slot-by-slot shop simulation.
#   python3 -I tests/test_econ.py
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from econ import damage, gold_for, hit_chance, income, level_cost, losses_to_death, tier_pool  # noqa: E402

rules = json.loads((ROOT / "data/constants.json").read_text())["TFTSet18"]


def simulate(need, gold, cost, odds, copies_left, tier_left, trials=20000, seed=1):
    """Real shop: each slot picks a tier, then a copy without replacement; unbought copies return."""
    rng, hits = random.Random(seed), 0
    for _ in range(trials):
        k, r, g, got = copies_left, tier_left, gold, 0
        while got < need and g >= 2:
            g -= 2
            kk, rr, seen = k, r, 0
            for _ in range(5):
                if rng.random() < odds and rr > 0:
                    if rng.random() < kk / rr:
                        seen, kk = seen + 1, kk - 1
                    rr -= 1
            buy = min(seen, need - got, g // cost)
            got, g, k, r = got + buy, g - buy * cost, k - buy, r - buy
        hits += got >= need
    return hits / trials


cases = [  # (need, gold, cost, odds, copies_left, tier_left)
    (2, 50, 4, 0.30, 9, 110),     # 2-star a held 4-cost at level 8
    (1, 40, 5, 0.15, 9, 80),      # find one 5-cost at level 9
    (6, 60, 2, 0.40, 22, 265),    # 2-cost reroll at level 6
]
for c in cases:
    exact, sim = hit_chance(*c), simulate(*c)
    print(f"{c}: dp {exact:.3f} sim {sim:.3f}")
    assert abs(exact - sim) < 0.02, (c, exact, sim)

# monotone in gold; level 9 finds a 5-cost far cheaper than level 8
assert hit_chance(2, 30, 4, 0.30, 9, 110) < hit_chance(2, 60, 4, 0.30, 9, 110)
five = dict(need=1, cost=5, copies_left=9, tier_left=80, pay_for_units=False)
assert gold_for(0.5, odds=0.15, **five) < gold_for(0.5, odds=0.03, **five)

static = {"units": [{"api": "A", "cost": 4, "pool": 10, "unlockable": False},
                    {"api": "B", "cost": 4, "pool": 10, "unlockable": True}]}
assert tier_pool(static, 4) == 10 and tier_pool(static, 4, unlocked={"B"}, out=3) == 17

assert damage(4, 5, rules) == 12 and losses_to_death(40, 4, 5, rules) == 3
assert income(54, 5, True, rules) == 5 + 5 + 2 + 1
assert level_cost(7, 0, rules) == 56 and level_cost(7, 10, rules) == 48
print("ok")
