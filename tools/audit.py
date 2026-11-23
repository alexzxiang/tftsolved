"""Parse-health audit: where reading breaks, measured without labels. Every round must obey the game's rules
(no skipped rounds, level never falls, XP rises by 2 a round plus 4 per purchase, HP barely rises, a loss costs
at most stage damage + a full board, a streak grows by one or restarts, shops only offer costs the level
allows, other players' HP barely rises), so counting rule breaks per field shows which reader to fix.
Softer checks flag flicker: the trait panel or item bench changing for a single round, health bars that
can't be the board. A frame pass adds raw OCR noise: a value differing from both neighbouring frames while
those agree. It also reports where the HUD disagrees with the rules file (rules copied from the last set).

    python3 -I tools/audit.py [recordings/<dir> ...] [--set TFTSet19] [--no-frames]   # default: all
    python3 -I tools/audit.py recordings/<dir>/state.replay.jsonl      # a re-parse (record.py --replay)
"""
import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "capture")]
from econ import damage  # noqa: E402
from hud import counter_targets, read  # noqa: E402
from record import BENCH_MIN_CONF  # noqa: E402
from unlocks import BENCH_Y, load_set, round_type, stage_key  # noqa: E402

AUGMENT_ROUNDS = ("2-1", "3-2", "4-2")
MAX_SURVIVORS = 10        # a loss costs stage damage + damage per enemy unit left standing (a full board at most)
MAX_UNIT_DAMAGE = 3       # ponytail: the rules file says 1 a unit; starred units may cost more (a 34-HP loss at
                          # stage 4 was read). Losses past the rules file's own cap are reported as rule notes.
MAX_HEAL = 5              # HP rises a little in Set 19 (+3 at 2-1, +2 a round for one player, steady over
                          # 40+ frames each: healing effects); bigger rises are misreads
MAX_LEVEL = 10            # XP stops here (10 -> 11 only from a scroll)
FIELDS = ("stage", "level", "xp", "gold", "hp", "streak", "traits", "board", "shop", "items", "lobby", "augments")
FRAME_FIELDS = ("t", "level", "xp", "gold", "hp", "streak_n", "held")


def next_stage(st):
    s, r = stage_key(st)
    return f"{s + 1}-1" if r == (4 if s == 1 else 7) else f"{s}-{r + 1}"


def xp_caps(static, states):
    """XP to the next level: the HUD's own bar where read (its most common value), else the rules; plus
    the levels where the two disagree, as {level: (shown, rule, rounds)}."""
    seen = {}
    for s in states:
        if s.get("level") and s.get("xp"):
            seen.setdefault(s["level"], Counter())[s["xp"][1]] += 1
    rule = {int(k): v for k, v in static["rules"]["xp_to_next_level"].items()}
    shown = {lv: c.most_common(1)[0] for lv, c in seen.items()}
    return rule | {lv: v for lv, (v, _) in shown.items()}, \
        {lv: (v, rule.get(lv), n) for lv, (v, n) in sorted(shown.items()) if v != rule.get(lv)}


def xp_total(level, xp, need):
    return sum(need[k] for k in range(1, level)) + xp


def trait_units(s, per_star):
    return sum(t["count"] or 0 for t in s.get("traits") or [] if t["name"] not in per_star)


