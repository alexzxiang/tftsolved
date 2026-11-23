# Unlock checker scenarios on the hand-made Set 19 rules.
#   python3 -I tests/test_unlocks.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from unlocks import evaluate, load_set  # noqa: E402

S19 = load_set("TFTSet19")
assert S19["rules"]["base_income"] == 5 and len(S19["units"]) == 94 and len(S19["unlocks"]) == 32


def status(state, unit):
    return next(r for r in evaluate(S19, state) if r["unit"] == unit)


def U(name, stars=1, items=0, hex=None):
    u = {"unit": name, "stars": stars, "items": ["X"] * items}
    return u | ({"hex": hex} if hex else {})


# Stage 2: Kobuko is one item away, then ready; Seraphine's reroll window runs to the 2-4 carousel
early = {"stage": "2-1", "level": 4, "board": [U("Ziggs", 2), U("Olaf")], "counters": {"rerolls_before_2_carousel": 2}}
assert status(early, "Kobuko")["status"] == "LOCKED"
early["board"][0]["items"] = ["BFSword"]
assert status(early, "Kobuko")["status"] == "READY"
assert status(early, "Seraphine")["status"] == "PROGRESS"
assert status(early | {"stage": "2-5"}, "Seraphine")["status"] == "DEAD"

# Level-7 gate: Alune's board condition met at 6 waits for 7
hs = [U("Kayn"), U("Sett"), U("Ezreal"), U("Lux")]
assert status({"level": 6, "board": hs}, "Alune")["status"] == "NEEDS_LEVEL"
assert status({"level": 7, "board": hs}, "Alune")["status"] == "READY"
assert status({"level": 7, "board": hs[:3]}, "Alune")["value"] == 3

# Akali fork: K/DA side ready warns it blocks True Damage Akali; taking one blocks the other
kda = [U(n, 2) for n in ("Lillia", "Neeko", "Gragas", "Evelynn", "Kai'Sa", "Ahri")]
r = status({"level": 8, "board": kda}, "Akali (K/DA)")
assert r["status"] == "READY" and "permanently blocks Akali (True Damage)" in r["detail"], r
assert status({"board": kda, "unlocked": ["Akali (True Damage)"]}, "Akali (K/DA)")["status"] == "BLOCKED"

# Accumulators: unknown until the tracker is read; Xayah gate shows as paused
assert status({"board": []}, "Wukong")["status"] == "UNKNOWN"
r = status({"board": [U("Olaf")], "counters": {"xayah_ally_damage": 9000}}, "Wukong")
assert r["status"] == "PROGRESS" and "paused: Xayah not fielded" in r["detail"], r

# Smeech counts non-unique active traits only
smeech = [U("Ziggs"), U("Zoe"), U("Annie"), U("Taric"), U("Olaf"), U("Gnar"), U("Karthus"), U("Kennen"),
          U("Lillia"), U("Jax")]
r = status({"level": 9, "board": smeech}, "Smeech")
assert r["value"] >= 5 and r["status"] in ("PROGRESS", "READY"), r

# Vladimir needs positions; with them, one unit in the front two rows is ready at level 8
assert status({"level": 8, "board": [U("Olaf"), U("Zoe")]}, "Vladimir")["status"] == "UNKNOWN"
pos = [U("Olaf", hex=[0, 3]), U("Zoe", hex=[3, 0]), U("Karthus", hex=[2, 1])]
assert status({"level": 8, "board": pos}, "Vladimir")["status"] == "READY"
assert status({"level": 8, "board": pos + [U("Taric", hex=[1, 2])]}, "Vladimir")["status"] == "LOCKED"

# Rakan: loss streak of 3 at level 8; unknown rules stay unknown
assert status({"level": 8, "streak": {"type": "loss", "n": 3}}, "Rakan")["status"] == "READY"
assert status({"level": 8, "streak": {"type": "win", "n": 3}}, "Rakan")["status"] == "PROGRESS"
assert status({"board": [U("Jhin", 1, 2)]}, "Samira")["status"] == "READY"     # Classical with 2 items
assert not [u for u in S19["unlocks"] if u["unit"] in ("Nasus", "Galio")]           # normal units on current PBE

# A fielded unlockable is unlocked, and closes its exclusive twin
assert status({"board": [U("Jinx")]}, "Jinx")["status"] == "UNLOCKED"
assert status({"board": [U("Akali (K/DA)")]}, "Akali (True Damage)")["status"] == "BLOCKED"

# Baron needs both parts
baron = {"board": [U("Malzahar")], "counters": {"instruments": 5, "malzahar_damage": 30000}}
assert status(baron, "Baron Nashor")["status"] == "PROGRESS"
baron["counters"]["malzahar_damage"] = 60000
assert status(baron, "Baron Nashor")["status"] == "READY"
# Trait panel stands in for the board (HUD can't see units): lower bounds, solo traits excluded
panel = [{"name": "Beach Pop", "count": 2, "active": False}, {"name": "Collab", "count": 3, "active": True},
         {"name": "Ionic Spark", "count": 3, "active": True}, {"name": "Country", "count": 1, "active": True}]
r = status({"level": 5, "traits": panel}, "Zac")
assert r["status"] == "PROGRESS" and r["value"] == 2 and "trait panel" in r["detail"], r
assert status({"traits": panel}, "Smeech")["value"] == 2          # Collab counts, solo Country doesn't
# Owned units (purchase bookkeeping, no board): Aphelios from Yone copies; Kobuko's items unseen;
# Xayah owned but no Gu Feng/Hitmaker on the panel -> benched, so the Gu Feng counters are paused
owned = {"owned": [{"unit": "Yone", "copies": 3, "stars": 2}, {"unit": "Ziggs", "copies": 3, "stars": 2},
                   {"unit": "Xayah", "copies": 1, "stars": 1}],
         "traits": [{"name": "Heartsteel", "count": 1, "active": True}, {"name": "Hyperpop", "count": 1, "active": False},
                    {"name": "Slayer", "count": 1, "active": False}],
         "counters": {"xayah_ally_damage": 0}}
assert status(owned, "Aphelios")["status"] == "READY"
r = status(owned, "Kobuko")
assert r["status"] == "UNKNOWN" and "can't see its items" in r["detail"], r
assert "paused: Xayah not fielded" in status(owned, "Wukong")["detail"]

# star badges on the board's bars set the inferred board's stars (likeliest units first)
from unlocks import infer_board  # noqa: E402
bars = [{"x": 0.4, "y": 0.3, "w": 0.03, "h": 0.004, "items": [], "stars": 2}, {"x": 0.5, "y": 0.3, "w": 0.03, "h": 0.004, "items": [], "stars": 1}]
b, _ = infer_board(S19, {"traits": [{"name": "Beach Pop", "count": 2, "active": False}], "level": 2, "owned": [], "units": bars, "unlocked": []})
assert sorted(x["stars"] for x in b) == [1, 2], b
print("ok")
