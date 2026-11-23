# Champion labels you confirm: crops of every unit (board and bench) once per round, grouped by look-alike,
# with suggested names, reviewed on a local page. Confirmed crops become the training labels
# (data/raw/labels/units/<Champion>/); a round check compares the labelled board with the game's trait panel.
#
#   python3 -I tools/label_units.py prepare RECORDING_DIR VIDEO.mp4 [--speed 2]   (once per recording)
#   python3 -I tools/label_units.py serve [--port 8765]                           then open http://127.0.0.1:8765
#   python3 -I tools/label_units.py regroup                                       (re-suggest after labelling)
#
# Everything stays on this machine (gitignored data/raw/labels/review); the server only listens on 127.0.0.1.
import argparse
import gzip
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "capture"), str(ROOT / "engine"), str(ROOT / "tools")]
from harvest_units import BENCH_Y  # noqa: E402
from hud import TOOL, read  # noqa: E402
from unlocks import infer_board, load_set  # noqa: E402

REVIEW = ROOT / "data/raw/labels/review"
UNITS = ROOT / "data/raw/labels/units"
LABELS = REVIEW / "labels.json"          # crop id -> champion name, or "__skip__" (not a unit / unusable)
META = REVIEW / "meta.json"
GROUP_DIST = 0.5     # look-alike distance: same unit across rounds ~0.27-0.55, different units ~0.60-0.87 (measured)
SET = "TFTSet19"


def review_box(u, W, H):
    """Pixel box showing a unit with its own health bar and items on top: the bar marks which unit is meant
    when neighbours overlap."""
    ref = u["w"] * W
    return round(u["x"] * W - 0.35 * ref), round(u["y"] * H - 0.25 * ref), round(1.8 * ref), round(2.9 * ref)


def fingerprints(paths):
    out = {}
    for i in range(0, len(paths), 200):
        p = subprocess.run([str(TOOL), "fprint", *map(str, paths[i:i + 200])], capture_output=True, text=True, check=True)
        for line in p.stdout.splitlines():
            d = json.loads(line)
            out[d["path"]] = d["v"]
    return out


def group(ids, vec):
    """Greedy average-linkage: each crop joins the group it's closest to on average, if close enough."""
    groups = []
    for i in ids:
        best, bd = None, GROUP_DIST
        for g in groups:
            d = sum(math.dist(vec[i], vec[j]) for j in g) / len(g)
            if d < bd:
                best, bd = g, d
        (best.append(i) if best is not None else groups.append([i]))
    return sorted(groups, key=len, reverse=True)


