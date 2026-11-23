# Harvest labelled pictures of champion models from a recorded VOD (rows.jsonl.gz with "units", i.e. recorded
# with the item model present), for learning what every Set 19 unit looks like. Labels come from the game:
#   buy:      the shop ledger books a purchase and a new health bar appears in the bench row -> that unit
#   tooltip:  an item tooltip names its holder ("Zac") and opens beside the hovered slot -> that slot's unit
# Crops go to data/raw/labels/units/<Champion>/ (gitignored: game art).
#
#   python3 -I tools/harvest_units.py RECORDING_DIR VIDEO.mp4 [--speed 2]
import argparse
import difflib
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine")]
from hud import centre, plausible_traits, read  # noqa: E402
from record import Recorder  # noqa: E402
from unlocks import load_set  # noqa: E402

OUT = ROOT / "data/raw/labels/units"
BENCH_Y = 0.6          # bars below this (game fraction) are on the bench


def unit_box(u, W, H):
    """Pixel box of the champion model under a health bar (u: game fractions; the bar width sets the scale)."""
    ref = u["w"] * W
    x0, y1 = u["x"] * W, (u["y"] + u["h"]) * H
    return round(x0 - 0.2 * ref), round(y1 + 0.6 * ref), round(1.6 * ref), round(1.9 * ref)


def slots(u, W, H):
    ref = u["w"] * W
    s, left, top = 0.405 * ref, u["x"] * W - 0.19 * ref, (u["y"] + u["h"]) * H + 0.143 * ref
    return [(left + k * s + s / 2, top + s / 2) for k in range(3)]


def frames(path):
    with gzip.open(path, "rt") as f:
        try:
            for line in f:
                d = json.loads(line)
                yield d["t"], d["rows"], d.get("units") or []
        except (EOFError, json.JSONDecodeError):          # a recording still being written: use what's there
            return


def bench(units):
    return [u for u in units if u["y"] >= BENCH_Y]


BENCH_X0, BENCH_DX = 0.203, 0.0627    # bench slot 1's bar x and the spacing (game fractions), 9 slots


def bench_slots(units):
    """{slot index: bar} for bars on the bench row."""
    out = {}
    for u in units:
        k = round((u["x"] - BENCH_X0) / BENCH_DX)
        if u["y"] >= BENCH_Y and 0 <= k < 9 and abs(u["x"] - (BENCH_X0 + k * BENCH_DX)) < 0.015:
            out[k] = u
    return out


def occupied(fr, t0, t1):
    """Bench slots occupied in most readings between t0 and t1 (bars flicker behind the cursor and
    animations; bench bars aren't drawn in combat, so callers keep the window inside one planning phase)."""
    win = [bench_slots(u) for t, _, u in fr if t0 <= t <= t1 and u]
    return {k for k in range(9) if win and sum(k in w for w in win) * 2 > len(win)} if win else None


def buy_labels(static, fr):
    """(time, unit, bar) for purchases: a bought unit lands in the leftmost empty bench slot, so after each
    purchase the newly filled slots, left to right, belong to the units bought in that burst, in order."""
    rec = Recorder({u["name"]: u["cost"] for u in static["units"]}, {u["unit"] for u in static["unlocks"]})
    rec.trait_info = {t["name"]: t for t in static["traits"]}
    buys, now = [], {"t": 0}
    orig = rec._buy
    rec._buy = lambda unit: (buys.append((now["t"], unit)), orig(unit))
    for t, rows, _ in fr:
        now["t"] = t
        r = read(rows, static["units"], static["traits"])
        plausible_traits(r["traits"], static)
        rec.feed(r, t)
    times = [t for t, _, _ in fr]
    idx = lambda t: min(range(len(times)), key=lambda i: abs(times[i] - t))   # noqa: E731
    out, i = [], 0
    while i < len(buys):                                   # bursts: buys booked within 3 s of each other
        j = i
        while j + 1 < len(buys) and buys[j + 1][0] - buys[j][0] <= 3:
            j += 1
        burst = buys[i:j + 1]
        tb0, tb1 = burst[0][0], burst[-1][0]
        before = occupied(fr, tb0 - 4, tb0 - 2)            # a buy is booked 2 readings after its card vanished
        k_after = idx(tb1 + 2)
        after = occupied(fr, tb1, tb1 + 3)
        new = sorted(after - before) if before is not None and after is not None else []
        leftmost = [k for k in range(9) if k not in (before or set())][:len(burst)]
        # the game puts a bought unit in the leftmost empty slot: anything else (a merge into a 2-star, a unit
        # dragged straight to the board) means the new bars aren't the purchases
        # cards that vanished in the same reading were bought in an unknown order: only assign if they're the
        # same champion
        tied = lambda m: any(o != m and burst[o][0] == burst[m][0] and burst[o][1] != burst[m][1]   # noqa: E731
                             for o in range(len(burst)))
        if new and new == leftmost and len(new) == len(burst) and not (before - after):
            for m, ((tb, unit), k) in enumerate(zip(burst, new)):
                if tied(m):
                    continue
                bar = bench_slots(fr[k_after][2]).get(k) or next((bench_slots(u)[k] for _, _, u in fr[k_after:k_after + 3]
                                                                  if k in bench_slots(u)), None)
                if bar:
                    out.append((fr[k_after][0], unit, bar, "buy"))
        i = j + 1
    return out


