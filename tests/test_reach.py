# Unlock reachability: round arithmetic, exact streak and counter math, and shop-simulation direction.
#   python3 -I tests/test_reach.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from reach import counter_reach, level_at, reach, rnum, stage_of, streak_reach  # noqa: E402
from unlocks import load_set  # noqa: E402

assert all(stage_of(rnum(s)) == s for s in ("2-1", "2-7", "3-1", "4-5", "6-3"))
assert rnum("4-1") - rnum("3-2") == 6
assert level_at("3-2", 4) == 6 and level_at("4-5", 9) == 9 and level_at("2-1", 3) == 4

# Rakan (win 4 / loss 3) at level 8 with one round left: a coin flip either way from 3W or 2L
rakan = {"win": 4, "loss": 3}
for streak in ({"type": "win", "n": 3}, {"type": "loss", "n": 2}):
    p, _ = streak_reach(rakan, {"stage": "5-1", "level": 8, "streak": streak}, "5-1")
    assert abs(p - 0.5) < 1e-9, (streak, p)
p_short, _ = streak_reach(rakan, {"stage": "5-1", "level": 8}, "5-2")
p_long, _ = streak_reach(rakan, {"stage": "5-1", "level": 8}, "6-1")
assert p_short == 0 and 0 < p_long < 1

# Counters: steady 1000/round needs 3 rounds for 3000 more
cond = {"name": "xayah_ally_damage", "n": 13000}
state = {"stage": "4-1", "counter_history": {"xayah_ally_damage": [7000, 8000, 9000, 10000]}}
assert counter_reach(cond, state, "4-5")[0] > 0.9
assert counter_reach(cond, state, "4-1")[0] < 0.1
assert counter_reach(cond, {"stage": "4-1"}, "4-5")[0] is None
# a counter that just wasn't re-read (unchanged values) is unknown, not dead
assert counter_reach(cond, {"stage": "4-1", "counter_history": {"xayah_ally_damage": [9000, 9000, 9000]}}, "4-5")[0] is None

# Shop simulation: more time helps; rolling down now buys speed at the cost of interest
S19 = load_set("TFTSet19")
mid = {"stage": "3-5", "level": 6, "gold": 44, "board": [{"unit": "Annie", "stars": 1, "items": ["X"]}]}
by = {s: next(r for r in reach(S19, mid, s) if r["unit"] == "Tibbers")["p"] for s in ("4-1", "5-1")}
assert by["4-1"]["standard"] < by["5-1"]["standard"], by
assert by["4-1"]["roll_now"] > by["4-1"]["standard"], by

# Level gates: Smeech needs level 9, which the standard line reaches at 5-5
smeech = next(r for r in reach(S19, {"stage": "4-1", "level": 7}, "5-1") if r["unit"] == "Smeech")
assert smeech["kind"] == "level" and smeech["p"] == 0.0
print("ok")
