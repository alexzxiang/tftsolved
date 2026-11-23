"""Read the TFT HUD from one frame (PNG) via capture/tftcap OCR.

    python3 -I capture/hud.py frame.png [TFTSet19]        # -> JSON
    capture/tftcap shot frame.png && python3 -I capture/hud.py frame.png

Reads: stage, level, XP, gold, streak length, shop odds, board count, the five shop slots, the trait
panel (name, count, breakpoints), your HP and the lobby HP list. tftcap crops letterbox bars first, so
regions are fractions of the game area. LAYOUT is calibrated on a Set 19 PBE frame (16:9,
tests/fixtures/pbe_set19_3-1.png). Anything not found is listed in quality.unread, never guessed.
"""
import difflib
import functools
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
from unlocks import load_set  # noqa: E402

TOOL = HERE / "tftcap"
LAYOUT = {   # (x0, y0, x1, y1) as fractions of the game area
    "calibrated": "Set 19 PBE, 16:9, 2026-11-18",
    "stage": (0.33, 0.00, 0.46, 0.05),
    "level": (0.15, 0.77, 0.23, 0.82),
    "xp": (0.23, 0.77, 0.275, 0.82),
    "odds": (0.27, 0.77, 0.46, 0.82),
    "gold": (0.50, 0.77, 0.57, 0.83),
    "streak": (0.575, 0.77, 0.62, 0.83),
    "board": (0.38, 0.15, 0.62, 0.32),
    "shop": (0.27, 0.925, 0.83, 0.97),
    "traits": (0.04, 0.22, 0.15, 0.72),
    "lobby": (0.87, 0.14, 0.97, 0.75),
}
SHOP_X0, SHOP_DX = 0.285, 0.105        # left edge of slot 1 and card width
ODDS_X0, ODDS_DX = 0.299, 0.031        # centre of the 1-cost % and spacing to the next
SELF_HP_X = (0.925, 0.965)             # your HP's centre x (late game the list shifts right ~0.01); other
                                       # players' HPs overlap it, but their line has a name on it
SELF_HP_MIN_H = 0.015                  # your HP is 0.015-0.022 tall; smaller digits nearby are other text