def prepare(rec, video, speed):
    static = load_set(SET)
    rec = Path(rec)
    tag = rec.name.replace(" ", "_")[:40]
    state_file = rec / ("state.replay.jsonl" if (rec / "state.replay.jsonl").exists() else "state.jsonl")
    states = {s["stage"]: s for s in map(json.loads, open(state_file))}
    seen = {}                                             # stage -> [(t, units)]
    with gzip.open(rec / "rows.jsonl.gz", "rt") as f:
        for line in f:
            d = json.loads(line)
            st = read(d["rows"], static["units"], static["traits"])["t"]
            if st in states:
                seen.setdefault(st, []).append((d["t"], d.get("units") or []))
    best = {}       # stage -> (units seen, t, units): the fullest reading of the planning phase (the round's first
    for st, fr in seen.items():                         # half; combat is full of spell effects), settled 3 s in
        t0 = fr[0][0]
        plan = [(t, u) for t, u in fr[:max(1, len(fr) // 2)] if t >= t0 + 3 and u] or [(t, u) for t, u in fr if u]
        if plan:
            t, u = max(plan, key=lambda tu: (len(tu[1]), -tu[0]))
            best[st] = (len(u), t, u)
    if not best:
        sys.exit("no unit readings in this recording: record it with the item model present, or run tools/reread_units.py")
    W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", video],
                                   capture_output=True, text=True, check=True).stdout.strip().split(","))
    out = REVIEW / tag
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    crops, rounds = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        for st, (_, t, units) in sorted(best.items(), key=lambda kv: kv[1][1]):
            frame = Path(tmp) / "f.png"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t / speed:.2f}", "-i", video, "-frames:v", "1",
                            str(frame)], check=True)
            s = states[st]
            board, _ = infer_board(static, s)
            rounds[f"{tag}/{st}"] = {
                "stage": st, "t": t, "level": s.get("level"), "rec": str(rec),
                "units": [{"x": u["x"], "y": u["y"], "items": u["items"]} for u in s.get("units") or []],
                "panel": {x["name"]: x["count"] for x in s.get("traits", []) if x.get("active") and x.get("count")},
                "owned": [o["unit"] for o in s.get("owned", [])],
                "inferred": [u["unit"] for u in board or []]}
            for k, u in enumerate(sorted(units, key=lambda u: (u["y"], u["x"]))):
                x, y, w, h = review_box(u, W, H)
                cid = f"{tag}/{st}_{k}"
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(frame), "-vf",
                                f"crop={w}:{h}:{max(0, x)}:{max(0, y)}", str(REVIEW / f"{cid}.png")], check=True)
                crops.append({"id": cid, "round": f"{tag}/{st}", "stage": st, "x": u["x"], "y": u["y"],
                              "bench": u["y"] >= BENCH_Y, "items": [i[0] for i in u.get("items", [])]})
    m = json.loads(META.read_text()) if META.exists() else {"crops": {}, "rounds": {}}
    m["crops"] = {k: v for k, v in m["crops"].items() if not k.startswith(tag + "/")} | {c["id"]: c for c in crops}
    m["rounds"] = {k: v for k, v in m["rounds"].items() if not k.startswith(tag + "/")} | rounds
    META.write_text(json.dumps(m))
    rebuild_index()
    print(f"{len(crops)} unit crops from {len(rounds)} rounds -> {out.relative_to(ROOT)}")


def refresh_rounds():
    """Re-read each prepared round's context (item consensus, panel, level) from its recording's state, so
    better readers improve the round check without re-cropping (labels are keyed by crop id)."""
    if not META.exists():
        return
    m = json.loads(META.read_text())
    cache = {}
    for rk, r in m["rounds"].items():
        rec = Path(r.get("rec") or ROOT / "recordings" / rk.split("/")[0])
        if rec not in cache:
            f = rec / "state.replay.jsonl" if (rec / "state.replay.jsonl").exists() else rec / "state.jsonl"
            cache[rec] = {s["stage"]: s for s in map(json.loads, open(f))} if f.exists() else {}
        s = cache[rec].get(r["stage"])
        if s:
            r.update(rec=str(rec), level=s.get("level"),
                     panel={x["name"]: x["count"] for x in s.get("traits", []) if x.get("active") and x.get("count")},
                     units=[{"x": u["x"], "y": u["y"], "items": u["items"]} for u in s.get("units") or []])
    META.write_text(json.dumps(m))


def labels():
    return json.loads(LABELS.read_text()) if LABELS.exists() else {}


def rebuild_index():
    """Groups and suggestions from all prepared crops plus the labels so far (confirmed crops are the
    reference: an unlabelled group close to a labelled crop is suggested that name)."""
    if not META.exists():
        return
    m = json.loads(META.read_text())
    lab = labels()
    vec = {Path(p).relative_to(REVIEW).with_suffix("").as_posix(): v
           for p, v in fingerprints([REVIEW / f"{i}.png" for i in m["crops"]]).items()}
    ids = [i for i in m["crops"] if i in vec]
    named = [(vec[i], n) for i, n in lab.items() if i in vec and n != "__skip__"]
    out = []
    for g in group(ids, vec):
        suggest = None
        if named:
            d, n = min((sum(math.dist(vec[i], v) for i in g) / len(g), n) for v, n in named)
            suggest = n if d < GROUP_DIST else None
        cands = {}
        for i in g:
            r = m["rounds"][m["crops"][i]["round"]]
            for n in (r["owned"] if m["crops"][i]["bench"] else r["inferred"]):
                cands[n] = cands.get(n, 0) + 1
        out.append({"ids": g, "suggest": suggest, "candidates": sorted(cands, key=cands.get, reverse=True)[:8]})
    (REVIEW / "index.json").write_text(json.dumps({"groups": out}))


