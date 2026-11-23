# Harvest labelled item icons from item tooltips in a recorded VOD: the tooltip's title is the item name
# (OCR, already in rows.jsonl.gz) and its icon sits just left of the title. Each hit becomes a real in-game
# crop under data/raw/labels/items/<item>/ (gitignored: game art), for training and checking the classifier.
#
#   python3 -I tools/harvest_items.py RECORDING_DIR VIDEO.mp4 [--speed 2]
import argparse
import difflib
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine")]
from unlocks import load_set  # noqa: E402

OUT = ROOT / "data/raw/labels/items"
ICON = 3.3          # tooltip icon side, in title-text heights
GAP = 0.55          # gap between icon and title, in title-text heights


def item_names():
    names = {e["name"] for e in json.loads((ROOT / "data/raw/cdragon/items/index.json").read_text())}
    names |= {f"{t['name']} Emblem" for t in load_set("TFTSet19")["traits"]}       # Set 19 emblems
    traits = {t["name"].lower() for t in load_set("TFTSet19")["traits"]}
    return {n.lower(): n for n in names if n.lower() not in traits}                # "Ionic Spark" is also a trait


def hits(rows_path, names, min_gap=20):
    last, out = {}, []
    for line in gzip.open(rows_path, "rt"):
        f = json.loads(line)
        for r in f["rows"]:
            t = r["text"].strip()
            if not 4 <= len(t) <= 30 or r["h"] < 0.017:
                continue
            m = difflib.get_close_matches(t.lower(), list(names), n=1, cutoff=0.86)
            if m and f["t"] - last.get(m[0], -1e9) > min_gap:
                out.append((f["t"], names[m[0]], r))
            if m:
                last[m[0]] = f["t"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("video")
    ap.add_argument("--speed", type=float, default=1.0)
    a = ap.parse_args()
    rec = Path(a.recording)
    W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", a.video],
                                   capture_output=True, text=True, check=True).stdout.strip().split(","))
    tag = rec.name[:24].replace(" ", "_") + f"_{H}p"
    n = 0
    for t, name, r in hits(rec / "rows.jsonl.gz", item_names()):
        # rows are game coordinates; full-frame VODs map them onto the video as is
        h = r["h"] * H
        side = round(ICON * h)
        x1 = r["x"] * W - GAP * h
        y0 = r["y"] * H - 0.55 * h
        d = OUT / name.replace("/", "-")
        d.mkdir(parents=True, exist_ok=True)
        dst = d / f"{tag}_{int(t)}.png"
        crop = f"crop={side}:{side}:{max(0, round(x1 - side))}:{max(0, round(y0))}"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t / a.speed:.2f}", "-i", a.video,
                        "-frames:v", "1", "-vf", crop, str(dst)], check=True)
        n += 1
    print(f"{n} tooltip icons -> {OUT}")


if __name__ == "__main__":
    main()