def ocr(png):
    if not TOOL.exists():
        subprocess.run(["swiftc", "-O", "-parse-as-library", str(HERE / "tftcap.swift"), str(HERE / "units.swift"),
                        "-o", str(TOOL)], check=True)
    out = subprocess.run([str(TOOL), "ocr", str(png)], capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def centre(r):
    return r["x"] + r["w"] / 2, r["y"] + r["h"] / 2


def inside(r, region):
    cx, cy = centre(r)
    x0, y0, x1, y1 = region
    return x0 <= cx <= x1 and y0 <= cy <= y1


# Unlock tracker ("x/N description", as in the game's own Set 16 strings). Layout not seen yet for Set 19,
# so lines are matched anywhere outside the HUD regions: N must equal the unlock's threshold AND the line
# (or the one under it) must name what is counted.
TRACKER_WORDS = {
    "hyperpop_casts": r"cast", "hyperpop_kills": r"kill", "captivated_seconds": r"captivat",
    "xayah_ally_damage": r"damage", "xayah_interest": r"interest", "xayah_player_damage": r"player damage",
    "ionic_cheers": r"cheer", "hype": r"hype", "bling": r"bling", "collab_inspires": r"inspire",
    "instruments": r"instrument|ensemble|member", "malzahar_damage": r"damage|malzahar",
    "rock_combats": r"rock|combat", "rerolls_before_2_carousel": r"reroll",
}
HUD_REGIONS = ("xp", "traits", "board", "level", "odds")


def counter_targets(unlocks):
    """counter name -> threshold, from the unlock rules."""
    out = {}

    def walk(w):
        (kind, a), = w.items()
        if kind == "all_of":
            for x in a:
                walk(x)
        elif kind == "counter":
            out[a["name"]] = a["n"]
        elif kind == "window":
            out[a["counter"]] = a["n"]
    for u in unlocks:
        if u.get("when"):
            walk(u["when"])
    return out


def read_tracker(rows, targets, layout=LAYOUT):
    found = {}
    free = [r for r in rows if not any(inside(r, layout[k]) for k in HUD_REGIONS)]
    for r in free:
        for m in re.finditer(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", r["text"]):
            v, n = (int(x.replace(",", "")) for x in m.groups())
            near = r["text"] + " " + " ".join(o["text"] for o in free
                                              if 0 < centre(o)[1] - centre(r)[1] < 0.03 and abs(o["x"] - r["x"]) < 0.1)
            for name, target in targets.items():
                if n == target and re.search(TRACKER_WORDS.get(name, r"$^"), near, re.I):
                    found[name] = v
    return found


# Two HUD landmarks with known places in the game area (from the calibrated frame). Finding them in a
# video frame gives the game's scale and offset, so streams that box the game in an overlay still read.
ANCHOR_STAGE, ANCHOR_LEVEL = (0.402, 0.018), (0.193, 0.804)


def masked(rows, masks):
    """Drop OCR rows whose centre lies in any mask rectangle (webcams, overlays), in frame fractions."""
    return [r for r in rows if not any(inside(r, m) for m in masks or ())]


def locate(rows):
    """(sx, ox, sy, oy) mapping frame -> game coordinates from the stage and level landmarks, or None."""
    stage = [r for r in rows if re.search(r"(?:^|\s)[1-8]\s*-\s*[1-7](?:\s|$)", r["text"]) and len(r["text"]) < 12]
    level = [r for r in rows if re.search(r"(?i)\blvl?\.?\s*\d{1,2}\b", r["text"])]
    if stage and not level:
        # full-screen game with the bottom HUD covered (augment choice, stage 1): the stage at its own
        # spot means no scaling
        s = centre(min(stage, key=lambda r: r["y"]))
        return (1.0, 0.0, 1.0, 0.0) if abs(s[0] - ANCHOR_STAGE[0]) < 0.015 and abs(s[1] - ANCHOR_STAGE[1]) < 0.015 else None
    if not stage or not level:
        return None
    s = centre(min(stage, key=lambda r: r["y"]))           # stage sits at the top of the HUD
    lv = centre(max(level, key=lambda r: r["y"]))
    if abs(lv[0] - s[0]) < 1e-3 or abs(lv[1] - s[1]) < 1e-3:
        return None
    sx = (ANCHOR_LEVEL[0] - ANCHOR_STAGE[0]) / (lv[0] - s[0])
    sy = (ANCHOR_LEVEL[1] - ANCHOR_STAGE[1]) / (lv[1] - s[1])
    if not (0.9 <= sx <= 4 and 0.9 <= sy <= 4 and 0.5 <= sx / sy <= 2):   # game fills 25%-110% of the frame
        return None
    return sx, ANCHOR_STAGE[0] - s[0] * sx, sy, ANCHOR_STAGE[1] - s[1] * sy


def to_game(rows, tf):
    if not tf:
        return rows
    sx, ox, sy, oy = tf
    out = []
    for r in rows:
        g = dict(r, x=r["x"] * sx + ox, y=r["y"] * sy + oy, w=r["w"] * sx, h=r["h"] * sy)
        if -0.02 <= g["x"] <= 1.02 and -0.02 <= g["y"] <= 1.02:
            out.append(g)
    return out


def read(rows, roster, traits=(), layout=LAYOUT, targets=None, masks=None, transform=None):
    """masks: frame rectangles to ignore. transform: last good frame->game mapping, used when this frame's
    landmarks are hidden. The mapping used is returned in quality.transform."""
    rows = masked(rows, masks)
    tf = locate(rows) or transform
    rows = to_game(rows, tf)
    def texts(field):
        return [r for r in rows if inside(r, layout[field])]

    def search(field, pattern):
        for r in sorted(texts(field), key=lambda r: r["y"]):
            m = re.search(pattern, r["text"])
            if m:
                return m
        return None

    out = {}
    m = search("stage", r"([1-8])\s*-\s*([1-7])")
    out["t"] = f"{m[1]}-{m[2]}" if m else None
    m = search("level", r"(?i)(?:lvl?\.?|level)\s*(\d{1,2})")
    out["level"] = int(m[1]) if m else None
    m = search("xp", r"(\d{1,3})\s*/\s*(\d{1,3})")
    out["xp"] = [int(m[1]), int(m[2])] if m else None
    out["gold"], out["gold_alt"] = read_gold(texts("gold"))
    if out["level"] is None and out["xp"] is None:    # no HUD bar (scouting, item choice, combat camera):
        out["gold"] = out["gold_alt"] = None           # what's in the gold box is board text (3 of 44 frames)
    m = search("streak", r"(\d{1,2})\s*$")
    out["streak_n"] = int(m[1]) if m else None
    odds = [None] * 5                                # placed by x: a missed value can't shift the rest
    for r in texts("odds"):
        for pct in re.findall(r"(\d{1,3})\s*%", r["text"]):
            i = round((centre(r)[0] - ODDS_X0) / ODDS_DX)
            if 0 <= i < 5:
                odds[i] = int(pct)
    out["odds"] = odds if any(o is not None for o in odds) else None
    m = search("board", r"(\d{1,2})\s*/\s*(\d{1,2})\s*$")
    out["board_count"] = [int(m[1]) % 10 if int(m[1]) > int(m[2]) else int(m[1]), int(m[2])] if m else None

    out["shop"] = []
    unit_traits = {u["name"]: set(u["traits"]) for u in roster if isinstance(u, dict)}
    roster = [u if isinstance(u, str) else u["name"] for u in roster]
    trait_names = [x if isinstance(x, str) else x["name"] for x in traits]
    for r in texts("shop"):
        text = r["text"].strip()
        name = difflib.get_close_matches(text, roster, n=1, cutoff=0.75)
        slot = int((centre(r)[0] - SHOP_X0) // SHOP_DX) + 1
        if name and unit_traits and difflib.SequenceMatcher(None, text, name[0]).ratio() < 0.9:
            # a loose name match must agree with the traits printed on the card above it ("onar" isn't Sona)
            card = {m for c in rows if 0.01 < centre(r)[1] - centre(c)[1] < 0.07
                    and int((centre(c)[0] - SHOP_X0) // SHOP_DX) + 1 == slot
                    for m in loose_match(re.sub(r"^\W*\d*\s*", "", c["text"]), trait_names)}
            if card and not card & unit_traits.get(name[0], set()):
                name = []
        if name and 1 <= slot <= 5:
            out["shop"].append({"slot": slot, "unit": name[0]})
    out["shop"].sort(key=lambda s: s["slot"])

    out["traits"] = read_traits(texts("traits"), list(traits))
    out["traits_hidden"] = trait_badge(rows)
    lob = texts("lobby")
    hps = [r for r in lob if not r.get("zoom") and re.fullmatch(r"[1-9]\d{0,2}", r["text"].strip())
           and int(r["text"]) <= 150]                                     # some effects lift HP past 100
    # your HP: the tallest number in its own narrow column; a "left of the median" rule confused it with
    # ability tooltips ("30/25/25") at 720p, where other players' HPs are often unread
    named = [n["y"] for n in lobby_names(rows)]
    band = [r for r in hps if SELF_HP_X[0] <= centre(r)[0] <= SELF_HP_X[1] and r["h"] >= SELF_HP_MIN_H
            and not any(abs(r["y"] - y) < 0.012 for y in named)]
    mine = sorted(band, key=lambda r: -r["h"])[:1]
    out["hp"] = int(mine[0]["text"]) if mine else None
    out["tracker"] = read_tracker(rows, targets, layout) if targets else {}
    out["augments"] = read_augments(rows)
    out["held_augments"] = read_held_augments(rows)
    out["lobby"] = read_lobby(rows)
    out["lobby_levels"] = read_lobby_levels(rows)
    out["item_offers"] = read_item_offers(rows)
    unread = [k for k in ("t", "level", "xp", "gold", "hp") if out[k] is None]
    out["quality"] = {"unread": unread, "layout": layout["calibrated"], "transform": tf}
    return out


def plausible_traits(found, static):
    """Drop impossible counts (more than the trait could hold): keep the trait as active with no count."""
    members = {x["name"]: sum(x["name"] in u["traits"] for u in static["units"]) for x in static["traits"]}
    stars = {x["name"] for x in static["traits"] if x.get("counts") == "stars"}
    for f in found:
        cap = members.get(f["name"], 9) * (3 if f["name"] in stars else 1)
        if f.get("count") is not None and f["count"] > max(cap, 1):
            f["count"] = None
            f["count_is_lower_bound"] = True
    return found


def loose_match(text, names, floor=0.65, lead=0.15):
    """Badly read names inside the trait panel ("JorlcSpark"): ignoring case and spaces, the best name
    if it is fairly close and clearly closer than any other."""
    key = lambda s: re.sub(r"\s", "", s).lower()          # noqa: E731
    k = key(text)
    if len(k) < 5:
        return []
    ranked = sorted(((difflib.SequenceMatcher(None, k, key(n)).ratio(), n) for n in names), reverse=True)
    best, second = ranked[0][0], (ranked[1][0] if len(ranked) > 1 else 0)
    return [ranked[0][1]] if best >= floor and best - second >= lead else []


GAME_ASPECT = 16 / 9
COIN_FREE_X = 0.527             # an enlarged gold read starting right of this left the coin out: digits only
LONE_DIGIT_ASPECT = 1.15        # a lone digit's box is ~0.85 wide per unit height; coin + digit is ~1.5+


def read_gold(rows):
    """(gold, alternative) beside the coin icon, from every reading of it (plain and enlarged). OCR reads the
    coin as a glyph:
      separate ("9 4", "• 35")  -> the last number, certain
      a lone digit              -> certain if digit-shaped; a coin-wide box may be the coin itself: dropped
      fused digits ("94")       -> 4 or 94 can't be told apart: both offered, the recorder picks by continuity
    The enlarged re-read leaves the coin out (it starts right of COIN_FREE_X), so its digits count too: below
    separated and digit-shaped plain reads (it reads 6 as 9), above fused ones ("998" for 28); it is often the
    only read of a lone 1-6. 150+ is never real gold."""
    certain, lone, zoomed, fused, ambiguous = [], [], [], [], []
    for r in sorted(rows, key=lambda r: r["y"]):
        m = re.search(r"(\d{1,3})\s*$", r["text"])
        if not m:
            continue
        digits, text = m[1], r["text"].strip()
        aspect = r["w"] / r["h"] * GAME_ASPECT if r.get("h") else 0
        if not re.fullmatch(r"\d+", text):
            certain.append(int(digits))
        elif r.get("zoom") and r["x"] >= COIN_FREE_X and int(digits) <= 150:
            zoomed.append(int(digits))
        elif len(digits) == 1:
            if aspect <= LONE_DIGIT_ASPECT:
                lone.append(int(digits))
        elif int(digits) > 150:
            fused.append(int(digits[1:]))
        else:
            ambiguous.append((int(digits), int(digits[1:])))
    for found in (certain, lone, zoomed, fused):
        if found:
            return max(set(found), key=found.count), None
    return ambiguous[0] if ambiguous else (None, None)


AUGMENT_TITLE_Y = (0.47, 0.515)       # card names on the "Choose One" screen (descriptions start ~0.53)
AUGMENT_COLS = (0.28, 0.50, 0.72)


def read_augments(rows):
    """Cards on the augment choice screen, left to right ({"name", "desc"}), or [] when it isn't showing.
    None for a card whose name wasn't read. The pick itself isn't shown."""
    if not any("choose one" in r["text"].lower() for r in rows):
        return []
    out, desc = [None] * 3, [[], [], []]
    for r in sorted(rows, key=lambda r: r["y"]):
        cx, cy = centre(r)
        text = r["text"].strip()
        i = min(range(3), key=lambda k: abs(cx - AUGMENT_COLS[k]))
        if abs(cx - AUGMENT_COLS[i]) >= 0.08:
            continue
        if AUGMENT_TITLE_Y[0] <= cy <= AUGMENT_TITLE_Y[1] and r["h"] >= 0.014 and 3 <= len(text) <= 32 \
                and not text.endswith(".") and any(c.isalpha() for c in text):
            out[i] = text.replace("#", "+")
        elif AUGMENT_TITLE_Y[1] < cy <= 0.68:
            desc[i].append(text)
    # a real card has effect text under its name (other "Choose One" screens show player names)
    cards = [{"name": n, "desc": " ".join(d)} if n and len(" ".join(d)) >= 10 else None for n, d in zip(out, desc)]
    return cards if any(cards) else []


def read_held_augments(rows):
    """The game's Augments panel (hovering the augment icons by a player's name): the held augments in the
    order they were gained, names left-aligned under an "Augments" header. [] when it isn't showing."""
    head = next((r for r in rows if r["text"].strip() == "Augments"), None)
    if not head:
        return []
    names = [r for r in rows if head["y"] + head["h"] < r["y"] < head["y"] + 0.4 and abs(r["x"] - head["x"]) < 0.03
             and r["h"] >= 0.012 and 3 <= len(r["text"].strip()) <= 32 and any(c.isalpha() for c in r["text"])]
    return [r["text"].strip().replace("#", "+") for r in sorted(names, key=lambda r: r["y"])]


LOBBY_NAME_X = (0.84, 0.935)       # other players' names, right column (game coordinates, left edge)
LOBBY_HP_X = (0.935, 0.988)         # their HP, on the same line, left of the level badge (~0.993); the list
                                    # shifts right ~0.013 late game


def read_lobby(rows):
    """Other players' HP from the player list on the right: {name: hp}. Your own row shows no name (its HP
    is read_hp's). Empty while the end-of-combat damage chart covers the list."""
    if any(r["text"].strip().endswith("Damage Dealt") and r["x"] > 0.75 for r in rows):
        return {}               # the chart's own title ("robinsongz Damage Dealt"), not an augment's text
    hps = [r for r in rows if LOBBY_HP_X[0] <= r["x"] <= LOBBY_HP_X[1] and r["text"].strip().isdigit()
           and int(r["text"]) <= 150]
    out = {}
    for n in lobby_names(rows):
        name, fused, end = split_name(n)
        # the enlarged column also catches the name's tail ("DripGodWoo" -> "00"): the HP starts past the
        # name's end, and is the rightmost number on the line
        near = [h for h in hps if abs(h["y"] - n["y"]) < 0.012 and h["x"] >= end - 0.003]
        near = [h for h in near if h.get("zoom")] or near        # the enlarged re-read wins for small digits
        if near:
            out[name] = int(max(near, key=lambda h: h["x"])["text"])
        elif fused is not None:
            out[name] = fused
    return out


def split_name(n):
    """(name, HP fused onto it or None, x where the name ends). OCR often fuses the HP onto the name
    ("Meneyota 42", "LooptheLoop40"): 2-3 digits are split off (a lone digit stays: names end in digits too,
    "dmhmakPBE1", and "Noctuss3" reads "Noctuss 3")."""
    text = re.sub(r"^[^\w]+\s*", "", n["text"].strip()) or n["text"].strip()   # "• Daby": a marker, not the name
    m = re.fullmatch(r"(.*?\D)\s*(\d{2,3})", text)
    name, fused = (m[1].strip(), int(m[2])) if m and int(m[2]) <= 150 else (text, None)
    return name, fused, n["x"] + n["w"] * len(name) / len(text)


LEVEL_BADGE_X = 0.985        # each portrait's level badge: right of the HP column, ~0.025 below the name line


def read_lobby_levels(rows):
    """Other players' levels from the small badges on their portraits: {name: level}."""
    badges = [r for r in rows if r["x"] >= LEVEL_BADGE_X and re.fullmatch(r"\d{1,2}", r["text"].strip())
              and 1 <= int(r["text"]) <= 11 and not r.get("zoom")]
    out = {}
    for n in lobby_names(rows):
        b = [x for x in badges if 0.012 < x["y"] - n["y"] < 0.045]
        if b:
            out[split_name(n)[0]] = int(min(b, key=lambda x: x["y"])["text"])
    return out


def lobby_names(rows):
    return [r for r in rows if LOBBY_NAME_X[0] <= r["x"] <= LOBBY_NAME_X[1] and 0.15 <= r["y"] <= 0.8
            and not r.get("zoom") and len(r["text"].strip()) >= 3 and any(c.isalpha() for c in r["text"])]


ITEM_OFFER_Y = (0.88, 0.935)          # item choices (artifacts, components, completed items) replace the shop


@functools.lru_cache(maxsize=1)
def item_names():
    """Item names CommunityDragon knows (components, completed, radiant, artifacts, emblems): {} without it."""
    f = Path(__file__).resolve().parent.parent / "data/raw/cdragon/items/index.json"
    return frozenset(e["name"] for e in json.loads(f.read_text())) if f.exists() else frozenset()


def read_item_offers(rows):
    """The cards of an item choice ("Aegis of Dusk", "Manazane", ...) left to right, when 2+ names show."""
    names = item_names()
    cards = sorted((r for r in rows if ITEM_OFFER_Y[0] <= r["y"] <= ITEM_OFFER_Y[1] and not r.get("zoom")
                    and (r["text"].strip() in names or difflib.get_close_matches(r["text"].strip(), names, 1, 0.88))),
                   key=lambda r: r["x"])
    out = [r["text"].strip() if r["text"].strip() in names else difflib.get_close_matches(r["text"].strip(), names, 1, 0.88)[0]
           for r in cards]
    return out if len(out) >= 2 else []


def trait_badge(rows):
    """Traits the panel can't fit: its "2+" badge (planning) or "+9" (collapsed in combat), else 0."""
    for r in rows:
        m = re.fullmatch(r"\s*\+\s*(\d{1,2})\s*|\s*(\d{1,2})\s*\+\s*", r["text"])
        if m and r["x"] < 0.07 and 0.55 < r["y"] < 0.76:
            return int(m[1] or m[2])
    return 0


def read_traits(rows, traits):
    """Trait panel: per trait a count (digit fused to the name, the hexagon digit beside it, or an inactive
    'n/m' line under it) and whether it's active. traits: names, or static trait dicts with breakpoints.
    The OCR'd breakpoint lines are cut off too often to trust; with breakpoints known, active = count >=
    first breakpoint. No count: active only if an 'a > b' line shows (inactive traits show 'n/m'), with the
    first breakpoint as a lower bound; otherwise present but unknown (active None)."""
    bps = {t["name"]: t.get("breakpoints") or [] for t in traits} if traits and isinstance(traits[0], dict) else {}
    names = list(bps) or list(traits)
    if not names:
        return []
    zoomed = [r for r in rows if r.get("zoom")]           # enlarged re-read: trusted for the count digits only
    rows = [r for r in rows if not r.get("zoom")]
    found = []
    for r in rows:
        text = re.sub(r"^\s*\d+\s*", "", r["text"])            # count fused onto the name ("2 Frontman")
        match = difflib.get_close_matches(text.replace("lonic", "Ionic"), names, n=1, cutoff=0.75) or \
            loose_match(text, names)
        if match and any(f["name"] == match[0] for f in found):
            continue                                       # a trait is listed once (a second read is noise)
        if match:
            lead = re.match(r"^\s*(\d+)\s", r["text"])
            found.append({"row": r, "name": match[0], "count": int(lead[1]) if lead else None})
    out = []
    for f in found:
        fy = centre(f["row"])[1]
        below = [r for r in rows if 0 < centre(r)[1] - fy < 0.03 and r["x"] >= f["row"]["x"] - 0.005]
        side = [r for r in zoomed + rows if abs(centre(r)[1] - fy) < 0.01 and centre(r)[0] < f["row"]["x"]
                and re.fullmatch(r"\d{1,2}|[Il|]", r["text"].strip())]          # a hexagon's 1 reads as I or l
        count = f["count"] if f["count"] is not None else \
            (int(side[0]["text"]) if side[0]["text"].strip().isdigit() else 1) if side else None
        line = " ".join(r["text"] for r in sorted(below, key=lambda r: r["x"]))
        under = [r for r in zoomed if 0 < centre(r)[1] - fy < 0.03 and r["x"] >= f["row"]["x"] - 0.005] + below
        inactive = next((m for r in under for m in [re.fullmatch(       # "1/2" also reads "112", "]/3", "I/1"
            r"\s*([\dIl|\]])\s*[/1l|]\s*(\d)\s*", r["text"])] if m), None) or \
            re.match(r"\s*(\d)\s*[/1l|]\s*(\d)\s*$", line)
        if inactive and count is None:
            count = int(inactive[1]) if inactive[1].isdigit() else 1
        first = (bps.get(f["name"]) or [None])[0]
        if count is not None:
            active = (count >= first) if first else not inactive
            out.append({"name": f["name"], "count": count, "active": active, "count_is_lower_bound": False})
        elif ">" in line and not inactive:                     # an active trait's breakpoint ladder
            out.append({"name": f["name"], "count": first, "active": True, "count_is_lower_bound": True})
        else:
            out.append({"name": f["name"], "count": None, "active": None, "count_is_lower_bound": True})
    # the panel lists active traits above inactive ones: an unknown trait above a known-active one is active
    # (count at least its first breakpoint); one below a known-inactive one is inactive
    ys = [centre(f["row"])[1] for f in found]
    for o, y in zip(out, ys):
        if o["active"] is None:
            if any(p["active"] for p, py in zip(out, ys) if py > y):
                o.update(active=True, count=(bps.get(o["name"]) or [None])[0])
            elif any(p["active"] is False for p, py in zip(out, ys) if py < y):
                o["active"] = False
    return out


if __name__ == "__main__":
    s = load_set(sys.argv[2] if len(sys.argv) > 2 else "TFTSet19")
    print(json.dumps(read(ocr(sys.argv[1]), [u["name"] for u in s["units"]], s["traits"],
                          targets=counter_targets(s["unlocks"])), indent=1))
