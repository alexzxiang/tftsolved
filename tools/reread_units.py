# Re-read only the units (health bars + items) of a recorded VOD with the current item model, and swap them
# into its rows.jsonl.gz (OCR text kept). Much faster than a full re-read when only the item model changed.
#   python3 -I tools/reread_units.py RECORDING_DIR VIDEO.mp4 [--speed 2] [--every 1]
import argparse
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "capture")]
from hud import TOOL  # noqa: E402
from record import ITEM_MODEL  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("video")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--every", type=float, default=1.0)
    a = ap.parse_args()
    path = Path(a.recording) / "rows.jsonl.gz"
    frames = [json.loads(x) for x in gzip.open(path, "rt") if x.strip()]
    by_t = {round(f["t"], 1): f for f in frames}
    cmd = [str(TOOL), "vod", a.video, "--every", str(a.every / a.speed), "--units", "--no-ocr", "--model", str(ITEM_MODEL)]
    n = 0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as p:
        for line in p.stdout:
            d = json.loads(line)
            f = by_t.get(round(d["t"] * a.speed, 1))
            if f is None:
                continue
            # units come in frame fractions; full-frame VODs map 1:1 (boxed streams: re-run record.py instead)
            f["units"] = [dict(u, items=[[x[0], round(x[1], 2)] for x in u["items"]],
                               **{k: round(u[k], 4) for k in ("x", "y", "w", "h")}) for u in d["units"]]
            n += 1
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", compresslevel=9) as out:
        for f in frames:
            out.write(json.dumps(f, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
    print(f"units re-read in {n} of {len(frames)} frames -> {path}")


if __name__ == "__main__":
    main()
