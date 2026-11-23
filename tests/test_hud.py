# HUD reader on a real Set 19 PBE frame (letterboxed video frame), plus parser cases without OCR.
#   python3 -I tests/test_hud.py      (compiles capture/tftcap on first run, ~1 minute)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "tests/fixtures/pbe_set19_3-1.png").exists():      # a PBE game screenshot: kept private (player names)
    print("skip: needs tests/fixtures/pbe_set19_3-1.png (a private game screenshot)")
    sys.exit()
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine")]
from hud import counter_targets, ocr, read, read_tracker  # noqa: E402
from unlocks import load_set  # noqa: E402

S19 = load_set("TFTSet19")
ROSTER, TRAITS = [u["name"] for u in S19["units"]], S19["traits"]

got = read(ocr(ROOT / "tests/fixtures/pbe_set19_3-1.png"), ROSTER, TRAITS)
want = {"t": "3-1", "level": 5, "xp": [2, 20], "gold": 44, "streak_n": 3, "board_count": [6, 6], "hp": 83}
assert {k: got[k] for k in want} == want, {k: got[k] for k in want}
assert [s["unit"] for s in got["shop"]] == ["Kayn", "Lucian", "Camille", "Taric", "Taric"], got["shop"]
assert got["odds"][:3] == [45, 33, 20] and got["odds"][4] == 0          # matches the level-5 table
traits = {t["name"]: t for t in got["traits"]}
assert {n: (t["count"], t["active"]) for n, t in traits.items()} == {
    "Collab": (3, True), "Ionic Spark": (3, True), "Choreographer": (2, True), "Frontman": (2, True),
    "Beach Pop": (2, False), "Classical": (1, False), "Prodigy": (1, False), "Slayer": (1, False),
    "Swiftstriker": (1, False)}, traits
assert traits["Collab"]["count_is_lower_bound"]                        # its count sits inside the icon
assert got["quality"]["unread"] == []


def box(text, x, y):
    return {"text": text, "x": x, "y": y, "w": 0.02, "h": 0.02, "conf": 1}


# a lobby HP must not be taken for gold; missing fields are reported, never guessed
got = read([box("71", 0.95, 0.80), box("2 3-2", 0.385, 0.008), box("Level 8", 0.18, 0.79)], ROSTER, TRAITS)
assert got["gold"] is None and got["level"] == 8 and got["t"] == "3-2"
assert {"gold", "xp", "hp"} <= set(got["quality"]["unread"])

# Unlock tracker lines: matched by threshold + wording, never from HUD regions
targets = counter_targets(S19["unlocks"])
assert targets["xayah_ally_damage"] == 25000 and targets["hype"] == 900 and targets["rerolls_before_2_carousel"] == 4
rows = [box("14,000/25,000", 0.80, 0.40), box("Allies deal damage while fielding Xayah", 0.80, 0.42),
        box("312/900 Hyperpop Hype", 0.80, 0.50),
        box("2/20", 0.24, 0.79),                    # XP line: same shape, must be ignored
        box("1/2", 0.06, 0.50),                     # trait panel
        box("3/5 Collab", 0.80, 0.60)]              # 5 is no counter's threshold with that wording
assert read_tracker(rows, targets) == {"xayah_ally_damage": 14000, "hype": 312}, read_tracker(rows, targets)

# real-VOD fixes: the coin icon read as a leading digit; implausible trait counts dropped
got = read([box("230", 0.52, 0.795), box("2 3-5", 0.385, 0.008), box("Lvl. 7", 0.18, 0.79)], ROSTER, TRAITS)
assert got["gold"] == 30, got["gold"]
# the coin glyph: separate (certain), fused onto digits ("94": 4 or 94, both offered), or read as a lone
# digit in a coin-wide box (dropped; the narrow "6" beside it wins)
from hud import read_gold  # noqa: E402
assert read_gold([box("94", 0.524, 0.797)]) == (94, 4) and read_gold([box("9 46", 0.522, 0.797)]) == (46, None)
assert read_gold([box("230", 0.52, 0.795)]) == (30, None)
assert read_gold([dict(box("9", 0.531, 0.824), w=0.0131, h=0.0159, zoom=True),
                  dict(box("6", 0.533, 0.824), w=0.0073, h=0.0155)]) == (6, None)