def audit(static, states):
    """{field: [rounds checked, rounds unread, [(stage, problem)]]} and notes where reads contradict the rules
    file (a stale rule, or the same misread every time)."""
    rules, odds = static["rules"], static["shop_odds_by_level"]
    cost = {u["name"]: u["cost"] for u in static["units"]}
    per_star = {t["name"] for t in static["traits"] if t.get("counts") == "stars"}
    need, stale = xp_caps(static, states)
    notes = [f"the XP bar shows /{v} at level {lv} in {k} rounds; the rules file says {r}" for lv, (v, r, k) in stale.items()
             if lv < MAX_LEVEL]                  # XP stops at the top level; its bar shows a leftover number
    out = {f: [0, 0, []] for f in FIELDS}

    def note(field, stage, ok, problem=""):
        f = out[field]
        if ok is None:
            f[1] += 1
            return
        f[0] += 1
        if not ok:
            f[2].append((stage, problem))

    streak, since = None, 0                     # last HUD streak that fit, PvP rounds since
    for i, s in enumerate(states):
        st, kind = s["stage"], round_type(s["stage"])
        p = states[i - 1] if i and next_stage(states[i - 1]["stage"]) == st else None   # the round before
        n = states[i + 1] if i + 1 < len(states) and next_stage(st) == states[i + 1]["stage"] else None
        late = stage_key(st) >= (2, 1)          # level, XP and gold show from stage 2
        lv, xp, hp = s.get("level"), s.get("xp"), s.get("hp")
        if i:
            note("stage", st, p is not None, f"rounds missing after {states[i - 1]['stage']}")
        if late:
            pl = p and p.get("level")
            note("level", st, None if lv is None else not (pl and lv < pl), f"level {pl} -> {lv}")
            note("gold", st, None if s.get("gold") is None else 0 <= s["gold"] <= 300, f"gold {s.get('gold')}")
            # the free 2 XP can land just before or after the stage label turns at a carousel (no buying
            # there either), so a carousel is judged with the round after it, against the round before it
            q = p if not (p and round_type(p["stage"]) == "carousel") else \
                states[i - 2] if i >= 2 and next_stage(states[i - 2]["stage"]) == p["stage"] else None
            ql, qx = q and q.get("level"), q and q.get("xp")
            if kind == "carousel":
                pass
            elif lv and xp and ql and qx and ql < MAX_LEVEL:
                gain = xp_total(lv, xp[0], need) - xp_total(ql, qx[0], need) - 2
                note("xp", st, gain >= 0 and gain % rules["buy_xp"]["xp"] == 0,
                     f"{ql}:{qx[0]}/{qx[1]} -> {lv}:{xp[0]}/{xp[1]} is {gain:+d} XP beyond the free 2")
            else:
                note("xp", st, None)
        ph = p and p.get("hp")
        if hp is not None and ph is not None:
            loss, base = ph - hp, damage(stage_key(p["stage"])[0], 0, rules)
            cap, rule_cap = base + MAX_SURVIVORS * MAX_UNIT_DAMAGE, damage(stage_key(p["stage"])[0], MAX_SURVIVORS, rules)
            note("hp", st, -MAX_HEAL <= loss <= cap and not (loss and round_type(p["stage"]) == "carousel"),
                 f"HP {ph} -> {hp} after {p['stage']}" + (f" (a loss costs at most {cap})" if loss > cap else ""))
            if rule_cap < loss <= cap:
                notes.append(f"HP {ph} -> {hp} after {p['stage']}: past the rules file's cap of {rule_cap} for one loss")
        elif i:
            note("hp", st, None)
        if kind == "pvp":                       # the HUD streak after this round's fight
            since += 1
            k = s.get("streak_n")
            ok = None if k is None else streak is None or k == streak + since or 1 <= k <= since
            note("streak", st, ok, f"streak {streak} -> {k} over {since} fight(s)")
            if ok:
                streak, since = k, 0
        if late and lv:
            tu, near = trait_units(s, per_star), [trait_units(x, per_star) for x in (p, n) if x]
            ok = None if not s.get("traits") else lv - 1 <= tu <= 3 * (lv + 1) + 3 and \
                not (len(near) == 2 and tu < 0.6 * min(near))
            note("traits", st, ok, f"trait panel adds to {tu} unit-traits at level {lv} (neighbours {near})")
            bars = sum(1 for u in s.get("units") or [] if u["y"] < BENCH_Y)
            note("board", st, None if not s.get("units") else lv - 2 <= bars <= lv + 1, f"{bars} bars at level {lv}")
            off = [f"{x['unit']} ({cost[x['unit']]}-cost)" for x in s.get("shop") or []
                   if cost.get(x["unit"], 9) <= len(odds[lv - 1]) and odds[lv - 1][cost[x["unit"]] - 1] == 0]
            note("shop", st, None if not s.get("shop") else not off, f"{', '.join(off)} in a level-{lv} shop")
        # carousels show no item bench: the rounds either side are the neighbours there
        p2 = p if not (p and round_type(p["stage"]) == "carousel") else states[i - 2] if i >= 2 else None
        n2 = n if not (n and round_type(n["stage"]) == "carousel") else states[i + 2] if i + 2 < len(states) else None
        if kind == "carousel":
            pass
        elif late and all(x and x.get("items_held") is not None for x in (p2, s, n2)):
            a, h, b = (set(x["items_held"]) for x in (p2, s, n2))
            flick = sorted((h - a - b) | ((a & b) - h))      # here for one round only, or gone for one round
            note("items", st, not flick, f"{', '.join(flick)} flickers")
        elif late:
            note("items", st, None)
        lob, plob = s.get("lobby_hp") or {}, (p and p.get("lobby_hp")) or {}
        if late:
            rose = [f"{k} {plob[k]} -> {v}" for k, v in lob.items() if k in plob and v > plob[k] + MAX_HEAL]
            note("lobby", st, None if not lob else not rose, ", ".join(rose))
    offers = {a["stage"]: a for a in (states[-1].get("augment_offers") or [])} if states else {}
    for st in AUGMENT_ROUNDS:
        if states and stage_key(states[0]["stage"]) <= stage_key(st) <= stage_key(states[-1]["stage"]):
            a = offers.get(st)
            note("augments", st, None if a is None else a.get("picked") is not None, "pick not identified")
    return out, notes