def round_items(r, c):
    """A crop's items: what its frame read, plus the round's consensus for the unit at that spot (bars bob a
    little between frames: nearest within a small box)."""
    near = [u for u in r.get("units", []) if abs(u["x"] - c["x"]) < 0.012 and abs(u["y"] - c["y"]) < 0.03]
    best = min(near, key=lambda u: abs(u["x"] - c["x"]) + abs(u["y"] - c["y"]), default=None)
    return set(c["items"]) | set(best["items"] if best else [])


def check(m, lab, static):
    """Per round: is the labelled board consistent with the game's trait panel? Emblems and units the reader
    missed can only ADD to a trait, so:
      over  - the labelled units alone exceed the panel: a contradiction, most likely a wrong label
      short - they fall short: an emblem on a unit (read ones are counted) or an uncaptured unit can explain it
    Carousel rounds are skipped. Traits counted in star levels are left out."""
    units = {u["name"]: u for u in static["units"]}
    traits = {t["name"]: t for t in static["traits"]}
    by_round = {}
    for c in m["crops"].values():
        if not c["bench"]:
            by_round.setdefault(c["round"], []).append(c)
    out = []
    for rk, cs in sorted(by_round.items(), key=lambda kv: (kv[0].split("/")[0], m["rounds"][kv[0]]["t"])):
        r = m["rounds"][rk]
        if r["stage"].endswith("-4"):
            continue                                   # carousel: no normal board to check
        names = [lab.get(c["id"]) for c in cs]
        done = [n for n in names if n and n != "__skip__"]
        board = len(cs) - names.count("__skip__")
        res = {"round": rk, "stage": r["stage"], "labelled": len(done), "board": board,
               "missing": max(0, (r.get("level") or 0) - board)}
        if names.count(None) == 0 and done:
            base, emb = {}, {}
            for n in set(done):                        # a champion counts once, however many copies
                for tr in units.get(n, {}).get("traits", []):
                    base[tr] = base.get(tr, 0) + 1
            for c in cs:                               # emblems read on these units this round
                n = lab.get(c["id"])
                for it in round_items(r, c) if n not in (None, "__skip__") else ():
                    if it.endswith(" Emblem") and it[:-7] in traits and it[:-7] not in units.get(n, {}).get("traits", []):
                        emb[it[:-7]] = emb.get(it[:-7], 0) + 1
            res["over"], res["short"] = {}, {}
            for tr, want in r["panel"].items():
                if traits.get(tr, {}).get("counts") == "stars":
                    continue
                have = base.get(tr, 0)
                if have > want:
                    res["over"][tr] = [have, want]
                elif have + emb.get(tr, 0) < want:
                    res["short"][tr] = [have + emb.get(tr, 0), want]
            res["diffs"] = res["over"] | res["short"]       # (kept for callers that only want "any difference")
        out.append(res)
    return out


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>TFT unit labels</title>
<style>
body{font:14px -apple-system,system-ui,sans-serif;margin:0;background:#15171c;color:#e8e8e8}
header{position:sticky;top:0;background:#1d2027;padding:10px 16px;display:flex;gap:16px;align-items:center;border-bottom:1px solid #333;z-index:2}
header b{font-size:16px} main{display:flex;gap:16px;padding:16px} #groups{flex:1} #rounds{width:300px;font-size:12px}
.g{background:#1d2027;border:1px solid #2c3038;border-radius:8px;padding:10px;margin-bottom:12px}
.g.done{opacity:.55}.thumbs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.t{position:relative;width:84px;height:100px;border:2px solid transparent;border-radius:4px;overflow:hidden;cursor:pointer;background:#000}
.t img{width:100%;height:100%;object-fit:cover}.t.sel{border-color:#4da3ff}
.t span{position:absolute;left:0;right:0;bottom:0;background:#000b;font-size:10px;padding:1px 3px;white-space:nowrap;overflow:hidden}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
input:not([type=checkbox]){background:#111;color:#eee;border:1px solid #444;border-radius:4px;padding:6px 8px;width:180px}
button{background:#2b5fa8;color:#fff;border:0;border-radius:4px;padding:6px 10px;cursor:pointer}
button.alt{background:#3a3f4a}.chip{background:#2c3038;padding:3px 8px;border-radius:10px;cursor:pointer;font-size:12px}
.chip.sug{background:#245a2c}.ok{color:#6c6}.bad{color:#e77}.dim{color:#888}label{font-size:12px}
</style></head><body>
<header><b>Unit labels</b><span id="prog"></span><label><input type="checkbox" id="todo" checked> unlabelled only</label>
<span class="dim">Click thumbnails to label only some; Enter labels the group (or the selection).</span></header>
<main><div id="groups"></div><div id="rounds"><b>Round check</b> <span class="dim">labelled board vs the game's trait panel</span><div id="rl"></div></div></main>
<datalist id="roster"></datalist>
<script>
let D, L = {}; const SEL = new Set();
function h(tag, attrs, ...kids){ const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (k === 'class') e.className = v; else if (k.startsWith('data-')) e.setAttribute(k, v); else e[k] = v; }
  for (const c of kids.flat()) if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e; }
async function load(){ try { D = await (await fetch('/api/data')).json(); } catch (e) { return setTimeout(load, 700); }   // server still starting
  L = D.labels;
  document.getElementById('roster').replaceChildren(...D.roster.map(n => h('option', {value: n}))); draw(); rounds(); }
function draw(){
  const todo = document.getElementById('todo').checked, cards = []; let n = 0, done = 0;
  D.groups.forEach((g, gi) => { const lab = g.ids.filter(i => L[i]).length; n += g.ids.length; done += lab;
    if (todo && lab === g.ids.length) return;
    const chips = [...new Set([...(g.suggest ? [g.suggest] : []), ...g.candidates])];
    const thumbs = g.ids.slice(0, 24).map(i => { const c = D.crops[i];
      return h('div', {class: 't' + (SEL.has(i) ? ' sel' : ''), 'data-i': i, title: `${c.stage} ${c.bench ? 'bench' : 'board'} ${c.items.join(', ')}`},
        h('img', {src: '/crop/' + encodeURI(i) + '.png', loading: 'lazy'}), h('span', {}, L[i] || (c.stage + (c.bench ? ' bench' : '')))); });
    cards.push(h('div', {class: 'g' + (lab === g.ids.length ? ' done' : ''), 'data-g': gi},
      h('div', {class: 'thumbs'}, thumbs, g.ids.length > 24 ? h('span', {class: 'dim'}, `+${g.ids.length - 24} more`) : null),
      h('div', {class: 'row'}, h('input', {placeholder: 'champion', value: g.suggest || ''}),
        h('button', {'data-a': 'set'}, 'Label'), h('button', {class: 'alt', 'data-a': 'skip'}, 'Not a unit'),
        h('button', {class: 'alt', 'data-a': 'clear'}, 'Clear'),
        chips.map(c => h('span', {class: 'chip' + (c === g.suggest ? ' sug' : ''), 'data-c': c}, c)),
        h('span', {class: 'dim'}, `${g.ids.length} crops, ${lab} labelled`)))); });
  const el = document.getElementById('groups');
  el.replaceChildren(...(cards.length ? cards : [h('p', {class: 'dim'}, 'Nothing left to label.')]));
  document.getElementById('prog').textContent = `${done} / ${n} crops labelled`;
}
async function post(ids, name){ const r = await fetch('/api/label', {method: 'POST', body: JSON.stringify({ids, name})});
  const d = await r.json(); if (d.labels) { L = d.labels; ids.forEach(i => SEL.delete(i)); draw(); rounds(); } }
function target(card){ const g = D.groups[+card.dataset.g]; const sel = g.ids.filter(i => SEL.has(i)); return sel.length ? sel : g.ids; }
function labelWith(card, inp){ if (!D.roster.includes(inp.value)) { inp.style.borderColor = '#e77'; return; } post(target(card), inp.value); }
document.addEventListener('click', e => { const t = e.target.closest('.t'), card = e.target.closest('.g');
  if (t) { const i = t.dataset.i; SEL.has(i) ? SEL.delete(i) : SEL.add(i); t.classList.toggle('sel'); return; }
  if (!card) return; const inp = card.querySelector('input');
  if (e.target.dataset.c) { inp.value = e.target.dataset.c; inp.focus(); return; }
  const a = e.target.dataset.a; if (a === 'set') labelWith(card, inp);
  if (a === 'skip') post(target(card), '__skip__'); if (a === 'clear') post(target(card), ''); });
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.closest('.g')) labelWith(e.target.closest('.g'), e.target); });
document.getElementById('todo').onchange = draw;
async function rounds(){ const r = await (await fetch('/api/check')).json();
  document.getElementById('rl').replaceChildren(...r.map(x => { const head = `${x.round.split('/')[0].slice(0, 14)} ${x.stage}: ${x.labelled}/${x.board}`;
    if (!x.diffs) return h('div', {class: 'dim'}, head);
    const over = Object.entries(x.over), short = Object.entries(x.short);
    const miss = x.missing ? `${x.missing} unit${x.missing > 1 ? 's' : ''} not captured; ` : '';
    if (over.length) return h('div', {class: 'bad'}, `${head} ✗ too many: ` + over.map(([t, [a, b]]) => `${t} ${a}>${b}`).join(', ') + ' (check these labels)');
    if (short.length) return h('div', {class: 'dim'}, `${head} ~ short: ` + short.map(([t, [a, b]]) => `${t} ${a}<${b}`).join(', ') + ` (${miss}unread emblem?)`);
    return h('div', {class: 'ok'}, `${head} ✓ matches panel`); })); }
load();
</script></body></html>"""


def export(lab):
    """Confirmed crops -> data/raw/labels/units/<Champion>/review_*.png (what training and reid.swift read)."""
    for f in UNITS.glob("*/review_*.png"):
        f.unlink()
    for d in UNITS.glob("*/"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    for cid, name in lab.items():
        src = REVIEW / f"{cid}.png"
        if name != "__skip__" and src.exists():
            d = UNITS / name
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, d / ("review_" + cid.replace("/", "_") + ".png"))


def serve(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote
    static = load_set(SET)
    roster = sorted(u["name"] for u in static["units"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, ctype="application/json", code=200):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            m = json.loads(META.read_text()) if META.exists() else {"crops": {}, "rounds": {}}
            if self.path == "/":
                return self.send(PAGE, "text/html; charset=utf-8")
            if self.path == "/api/data":
                idx = json.loads((REVIEW / "index.json").read_text()) if (REVIEW / "index.json").exists() else {"groups": []}
                return self.send(json.dumps({"groups": idx["groups"], "crops": m["crops"], "labels": labels(), "roster": roster}))
            if self.path == "/api/check":
                return self.send(json.dumps(check(m, labels(), static)))
            if self.path.startswith("/crop/"):
                f = (REVIEW / unquote(self.path[len("/crop/"):])).resolve()
                if f.suffix == ".png" and f.is_file() and REVIEW.resolve() in f.parents:    # nothing outside review/
                    return self.send(f.read_bytes(), "image/png")
            self.send(b"not found", "text/plain", 404)

        def do_POST(self):
            if self.path != "/api/label":
                return self.send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            name, ids = body.get("name", ""), body.get("ids", [])
            m = json.loads(META.read_text())
            if name not in roster and name not in ("", "__skip__") or any(i not in m["crops"] for i in ids):
                return self.send(json.dumps({"error": "unknown champion or crop"}), code=400)
            lab = labels()
            for i in ids:
                if name:
                    lab[i] = name
                else:
                    lab.pop(i, None)
            LABELS.write_text(json.dumps(lab, indent=0, sort_keys=True))
            export(lab)
            self.send(json.dumps({"labels": lab}))

    print(f"open http://127.0.0.1:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("recording")
    p.add_argument("video")
    p.add_argument("--speed", type=float, default=1.0)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("regroup")
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(a.recording, a.video, a.speed)
    elif a.cmd == "regroup":
        refresh_rounds()
        rebuild_index()
    else:
        serve(a.port)


if __name__ == "__main__":
    main()
