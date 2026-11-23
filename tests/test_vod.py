# VODs: game found by HUD landmarks in a stream layout, webcam masked, landmark fallback, compact storage,
# and (if ffmpeg exists) a real video through the recorder's VOD path, then replayed from stored OCR rows.
#   python3 -I tests/test_vod.py
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / "tests/fixtures/pbe_set19_3-1.png").exists():      # a PBE game screenshot: kept private (player names)
    print("skip: needs tests/fixtures/pbe_set19_3-1.png (a private game screenshot)")
    sys.exit()
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine")]
from hud import locate, ocr, read  # noqa: E402
from record import Recorder, replay_frames, round_rows, vod_frames  # noqa: E402
from unlocks import load_set  # noqa: E402

S = load_set("TFTSet19")
R, T = [u["name"] for u in S["units"]], [t["name"] for t in S["traits"]]
WANT = {"t": "3-1", "level": 5, "xp": [2, 20], "gold": 44, "board_count": [6, 6]}
FIX = ROOT / "tests/fixtures/pbe_set19_3-1.png"
game_rows = ocr(FIX)

# 1. Stream layout without video: game scaled to 70% at an offset, plus a webcam with HUD-like text
k, ox, oy = 0.7, 0.05, 0.12
frame = [dict(r, x=r["x"] * k + ox, y=r["y"] * k + oy, w=r["w"] * k, h=r["h"] * k) for r in game_rows]
webcam = (0.78, 0.55, 0.99, 0.95)
frame += [{"text": "Lvl. 9", "x": 0.80, "y": 0.90, "w": 0.04, "h": 0.02, "conf": 1},   # overlay text that
          {"text": "88", "x": 0.85, "y": 0.70, "w": 0.02, "h": 0.02, "conf": 1}]       # would fool the reader
tf = locate([r for r in frame if not (0.78 <= r["x"] <= 0.99 and 0.55 <= r["y"] <= 0.95)])
assert tf and abs(tf[0] - 1 / k) < 0.03 and abs(tf[2] - 1 / k) < 0.03, tf
got = read(frame, R, T, masks=[webcam])
assert {k_: got[k_] for k_ in WANT} == WANT, {k_: got[k_] for k_ in WANT}
assert [s["unit"] for s in got["shop"]] == ["Kayn", "Lucian", "Camille", "Taric", "Taric"]

# 2. Landmarks hidden this frame (webcam over the level text): the last mapping is reused
hidden = [r for r in frame if "Lvl" not in r["text"]]
got2 = read(hidden, R, T, masks=[webcam], transform=got["quality"]["transform"])
assert got2["gold"] == 44 and got2["t"] == "3-1", got2

# 3. Storage: rounded OCR rows of one frame gzip to about a kilobyte
packed = len(gzip.compress(json.dumps({"t": 0, "rows": round_rows(game_rows)}).encode()))
assert packed < 2500, packed

# 4. Real video (needs ffmpeg): stream layout + webcam box, read by the VOD path, then replayed
if shutil.which("ffmpeg"):
    tmp = Path(tempfile.mkdtemp())
    try:
        vid = tmp / "stream.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(FIX), "-t", "4", "-vf",
                        "scale=1440:-2,pad=1920:1080:60:100:color=0x3a2a5a,"
                        "drawbox=x=1290:y=240:w=440:h=420:color=0x9a7a5a:t=fill",
                        "-r", "1", "-pix_fmt", "yuv420p", str(vid)], check=True)
        rows_log = []
        rec, tfm = Recorder({u["name"]: u["cost"] for u in S["units"]}), None
        for ts, rows, _units, _held in vod_frames(vid, 2, None, None):
            rows_log.append({"t": ts, "rows": round_rows(rows)})
            r = read(rows, R, T, masks=[(0.67, 0.22, 0.9, 0.61)], transform=tfm)
            tfm = r["quality"]["transform"] or tfm
            rec.feed(r, ts)
        state = rec.close()
        assert {k_: state[k_ if k_ != "t" else "stage"] for k_ in WANT} == WANT, state
        with gzip.open(tmp / "rows.jsonl.gz", "wt") as f:
            f.writelines(json.dumps(x) + "\n" for x in rows_log)
        rec2 = Recorder({u["name"]: u["cost"] for u in S["units"]})
        for ts, rows, _units, _held in replay_frames(tmp / "rows.jsonl.gz"):
            rec2.feed(read(rows, R, T, masks=[(0.67, 0.22, 0.9, 0.61)]), ts)
        assert rec2.close()["gold"] == 44                          # re-parsed from stored text, no video
    finally:
        shutil.rmtree(tmp)
else:
    print("ffmpeg not found: skipped the real-video part")
print("ok")