def blips(values):
    """Reads that differ from both neighbouring reads while those two agree (one-frame misreads)."""
    return sum(1 for a, b, c in zip(values, values[1:], values[2:]) if b != a and a == c)


def frame_noise(static, rows_path):
    """{field: (frames with a stage, unread, one-frame blips)} over a recording's stored OCR rows."""
    targets, vals, frames, transform, gold = counter_targets(static["unlocks"]), {f: [] for f in FRAME_FIELDS}, 0, None, None
    with gzip.open(rows_path, "rt") as f:
        for line in f:
            d = json.loads(line)
            r = read(d["rows"], static["units"], static["traits"], targets=targets, transform=transform)
            transform = r["quality"]["transform"] or transform
            if not r.get("t"):
                continue
            frames += 1
            if r.get("gold_alt") is not None and gold is not None and abs(r["gold_alt"] - gold) < abs(r["gold"] - gold):
                r["gold"] = r["gold_alt"]                 # the recorder's own fix ("94" after 6 = coin + 4)
            gold = r["gold"] if r.get("gold") is not None else gold
            if "held" in d:
                r["held"] = tuple(sorted(h[1] for h in d["held"] if h[2] >= BENCH_MIN_CONF))
            for k in FRAME_FIELDS:
                if r.get(k) is not None:
                    vals[k].append(tuple(r[k]) if isinstance(r[k], list) else r[k])
    return {k: (frames, frames - len(v), blips(v)) for k, v in vals.items() if v}


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def report(name, static, states, rows_path=None):
    out, notes = audit(static, states)
    print(f"\n{name}: {len(states)} rounds {states[0]['stage']}..{states[-1]['stage']}")
    print(f"  {'field':9} {'checked':>7} {'unread':>6} {'broken':>6}  first breaks")
    for f, (ok, unread, bad) in out.items():
        if ok or unread:
            where = "; ".join(f"{st} {msg}" for st, msg in bad[:2]) + (f"; +{len(bad) - 2} more" if len(bad) > 2 else "")
            print(f"  {f:9} {ok:7} {unread:6} {len(bad):6}  {where}")
    for x in notes:
        print(f"  rules: {x}")
    if states[-1].get("ledger_unattributed"):
        print(f"  ledger: {states[-1]['ledger_unattributed']} gold rises the purchase ledger couldn't explain")
    if rows_path and rows_path.exists():
        noise = frame_noise(static, rows_path)
        print("  frames (blips / unread): " + ", ".join(
            f"{k} {pct(b, n - u)}/{pct(u, n)}" for k, (n, u, b) in noise.items()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", type=Path)
    ap.add_argument("--set", default="TFTSet19")
    ap.add_argument("--no-frames", action="store_true", help="skip the OCR noise pass over rows.jsonl.gz")
    a = ap.parse_args()
    static = load_set(a.set)
    dirs = a.dirs or sorted(d for d in (ROOT / "recordings").iterdir() if (d / "state.jsonl").exists())
    total = {f: [0, 0] for f in FIELDS}
    for d in dirs:
        path, d = (d, d.parent) if d.is_file() else (d / "state.jsonl", d)
        states = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        if not states:
            continue
        out = report(f"{d.name}/{path.name}", static, states, None if a.no_frames else d / "rows.jsonl.gz")
        for f, (ok, _, bad) in out.items():
            total[f][0] += ok
            total[f][1] += len(bad)
    if len(dirs) > 1:
        print("\nall recordings: " + ", ".join(f"{f} {b}/{n} ({pct(b, n)})" for f, (n, b) in total.items() if n))


if __name__ == "__main__":
    main()
