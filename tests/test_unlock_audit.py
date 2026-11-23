# Audit of every Set 19 unlock rule: names resolve, and a state built to satisfy the rule reads READY
# (while an empty state does not). Catches misspelled traits and rules that can never fire.
#   python3 -I tests/test_unlock_audit.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from unlocks import evaluate, load_set  # noqa: E402

S = load_set("TFTSet19")
UNITS = {u["name"]: u for u in S["units"]}
TRAITS = {t["name"]: t for t in S["traits"]}
LOCKED = {u["unit"] for u in S["unlocks"]}
problems = []


def walk(when):
    (kind, a), = when.items()
    if kind == "all_of":
        for w in a:
            yield from walk(w)
    else:
        yield kind, a


# 1. every name a rule mentions exists
for u in S["unlocks"]:
    if u["unit"] not in UNITS:
        problems.append(f"{u['unit']}: not in roster")
    for x in u.get("excludes", []):
        if x not in UNITS:
            problems.append(f"{u['unit']}: excludes unknown {x}")
    for kind, a in walk(u.get("when") or {"none": {}}):
        for t in a.get("traits", []) + [a.get("requires_trait")] * bool(a.get("requires_trait")):
            if t not in TRAITS:
                problems.append(f"{u['unit']}: unknown trait {t}")
        for n in a.get("units", []) + [a.get("requires_unit")] * bool(a.get("requires_unit")):
            if n not in UNITS:
                problems.append(f"{u['unit']}: unknown unit {n}")


def members(trait, avoid):
    return [n for n, x in UNITS.items() if trait in x["traits"] and n not in avoid]


def satisfy(u):
    """A state that should make unlock `u` READY."""
    avoid = {u["unit"], *u.get("excludes", [])}
    st = {"stage": "2-1", "level": u.get("min_level") or 1, "board": [], "counters": {}, "unlocked": []}
    board = {}

    def field(name, stars=1, items=0, hex=None):
        if name in avoid:
            return
        if name in LOCKED:
            st["unlocked"].append(name)
        cur = board.get(name, {"unit": name, "stars": 1, "items": []})
        cur["stars"] = max(cur["stars"], stars)
        cur["items"] = ["X"] * max(len(cur["items"]), items)
        if hex:
            cur["hex"] = hex
        board[name] = cur

    def activate(trait):
        for n in members(trait, avoid)[:TRAITS[trait]["breakpoints"][0]]:
            field(n)

    for kind, a in walk(u["when"]):
        if kind == "board_unique":
            pool = sorted({n for t in a["traits"] for n in members(t, avoid)})
            for n in pool[:a["n"]]:
                field(n)
        elif kind == "board_stars":
            pool, total = sorted({n for t in a["traits"] for n in members(t, avoid)}), 0
            for n in pool:
                if total >= a["n"]:
                    break
                s = min(3, a["n"] - total)
                field(n, s)
                total += s
        elif kind == "items_on":
            field(members(a["traits"][0], avoid)[0], items=a["n"])
        elif kind == "item_on_role":
            name = next(n for n in UNITS if n not in avoid and n not in LOCKED)
            board[name] = {"unit": name, "stars": 1, "items": [a["item"]]}
            st["roles"] = {name: a["roles"][0]}
        elif kind == "unit_state":
            field(a["units"][0], a["stars"], a.get("items", 0))
        elif kind == "traits_active":
            ts = a.get("traits") or sorted(
                (t for t, x in TRAITS.items() if (x.get("breakpoints") or [0]) != [1] and x.get("breakpoints")),
                key=lambda t: TRAITS[t]["breakpoints"][0])
            for t in ts[:a["n"] + 1]:
                activate(t)
        elif kind == "front_rows_max":
            field("Olaf", hex=[0, 3])
            field("Zoe", hex=[3, 0])
        elif kind == "beach_pop_hex_each_cost":
            hexes = []
            for c in range(1, 6):
                n = next(n for n, x in UNITS.items() if x["cost"] == c and n not in avoid and n not in LOCKED)
                field(n, hex=[2, c])
                hexes.append([2, c])
            st["beach_pop_hexes"] = hexes
        elif kind == "gold_end_combat":
            st["gold_end_combat"] = a["n"]
        elif kind == "window":
            st["counters"][a["counter"]] = a["n"]
        elif kind == "counter":
            st["counters"][a["name"]] = a["n"]
            if a.get("requires_unit"):
                field(a["requires_unit"])
            if a.get("requires_trait"):
                activate(a["requires_trait"])
        elif kind == "streak":
            st["streak"] = {"type": "win", "n": a["win"]}
        else:
            problems.append(f"{u['unit']}: audit can't build {kind}")
    st["board"] = list(board.values())
    return st


# 2. each rule reaches READY when satisfied, and isn't READY from nothing
for u in S["unlocks"]:
    if not u.get("when"):
        problems.append(f"{u['unit']}: no condition")
        continue
    got = next(r for r in evaluate(S, satisfy(u)) if r["unit"] == u["unit"])
    if got["status"] != "READY":
        problems.append(f"{u['unit']}: satisfied state reads {got['status']} ({got['detail']})")
    empty = next(r for r in evaluate(S, {"stage": "2-1", "level": 10}) if r["unit"] == u["unit"])
    if empty["status"] == "READY":
        problems.append(f"{u['unit']}: READY from an empty state")

print("\n".join(problems) or "all rules resolve and fire")
assert not problems
print("ok")