def tooltip_labels(static, fr, W, H):
    """(time, unit, bar) from item tooltips that name their holder, linked to the hovered slot's bar."""
    names = {e["name"].lower(): e["name"] for e in json.loads((ROOT / "data/raw/cdragon/items/index.json").read_text())}
    names |= {f"{t['name']} Emblem".lower(): f"{t['name']} Emblem" for t in static["traits"]}
    items = set(names)
    roster = [u["name"] for u in static["units"]]
    out, prev_units, prev_t = [], [], None
    for t, rows, units in fr:
        for r in rows:
            if r["h"] < 0.017 or not difflib.get_close_matches(r["text"].strip().lower(), items, n=1, cutoff=0.86):
                continue
            cx, cy = centre(r)
            holder = [x for x in rows if 0.04 < centre(x)[1] - cy < 0.16 and abs(x["x"] - r["x"]) < 0.08
                      and difflib.get_close_matches(x["text"].strip(), roster, n=1, cutoff=0.9)]
            if len(holder) != 1:
                continue
            name = difflib.get_close_matches(holder[0]["text"].strip(), roster, n=1, cutoff=0.9)[0]
            item = names[difflib.get_close_matches(r["text"].strip().lower(), items, n=1, cutoff=0.86)[0]]
            h = r["h"] * H
            icon_left, icon_top = r["x"] * W - 3.85 * h, r["y"] * H - 0.55 * h
            p = (icon_left - 0.008 * W, icon_top + 0.006 * H)        # the hovered slot sits at the tooltip's corner
            # the holder's bar must carry that item (item reader) and sit by the tooltip's corner
            cands = [(min(((sx - p[0]) ** 2 + (sy - p[1]) ** 2) ** 0.5 for sx, sy in slots(u, W, H)), u)
                     for u in prev_units or units if item in [x[0] for x in u.get("items", [])]]
            cands = [c for c in cands if c[0] < 0.06 * W]
            if len(cands) == 1:
                # crop from the reading before the tooltip opened: the tooltip covers the unit
                out.append((prev_t if prev_units else t, name, min(cands, key=lambda c: c[0])[1], "tooltip"))
        if units and not any(r["h"] >= 0.017 and difflib.get_close_matches(r["text"].strip().lower(), items, n=1, cutoff=0.86)
                             for r in rows):
            prev_units, prev_t = units, t                              # last reading with no item tooltip open
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("video")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    rec = Path(a.recording)
    static = load_set("TFTSet19")
    W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", a.video],
                                   capture_output=True, text=True, check=True).stdout.strip().split(","))
    fr = list(frames(rec / "rows.jsonl.gz"))
    labels = buy_labels(static, fr) + tooltip_labels(static, fr, W, H)
    tag = rec.name[:12].replace(" ", "_") + f"_{H}p"
    seen = set()
    for t, name, u, src in labels:
        key = (name, round(u["x"], 2), round(u["y"], 2), int(t // 30))        # one crop per unit, spot and half-minute
        if key in seen:
            continue
        seen.add(key)
        x, y, w, h = unit_box(u, W, H)
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t / a.speed:.2f}", "-i", a.video, "-frames:v", "1",
                        "-vf", f"crop={w}:{h}:{max(0, x)}:{max(0, y)}", str(d / f"{tag}_{int(t)}_{src}_{int(u['x'] * 1000)}.png")],
                       check=True)
    from collections import Counter
    c = Counter(src for *_, src in labels)
    print(f"{len(seen)} labelled unit crops ({dict(c)}) -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
