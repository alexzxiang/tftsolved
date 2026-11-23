# Synthetic-match check for the post-game report. No API key needed.
#   python3 -I tests/test_postgame.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from postgame import board_value, report, stage  # noqa: E402

assert [stage(n) for n in (1, 4, 5, 11, 12, 26)] == ["1-1", "1-4", "2-1", "2-7", "3-1", "5-1"]

carry = {"character_id": "TFT18_Carry", "rarity": 4, "tier": 2, "itemNames": ["a", "b", "c"]}  # 4-cost 2-star
tank = {"character_id": "TFT18_Tank", "rarity": 0, "tier": 3, "itemNames": []}                # 1-cost 3-star
assert board_value([carry, tank], {}) == 4 * 3 + 1 * 9


def player(puuid, place, level, last_round, gold, augments=()):
    return {"puuid": puuid, "placement": place, "level": level, "last_round": last_round,
            "gold_left": gold, "units": [carry, tank], "augments": list(augments)}


# Me: 6th, out at 5-1 on level 7 holding 22 gold; the 5th and 7th went out the same stage on level 8.
lobby = [player("me", 6, 7, 26, 22), player("p5", 5, 8, 27, 4), player("p7", 7, 8, 26, 30)]
lobby += [player(f"p{i}", i, 9, 33, 10) for i in (1, 2, 3, 4)] + [player("p8", 8, 6, 19, 0)]
match = {"info": {"game_datetime": 1_790_000_000_000, "queue_id": 1100, "participants": lobby}}

text = report([match], "me", {})
print(text)
for want in ("died holding 22 gold", "behind same-stage players on level", "top 4 0%",
             "gold left in bottom-4 finishes: you 22.0 vs your lobbies 11.3",
             "level vs players knocked out in the same stage: -1.00",
             "augments present in match data: 0 of 8"):
    assert want in text, want
print("ok")
