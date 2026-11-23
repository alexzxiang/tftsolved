"""Unlock checker: where every unlock stands for one game state.

    python3 -I engine/unlocks.py TFTSet19 state.json

State (subset of docs/05 schema):
    {"stage": "3-2", "level": 7, "gold": 34, "gold_end_combat": 30,
     "board": [{"unit": "Ziggs", "stars": 2, "items": ["BFSword"], "hex": [0, 3]}],   # hex row 0 = front
     "unlocked": ["Kobuko"], "counters": {"hyperpop_casts": 4}, "streak": {"type": "win", "n": 2},
     "roles": {"Lux": "Caster"}, "beach_pop_hexes": [[2, 1]]}

Statuses: UNLOCKED, READY, NEEDS_LEVEL, PROGRESS, LOCKED, BLOCKED (exclusive unlock taken),
DEAD (deadline passed), UNKNOWN (rule or data missing; never guessed).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_set(name):
    """Static data for a set: generated (data/pbe) first, else hand-made (data/manual); rules filled in."""
    for d in ("pbe", "manual"):
        p = ROOT / "data" / d / f"{name}.json"
        if p.exists():
            s = json.loads(p.read_text())
            s["rules"] = s.get("rules") or json.loads((ROOT / "data/constants.json").read_text()).get(name)
            return s
    raise FileNotFoundError(f"no static data for {name}")


def unit_resolver(static):
    """Riot character_id -> roster name. Exact api match first (generated sets), else a normalised name
    match with the set prefix stripped ("TFT19_NunuWillump" -> "Nunu & Willump"; hand-made Set 19 data
    uses display names). Returns None for summons, props and anything unknown; callers count those."""
    import re
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())                        # noqa: E731
    exact = {u["api"]: u["name"] for u in static["units"]}
    by_norm = {norm(u["name"]): u["name"] for u in static["units"]}

    def resolve(cid):
        if cid in exact:
            return exact[cid]
        return by_norm.get(norm(re.sub(r"^(?:tft\d+[a-z]*|da_?\d*)_", "", cid, flags=re.I)))
    return resolve


def stage_key(s):
    a, b = s.split("-")
    return int(a), int(b)


EMBLEM_COST = 0.6                      # per trait point the fielded units don't explain


BENCH_Y = 0.6                          # health bars below this (frame fraction) stand on the bench
NEW_UNIT_COST = 0.3                    # a unit that wasn't on last round's board (boards change little)
# Weights measured on 14 hand-labelled boards (2 games, 2026-11-19): unowned 0.5 + continuity: precision 88%,
# recall 85%, 6/14 boards exact (was 73% / 78% / 2 with unowned 1.0, no continuity, no emblems/bar count).
OFF_ODDS_COST = 0.6                    # a unit the shop can't offer at this level, unless owned or already fielded


def round_type(stage):
    """combat kind of a round: 'pvp', 'pve' or 'carousel' (stage 1 PvE, x-4 carousel, x-7 PvE)."""
    s, r = stage_key(stage)
    if (s, r) == (1, 1) or (s >= 2 and r == 4):
        return "carousel"
    return "pve" if s == 1 or r == 7 else "pvp"


def infer_board(static, state, unowned_cost=0.5, prev=None):
    """Which units are fielded, from what the screen gives: the trait panel (counts per trait), the number
    of health bars on the board (else the level), emblems read on board units (each adds 1 to its trait),
    the units the purchase ledger saw bought, and last round's board (`prev`: boards change little).
    Picks the n units whose traits best reproduce the panel; a unit the ledger missed (carousel) costs
    `unowned_cost`, one the shop can't offer at this level costs more. Local search: greedy fill, then
    single swaps while they help. Returns (board, error); board items are None (not visible).
    ponytail: greedy + swaps, exact cover (ILP) if ties start to matter."""
    panel = {x["name"]: dict(x) for x in state.get("traits", []) if not x.get("carried")}
    hidden = {x["name"] for x in state.get("traits", []) if x.get("carried")}   # behind the panel's badge: free
    if not panel:
        return None, None
    units = {u["name"]: u for u in static["units"]}
    traits = {t["name"]: t for t in static["traits"]}
    owned = {o["unit"]: o.get("stars", 1) for o in state.get("owned", []) if o["unit"] in units}
    prev = set(prev or ())
    unlocked = set(state.get("unlocked", []))
    pool = set(owned) | prev | {n for n, u in units.items() if not u.get("unlockable") or n in unlocked}
    on_board = [u for u in state.get("units") or [] if u["y"] < BENCH_Y]
    level = state.get("level")
    # health bars miss units (and catch enemies in combat): players field `level` units, rarely one fewer
    n = (state.get("board_count") or [None])[0] or \
        (max(min(len(on_board), level), level - 1) if on_board and level else len(on_board) or None) or level
    if not n:
        pool = set(owned)                       # no board size to justify units the ledger never saw
    for u in on_board:                          # emblems read on board units: their trait point isn't a unit's
        for it in u.get("items", []):
            tr = it[:-7] if it.endswith(" Emblem") else None
            if tr in panel and panel[tr].get("count"):
                panel[tr]["count"] -= 1
    table = static.get("shop_odds_by_level") or []          # per level (1-based), chance per cost
    odds = table[level - 1] if level and 0 < level <= len(table) else None
    star = lambda u: owned.get(u, 1)                                      # noqa: E731

    def unit_cost(u):
        c = 0.0 if u in owned or u in prev else unowned_cost
        if prev and u not in prev:
            c += NEW_UNIT_COST
        cost = units[u].get("cost", 1)
        if odds and u not in owned and u not in prev and cost <= len(odds) and not odds[cost - 1]:
            c += OFF_ODDS_COST
        return c

    def err(sel):
        cnt = {}
        for u in sel:
            for tr in units[u]["traits"]:
                cnt[tr] = cnt.get(tr, 0) + (star(u) if traits.get(tr, {}).get("counts") == "stars" else 1)
        e = sum(unit_cost(u) for u in sel)
        for tr, x in panel.items():
            c = cnt.get(tr, 0)
            if x.get("count") is not None and not x.get("count_is_lower_bound"):
                # panel above the units: unread emblems can explain it (cheap); below: a unit that isn't there
                # (a listed trait with no unit at all is rarely emblems alone: that first point costs 1)
                e += (1 + EMBLEM_COST * (x["count"] - 1) if c == 0 and x["count"] > 0 else EMBLEM_COST * (x["count"] - c)) \
                    if c < x["count"] else c - x["count"]
            else:                                                           # lower bound only
                e += max(0, (x.get("count") or 1) - c)
        e += 0.4 * sum(1 for tr, c in cnt.items() if c and tr not in panel and tr not in hidden)   # scrolled: soft
        return e

    tie = lambda u: (u not in owned, u not in prev, units[u].get("cost", 1), u)   # noqa: E731
    sel = []
    while len(sel) < (n or len(pool)):
        best = min(pool - set(sel), key=lambda u: (err(sel + [u]), tie(u)))
        if not n and err(sel + [best]) >= err(sel):
            break
        sel.append(best)
    improved = True
    while improved:
        improved, base = False, err(sel)
        for i in range(len(sel)):
            for u in sorted(pool - set(sel), key=tie):
                cand = sel[:i] + [u] + sel[i + 1:]
                if err(cand) < base - 1e-9:
                    sel, base, improved = cand, err(cand), True
    stars = {u: star(u) for u in sel}
    # star badges on the bars: silver (2) and gold (3) reads are precise (24/24 checked; a stray green shape
    # reads bronze or nothing), so each one stars a unit, given to the likeliest (stars the ledger saw, then
    # most copies bought, then the cheapest: cheap units star up first); unread and bronze stay as they were
    seen = sorted((x["stars"] for x in on_board if (x.get("stars") or 0) >= 2), reverse=True)[:len(sel)]
    if seen:
        copies = {o["unit"]: o.get("copies", 1) for o in state.get("owned", [])}
        order = sorted(sel, key=lambda u: (-stars[u], -copies.get(u, 0), units[u].get("cost", 1), u))
        stars.update((u, max(stars[u], s)) for u, s in zip(order, seen))
    board = [{"unit": u, "stars": stars[u], "items": None, "owned": u in owned} for u in sorted(sel)]
    return board, err(sel)


def infer_boards(static, states):
    """infer_board over a game's rounds in order, each round starting from the previous round's board."""
    out, prev = [], None
    for s in states:
        b, e = infer_board(static, s, prev=prev)
        out.append((b, e))
        prev = {u["unit"] for u in b} if b else prev
    return out


def with_prev_boards(static, states):
    """States in stage order, each carrying the board inferred for the round before ("prev_board"), so
    Board() can prefer continuity. Unchanged when states carry exact boards."""
    states = sorted(states, key=lambda s: stage_key(s["stage"]))
    boards = infer_boards(static, states)
    out, prev = [], None
    for s, (b, _) in zip(states, boards):
        out.append(dict(s, prev_board=prev) if prev is not None and not s.get("board") else s)
        prev = [u["unit"] for u in b] if b else prev
    return out


class Board:
    def __init__(self, static, state):
        self.units = {u["name"]: u for u in static["units"]}
        self.traits = {t["name"]: t for t in static["traits"]}
        self.members = {t: sum(t in u["traits"] for u in static["units"]) for t in self.traits}
        self.state = state
        # trait panel from the HUD: stands in for the board when units aren't known (lower bounds)
        self.panel = {x["name"]: x for x in state.get("traits", [])} if not state.get("board") else {}
        board, self.bench = state.get("board"), {x["unit"] for x in state.get("bench", [])}
        if board is None and state.get("owned"):
            # units from purchase bookkeeping: the fielded set is the one that reproduces the trait panel;
            # the rest are benched. Items are not visible (None), unlike an empty list
            board = infer_board(static, state, prev=state.get("prev_board"))[0] if self.panel else None
            if board is None:
                board = [{"unit": o["unit"], "stars": o["stars"], "items": None} for o in state["owned"]]
            self.bench |= {o["unit"] for o in state["owned"]} - {u["unit"] for u in board}
        self.fielded = {}                                  # unique units, best copy each
        for u in board or []:
            best = self.fielded.get(u["unit"])
            if best is None or (u.get("stars", 1), len(u.get("items") or [])) > (best.get("stars", 1), len(best.get("items") or [])):
                self.fielded[u["unit"]] = u

    def has_trait(self, name, traits):
        return any(t in self.units.get(name, {}).get("traits", []) for t in traits)

    def count(self, trait):
        if self.panel:
            x = self.panel.get(trait)
            if not x:
                return 0
            if x.get("count") is None:                 # listed but count unread: a safe lower bound
                return (self.traits[trait].get("breakpoints") or [1])[0] if x.get("active") else 1
            return x["count"]
        us = [u for n, u in self.fielded.items() if trait in self.units.get(n, {}).get("traits", [])]
        return sum(u.get("stars", 1) for u in us) if self.traits[trait].get("counts") == "stars" else len(us)

    def active(self, trait):
        if self.panel:
            return bool((self.panel.get(trait) or {}).get("active"))
        bp = self.traits[trait].get("breakpoints")
        return None if not bp else self.count(trait) >= bp[0]


def check(when, b, st):
    """-> (met: True/False/None, value, target, detail)"""
    (kind, a), = when.items()
    f = b.fielded
    if kind in ("board_unique", "board_stars") and b.panel:
        # one unit may carry two listed traits, so the best single trait count is a safe lower bound;
        # for star-level conditions on unit-counting traits, units <= star levels: still a lower bound
        v = max((b.count(t) for t in a["traits"]), default=0)
        if kind == "board_stars":
            # the panel counts units for most traits; with owned stars known, the k fielded units carry at
            # least the k lowest star values among owned units of that trait (unknown ones count 1 star)
            for t in a["traits"]:
                k = b.count(t)
                if b.traits[t].get("counts") != "stars" and k:
                    stars = sorted(o["stars"] for o in st.get("owned", []) if t in b.units.get(o["unit"], {}).get("traits", []))
                    v = max(v, sum((stars + [1] * k)[:k]))
        what = "unique" if kind == "board_unique" else "star levels of"
        return (True if v >= a["n"] else False), v, a["n"], f"at least {v}/{a['n']} {what} {'/'.join(a['traits'])} (trait panel)"
    if kind in ("board_unique", "board_stars"):
        us = [u for n, u in f.items() if b.has_trait(n, a["traits"])]
        v = len(us) if kind == "board_unique" else sum(u.get("stars", 1) for u in us)
        what = "unique" if kind == "board_unique" else "star levels of"
        return v >= a["n"], v, a["n"], f"{v}/{a['n']} {what} {'/'.join(a['traits'])}"
    if kind == "items_on":
        holders = [u for n, u in f.items() if b.has_trait(n, a["traits"])]
        if holders and all(u.get("items") is None for u in holders):
            return None, None, a["n"], f"{'/'.join(a['traits'])} units owned; their items aren't visible"
        v = max((len(u.get("items") or []) for u in holders), default=0)
        return v >= a["n"], v, a["n"], f"best {'/'.join(a['traits'])} holder has {v}/{a['n']} items"
    if kind == "item_on_role":
        roles = st.get("roles")
        if not roles:
            return None, None, 1, "needs unit roles (Caster/Marksman) in the state"
        ok = any(roles.get(n) in a["roles"] and a["item"] in (u.get("items") or []) for n, u in f.items())
        return ok, int(ok), 1, f"{a['item']} on a {' or '.join(a['roles'])}"
    if kind == "unit_state":
        cands = [f[n] for n in a["units"] if n in f]
        if a.get("items") and any(u.get("items") is None and u.get("stars", 1) >= a["stars"] for u in cands):
            u = next(u for u in cands if u.get("items") is None)
            return None, 1, 1, f"{u['unit']} {u.get('stars', 1)}* owned; can't see its items (needs {a['items']})"
        ok = any(u.get("stars", 1) >= a["stars"] and len(u.get("items") or []) >= a.get("items", 0) for u in cands)
        best = max(cands, key=lambda u: (u.get("stars", 1), len(u.get("items") or [])), default=None)
        have = f"{best['unit']} {best.get('stars', 1)}* with {len(best.get('items') or [])} items" if best else "not fielded"
        need = f"{' or '.join(a['units'])} {a['stars']}*" + (f" with {a['items']} items" if a.get("items") else "")
        return ok, int(ok), 1, f"need {need}; have {have}"
    if kind == "traits_active":
        # unique = a solo trait (breakpoints [1]); Collab has one fixed member but 3/5 breakpoints
        ts = a.get("traits") or [t for t in b.traits
                                 if not a.get("non_unique") or (b.traits[t].get("breakpoints") or [0]) != [1]]
        unknown = [t for t in ts if b.active(t) is None and b.count(t)]
        v = sum(bool(b.active(t)) for t in ts)
        note = f" ({', '.join(unknown)} not counted: breakpoints unknown)" if unknown else ""
        what = "/".join(a["traits"]) if a.get("traits") else "non-unique traits"
        return v >= a["n"], v, a["n"], f"{v}/{a['n']} {what} active{note}"
    if kind == "front_rows_max":
        if not f or any("hex" not in u for u in f.values()):
            return None, None, a["n"], "needs hex positions for every fielded unit"
        v = sum(u["hex"][0] <= 1 for u in f.values())
        return v <= a["n"], v, a["n"], f"{v} units in the two front rows (max {a['n']})"
    if kind == "beach_pop_hex_each_cost":
        hexes = st.get("beach_pop_hexes")
        if not hexes or any("hex" not in u for u in f.values()):
            return None, None, 5, "needs Beach Pop hex locations and unit positions"
        costs = {b.units[n]["cost"] for n, u in f.items() if list(u["hex"]) in [list(h) for h in hexes]}
        v = len(costs & {1, 2, 3, 4, 5})
        return v >= 5, v, 5, f"costs on Beach Pop hexes: {sorted(costs)}"
    if kind == "gold_end_combat":
        g = st.get("gold_end_combat")
        if g is None:
            return None, None, a["n"], "gold at end of combat not read"
        return g >= a["n"], g, a["n"], f"{g}/{a['n']} gold at end of combat"
    if kind == "window":
        v = st.get("counters", {}).get(a["counter"])
        if v is None:
            return None, None, a["n"], f"{a['counter']} not tracked"
        if v < a["n"] and "stage" in st and stage_key(st["stage"]) >= stage_key(a["deadline"]):
            return "dead", v, a["n"], f"{v}/{a['n']}; window closed at {a['deadline']}"
        return v >= a["n"], v, a["n"], f"{v}/{a['n']} before {a['deadline']}"
    if kind == "counter":
        v = st.get("counters", {}).get(a["name"])
        gate = ""
        if a.get("requires_unit") and a["requires_unit"] not in f:
            gate = f"; paused: {a['requires_unit']} not fielded"
        if a.get("requires_trait") and b.active(a["requires_trait"]) is False:
            gate = f"; paused: {a['requires_trait']} not active"
        if v is None:
            return None, None, a["n"], f"{a['name']} not read (pin it in Team Planner to show progress){gate}"
        return v >= a["n"], v, a["n"], f"{v}/{a['n']} {a['name']}{gate}"
    if kind == "streak":
        s = st.get("streak_l8") or st.get("streak") or {}     # Rakan counts only streaks at level 8+
        need = a.get(s.get("type"), min(a.values()))
        v = (s.get("n") or 0)
        return v >= need, v, need, f"{s.get('type', 'no')} streak {v}/{need}"
    if kind == "all_of":
        parts = [check(w, b, st) for w in a]
        met = "dead" if any(p[0] == "dead" for p in parts) else (
            None if any(p[0] is None for p in parts) else all(p[0] for p in parts))
        first = next((p for p in parts if p[0] is not True), parts[0])
        return met, first[1], first[2], "; ".join(p[3] for p in parts)
    raise ValueError(f"unknown condition {kind}")


def evaluate(static, state):
    b = Board(static, state)
    unlockable = {u["unit"] for u in static["unlocks"]}
    unlocked = set(state.get("unlocked", [])) | (set(b.fielded) & unlockable)   # fielded => unlocked
    out = []
    for u in static["unlocks"]:
        name, row = u["unit"], {"unit": u["unit"], "value": None, "target": None}
        if name in unlocked:
            row.update(status="UNLOCKED", detail="")
        elif unlocked & set(u.get("excludes", [])):
            row.update(status="BLOCKED", detail=f"{', '.join(unlocked & set(u['excludes']))} already unlocked")
        elif not u.get("when"):
            row.update(status="UNKNOWN", detail=u.get("note", "condition not known"))
        else:
            met, v, t, detail = check(u["when"], b, state)
            row.update(value=v, target=t, detail=detail)
            lvl = u.get("min_level")
            if met == "dead":
                row["status"] = "DEAD"
            elif met is None:
                row["status"] = "UNKNOWN"
            elif met:
                ok = not lvl or (state.get("level") or 0) >= lvl
                row["status"] = "READY" if ok else "NEEDS_LEVEL"
                if not ok:
                    row["detail"] += f"; needs level {lvl}"
            else:
                capped = "front_rows_max" in u["when"]     # a value above a cap isn't progress
                row["status"] = "PROGRESS" if v and not capped else "LOCKED"
            if u.get("excludes") and met and not unlocked & set(u["excludes"]):
                row["detail"] += f"; WARNING: permanently blocks {', '.join(u['excludes'])}"
        out.append(row)
    return out


ORDER = ["READY", "NEEDS_LEVEL", "PROGRESS", "LOCKED", "UNKNOWN", "BLOCKED", "DEAD", "UNLOCKED"]

if __name__ == "__main__":
    rows = evaluate(load_set(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
    for r in sorted(rows, key=lambda r: ORDER.index(r["status"])):
        print(f"{r['status']:<12}{r['unit']:<22}{r['detail']}")