from hud import plausible_traits  # noqa: E402
tr = plausible_traits([{"name": "Juggernaut", "count": 1910, "active": True}, {"name": "K/DA", "count": 13, "active": True}], S19)
assert tr[0]["count"] is None and tr[1]["count"] == 13            # K/DA counts star levels: 13 is possible
from hud import loose_match  # noqa: E402
NAMES = [t["name"] for t in TRAITS]
assert loose_match("JorlcSpark", NAMES) == ["Ionic Spark"] and loose_match("1/2", NAMES) == []   # 720p VOD misread
# a loose shop name must agree with the traits printed on its card ("onar" over Trickshot is not Sona)
card = [box("Trickshot", 0.31, 0.91), box("onar", 0.29, 0.94), box("2 3-5", 0.385, 0.008), box("Lvl. 5", 0.18, 0.79)]
assert read(card, S19["units"], TRAITS)["shop"] == [], read(card, S19["units"], TRAITS)["shop"]
assert read(card[:1] + [box("Sona", 0.29, 0.94)] + card[2:], S19["units"], TRAITS)["shop"][0]["unit"] == "Sona"
# active traits are listed first: an unread count above a known-active trait still means active
from hud import read_traits  # noqa: E402
tr = {x["name"]: x for x in read_traits([box("lonic Spark", 0.07, 0.24), box("2 Frontman", 0.07, 0.29),
                                         box("Encore", 0.07, 0.34), box("1/2", 0.07, 0.36)], TRAITS)}
assert tr["Ionic Spark"]["active"] and tr["Ionic Spark"]["count"] == 3 and tr["Ionic Spark"]["count_is_lower_bound"]
assert tr["Encore"]["active"] is False

# the Augments panel: held augments in order under the header; other text on screen is ignored
from hud import read_held_augments  # noqa: E402
rows = [box("Augments", 0.358, 0.18), box("Silver Destiny", 0.359, 0.26), box("Bundle o' Shrooms", 0.36, 0.35),
        box("Missed Connections", 0.359, 0.44), box("Beach Pop", 0.07, 0.25), box("robinsongz", 0.17, 0.33)]
assert read_held_augments(rows) == ["Silver Destiny", "Bundle o' Shrooms", "Missed Connections"]
assert read_held_augments(rows[1:]) == []

# other players' HP from the player list: name and number on one line; the zoomed re-read wins for small digits
from hud import read_lobby  # noqa: E402
rows = [box("dmhmakPBE1", 0.892, 0.261), box("89", 0.954, 0.261), box("Meneyota", 0.907, 0.408),
        box("6", 0.946, 0.408), dict(box("8", 0.946, 0.409), zoom=True), box("Noightmare", 0.901, 0.630),
        box("103", 0.926, 0.178)]                                     # your own HP has no name beside it
assert read_lobby(rows) == {"dmhmakPBE1": 89, "Meneyota": 8}
assert read_lobby(rows + [box("Damage Dealt", 0.83, 0.25)]) == {}  # end-of-combat chart over the list
# the trait panel's "N+" badge (planning) and "+N" (collapsed in combat): traits it can't fit
from hud import trait_badge  # noqa: E402
R = lambda t, x=0.03, y=0.67: {"text": t, "x": x, "y": y, "w": 0.01, "h": 0.02}   # noqa: E731
assert trait_badge([R("2+")]) == 2 and trait_badge([R("+9", y=0.68)]) == 9
assert trait_badge([R("+109", y=0.45)]) == 0 and trait_badge([R("2+", x=0.5)]) == 0 and trait_badge([]) == 0
# player list (checked on 44 hand-read frames): HP fused onto the name is split off (2+ digits only: names end
# in digits too), the enlarged column's name tails ("Woo" -> "00") are skipped, the late-game shift is read
from hud import read_lobby, read_gold  # noqa: E402
L = lambda t, x, y, w=0.01, zoom=False: {"text": t, "x": x, "y": y, "w": w, "h": 0.012, **({"zoom": True} if zoom else {})}   # noqa: E731
lob = read_lobby([L("Meneyota 42", 0.9124, 0.32, 0.0572), L("LooptheLoop40", 0.9021, 0.40, 0.0675),
                  L("DripGodWoo", 0.9007, 0.47, 0.0499), L("00", 0.9407, 0.471, zoom=True), L("90", 0.9609, 0.47, zoom=True),
                  L("Noctuss 3", 0.9135, 0.54, 0.0346), L("dmhmakPBE1", 0.9136, 0.61, 0.0524), L("0", 0.9774, 0.611, 0.0043, zoom=True)])
assert lob == {"Meneyota": 42, "LooptheLoop": 40, "DripGodWoo": 90, "dmhmakPBE1": 0}, lob
# gold: the enlarged read (coin left out) beats a coin-fused "998", but not a separated plain read
G = lambda t, x, zoom=False, w=0.016: {"text": t, "x": x, "y": 0.798, "w": w, "h": 0.016, **({"zoom": True} if zoom else {})}   # noqa: E731
assert read_gold([G("998", 0.5208, w=0.0249), G("28", 0.5301, zoom=True)]) == (28, None)
assert read_gold([G("2 6", 0.5271, w=0.0195), G("9", 0.5361, zoom=True, w=0.0107)]) == (6, None)
assert read_gold([G("2", 0.5361, zoom=True, w=0.0128)]) == (2, None)
print("ok")
