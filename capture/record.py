"""Recorder: reads TFT (live window or a video) and writes one state per planning phase. Shows nothing in game.

    python3 -I capture/record.py [--frames]                       # live: your TFT window, Ctrl-C to stop
    python3 -I capture/record.py --vod game.mp4 --mask 0.7,0.6,1,1 # a video file you have; mask the webcam
    python3 -I capture/record.py --window YouTube --mask 0.7,0.6,1,1   # a VOD playing in your browser:
                                                                   # reads the window, saves no video
    python3 -I capture/record.py --replay recordings/<dir>/rows.jsonl.gz   # re-parse with a newer reader
    ->  recordings/<dir>/state.jsonl   (review: engine/review.py)

Storage: every read keeps its OCR text and boxes in rows.jsonl.gz (~1 KB a frame gzipped, ~2-3 MB a game),
enough to re-parse later without images. --frames adds small JPEGs (1280 px, ~120 KB): one per stage live,
one a minute for VODs. In VODs the game is found by two HUD landmarks, so scaled/boxed stream layouts work;
--area crops a known game box first; --mask hides webcams or overlays whose text could pass for HUD numbers.

Each line is the last good reading of a stage, in the engine's state format, plus counters the recorder
derives itself: rerolls (gold -2 and the shop replaced, same stage), rerolls before the 2-4 carousel, and
owned units from purchase bookkeeping (a slot empties as gold drops by its cost; sells by sell value).
Units from carousels/augments and items on units are not visible to it.
Live: waits while no TFT window is open; stops if Screen Recording permission is missing.
"""
import argparse
import difflib
import gzip
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "engine")]
from hud import TOOL, counter_targets, locate, masked, plausible_traits, read, to_game  # noqa: E402
from unlocks import load_set, round_type, stage_key  # noqa: E402

CARRY = ("level", "xp", "hp")
MAX_ROUND_LOSS = 35
ITEM_MODEL = HERE.parent / "data/models/items.mlmodel"   # trained by tools/train_items.swift (gitignored)
BUY_CONFIRM, BUY_GIVE_UP = 2, 6        # readings a slot must stay missing to count as bought / to drop it
REWIND_FRAMES = 5                      # readings of an earlier stage before believing a rewind
MIN_PLAYER_READS = 20     # readings of a name in the player list before it counts as a player
BENCH_MIN_CONF = 0.9      # item bench reads kept: components read at ~1.0, unknown art (new consumables,
                          # stream chat over a slot, icons dimmed mid-drag) at 0.6-0.86
INCOME_SECS = 6                        # round income lands as a stage opens: rises then aren't sales


def stars_of(copies):
    return 3 if copies >= 9 else 2 if copies >= 3 else 1


def sell_value(cost, stars):
    return cost * 3 ** (stars - 1) - (1 if stars > 1 and cost > 1 else 0)


def same_name(name, names):
    """A name already in names, allowing an OCR slip ("Nesting Anvills+", "LooptheLoor"); I, l, | and 1 look
    alike in the game's font ("nmSIIIII" reads "nmSHllll")."""
    norm = lambda s: s.lower().translate(str.maketrans("i|1", "lll"))    # noqa: E731
    return any(difflib.SequenceMatcher(None, norm(name), norm(n)).ratio() >= 0.85 for n in names if n)


def picked(final, held):
    """The augment taken from a round's final cards: the one that later shows in the Augments panel. None if
    none or several do (augments granted by other augments were never offered, so they don't interfere).
    ponytail: a scouted player's panel looks the same; a clash with our own cards needs a name check."""
    hits = {f for f in final if f and same_name(f, held)}
    return hits.pop() if len(hits) == 1 else None


def panel(state, trait):
    """A trait as read this round (carried-over traits are guesses: counters only count what was seen)."""
    return next((t for t in state.get("traits", []) if t["name"] == trait and not t.get("carried")), {})


class Recorder:
    def __init__(self, costs=None, unlockables=()):
        self.phases, self.cur, self.prev = [], None, None
        self.counters = {"rerolls": 0, "rerolls_before_2_carousel": 0, "rock_combats": 0, "xayah_interest": 0}
        self.unlockables, self.unlocked = set(unlockables), set()
        self.streak, self.streak8 = (None, 0), (None, 0)     # (win/loss, length); streak8 only at level 8+
        self.first = None                                    # first stage seen; joining late hides early counts
        self.costs = costs or {}          # unit -> shop cost, for purchase bookkeeping
        self.gates = {}                   # unlockable -> min level, to flag rule conflicts
        self.hp_seen = []                 # HP readings this round (mode wins: single misreads don't)
        self.trait_seen, self.trait_lens = {}, []   # trait panel readings this round (and their sizes), smoothed at round end
        self.streak_reads = []            # HUD streak readings this round
        self.shop_seen = set()            # this round: every unit offered in any shop (rerolls included)
        self.item_offer = None            # this round: the cards of an item choice (artifacts, components...)
        self.scout_reads = []             # this round: trait panels read while scouting another board
        self.hud_streak, self.fights = None, 0   # last streak that fit the streak rule, PvP fights since
        self.trait_info = {}              # static traits by name (breakpoints, counts units/stars)
        self.conflicts = set()
        self.owned = {}                   # unit -> copies bought and not sold
        self.slots, self.pending, self.bought = {}, {}, set()     # tracked shop, slots going missing, bought
        self.acquired = {}                # unit -> order of its latest purchase (oldest are sold first)
        self.gold_known = None            # last gold actually read (purchases are judged against it)
        self.augments = []                # per augment round: {"stage", "offered": every card seen, "final": last 3}
        self.held = []                    # names seen in the game's Augments panel, in order
        self.lobby_reads = {}             # this round: other player -> HP readings
        self.level_reads = {}             # this round: other player -> level badge readings
        self.lobby_names = Counter()      # every player name seen this game (first spelling kept) -> readings
        self.unit_reads = []              # this round's unit readings (pixels), for the consensus board
        self.bench_item_reads = []        # this round's item bench readings (sorted item names)
        self.back = 0                     # consecutive readings of an earlier stage
        self.unattributed = 0             # gold changes the ledger couldn't explain

    def _counters(self):
        """Counters we can vouch for: the pre-carousel reroll count only if we watched from the first shop."""
        c = dict(self.counters)
        if self.first and stage_key(self.first) > stage_key("1-2"):
            c.pop("rerolls_before_2_carousel", None)
        return c

    def _sell(self, p, r):
        """A gold rise matching exactly one owned unit's sell value is a sale; others are unattributed."""
        if None in (p.get("gold"), r.get("gold")) or r["gold"] <= p["gold"]:
            return
        cands = [(u, s) for u, c in self.owned.items() for s in (1, 2, 3)
                 if c >= 3 ** (s - 1) and sell_value(self.costs[u], s) == r["gold"] - p["gold"]]
        if len(cands) == 1:
            u, s = cands[0]
            self.owned[u] -= 3 ** (s - 1)
        else:
            self.unattributed += 1

    def _shop(self, r):
        """Track the shop across readings. Reroll: 3+ slots changed in the same stage (gold not required).
        Buy: a card goes missing, stays missing for BUY_CONFIRM readings, and gold is SEEN to have dropped by
        its cost since just before it vanished (cards vanishing together must be paid for together). No shop
        on screen (combat camera, closed shop, menus) says nothing; unread gold means a missed buy, never an
        invented one."""
        now = {s["slot"]: s["unit"] for s in r.get("shop", [])}
        if not now:
            return
        gold = r.get("gold")

        both = [k for k in now if k in self.slots]
        if len(both) >= 3 and sum(now[k] != self.slots[k] for k in both) >= 3:
            self._confirm(gold, reroll=True)                # bought just before rerolling
            self.counters["rerolls"] += 1
            if stage_key(r["t"]) < stage_key("2-4"):
                self.counters["rerolls_before_2_carousel"] += 1
            self.slots, self.pending, self.bought = dict(now), {}, set()
            self._note_gold(gold)
            return
        for k, unit in list(self.slots.items()):
            if k in now or k in self.bought:
                self.pending.pop(k, None)
            elif k not in self.pending:      # readings missing, gold before, order, lowest gold seen since
                self.pending[k] = [1, self.gold_known, len(self.pending), None]
            else:
                self.pending[k][0] += 1
        for p in self.pending.values():      # a sale right after a buy must not hide the payment
            if gold is not None:
                p[3] = gold if p[3] is None else min(p[3], gold)
        self._confirm(gold)
        for k in [k for k, p in self.pending.items() if p[0] >= BUY_GIVE_UP]:
            self.pending.pop(k)                           # never seen paid for: an OCR gap (or unread gold)
        for k, unit in now.items():
            if k in self.bought and unit != self.slots.get(k):
                self.bought.discard(k)
            self.slots[k] = unit
        self._note_gold(gold)

    def _note_gold(self, gold):
        if gold is not None:
            self.gold_known = gold

    def _confirm(self, gold, reroll=False):
        """Book pending cards whose cost the observed gold drop covers, in the order they vanished."""
        if gold is None:
            return
        ready = sorted(((k, p) for k, p in self.pending.items() if (p[0] >= BUY_CONFIRM or reroll)
                        and p[1] is not None and self.slots.get(k) in self.costs), key=lambda kp: kp[1][2])
        for k, _ in ready:
            n, g0, order, low = self.pending[k]
            cost = self.costs[self.slots[k]]
            low = min(gold, low if low is not None else gold)
            if g0 - low - (2 if reroll else 0) >= cost:
                self._buy(self.slots[k])
                self.bought.add(k)
                self.pending.pop(k)
                for p in self.pending.values():         # that gold is spent: others measured from the same
                    if p[1] == g0:                       # starting gold now need a further drop
                        p[1] -= cost

    def smooth_traits(self, level, prev=()):
        """Round's trait panel: traits seen in 1/3+ of readings, or (the panel scrolls, so each part shows
        only part of the time) in 1/6+ and read active 80%+ of the time; count = most common plausible
        reading (at most level+2 units, x3 for star-counting traits); active from the real breakpoints.
        Readings that caught under half the panel (collapsed in combat, an overlay) don't count: at 4-6 of
        one game 29 of 39 readings saw 1-2 traits and the real ones dropped out. Traits the panel's badge
        says are hidden ("2+", "+9") carry over from last round's panel (`prev`), marked carried."""
        full = max((n for n, _ in self.trait_lens), default=0)
        whole = [h for n, h in self.trait_lens if 2 * n >= full]
        reads, hidden = len(whole), Counter(whole).most_common(1)[0][0] if whole else 0
        out = []
        for name, seen in self.trait_seen.items():
            seen = [x for x in seen if 2 * x[2] >= full]       # whole-panel readings only
            steady = len(seen) >= 3 and sum(1 for _, a, _ in seen if a) >= 0.8 * len(seen)
            if len(seen) * 3 < reads and not (steady and len(seen) * 6 >= reads):
                continue
            info = self.trait_info.get(name, {})
            cap = ((level or 9) + 2) * (3 if info.get("counts") == "stars" else 1)
            counts = [c for c, _, _ in seen if c is not None and 0 < c <= cap]
            count = max(set(counts), key=counts.count) if counts else None
            first = (info.get("breakpoints") or [None])[0]
            if count is not None and first:
                active = count >= first
            else:
                acts = [a for _, a, _ in seen if a is not None]
                active = max(set(acts), key=acts.count) if acts else None
            out.append({"name": name, "count": count, "active": active, "count_is_lower_bound": count is None})
        self.trait_seen, self.trait_lens = {}, []
        shown = {x["name"] for x in out}
        out += [dict(x, carried=True) for x in prev if x["name"] not in shown][:hidden]
        return sorted(out, key=lambda x: (not x["active"], -(x["count"] or 0)))

    def _buy(self, unit):
        self.owned[unit] = self.owned.get(unit, 0) + 1
        self.acquired[unit] = len(self.acquired) + sum(self.owned.values())

    def cap_owned(self, level):
        """Sells are often missed (combat gold hides them), but nobody holds more than level + 9 units
        (board + bench): drop the longest-held units first, as players sell early units first."""
        cap = (level or 9) + 9
        while sum(1 for c in self.owned.values() if c > 0) > cap:
            oldest = min((u for u, c in self.owned.items() if c > 0), key=lambda u: self.acquired.get(u, 0))
            self.owned[oldest] = 0

    def close_pending(self):
        """End of a round or recording: cards that went missing count as bought if the last gold read covers
        them (however briefly they were seen missing)."""
        for p in self.pending.values():
            p[0] = max(p[0], BUY_CONFIRM)
        self._confirm(self.gold_known)
        self.pending = {}

    def feed(self, r, ts):
        """Take one HUD reading. Returns the finished phase state when the stage changes, else None."""
        if r.get("t") is None:
            return None                                   # loading, carousel camera, menus: no stage
        self.first = self.first or r["t"]
        if r.get("gold_alt") is not None and self.gold_known is not None and \
                abs(r["gold_alt"] - self.gold_known) < abs(r["gold"] - self.gold_known):
            r["gold"] = r["gold_alt"]                     # "94" right after 6 gold was the coin + 4
        # our own HUD bar on screen: scouting another board hides it, and then the trait panel, the bars and
        # the item bench show that player's (robinsongz game, 4-6: 160 such frames read as our traits)
        # (stage 1 shows no readable level or gold: taken as ours)
        own = r.get("level") is not None or r.get("gold") is not None or stage_key(r["t"]) < stage_key("2-1")
        if self.prev:
            for k in CARRY:
                if r.get(k) is None:
                    r[k] = self.prev.get(k)
        finished = None
        if self.cur and stage_key(r["t"]) < stage_key(self.cur["stage"]):
            self.back += 1                                   # a misread, unless it persists (a rewind)
            if self.back < REWIND_FRAMES:
                return None
        self.back = 0
        if self.cur and r["t"] != self.cur["stage"]:
            self.close_pending()
            self.cap_owned(self.cur.get("level"))
            self.cur["owned"] = [{"unit": u, "copies": c, "stars": stars_of(c)}
                                 for u, c in sorted(self.owned.items()) if c > 0]
            finished = self.cur
            self._close_phase(finished)
            self._append(finished)
            self.prev = None
            self.slots, self.pending, self.bought = {}, {}, set()   # a new round brings a new shop
        if finished or not self.cur:
            self.stage_ts = ts
        if self.prev and ts - self.stage_ts >= INCOME_SECS:
            self._sell(self.prev, r)
        self._shop(r)
        self.counters.update(r.get("tracker") or {})        # the game's own x/N beats our estimates
        if r.get("units") and own:
            self.unit_reads.append(r["units"])
        if r.get("bench_items") is not None and own:
            self.bench_item_reads.append(tuple(sorted(r["bench_items"])))
        if r.get("augments"):
            if not self.augments or self.augments[-1]["stage"] != r["t"]:
                self.augments.append({"stage": r["t"], "offered": [], "final": []})
            a = self.augments[-1]
            names = [c and c["name"] for c in r["augments"]]
            a["final"] = [n or f for n, f in zip(names, a["final"] or names)]       # rerolled cards replace
            a["offered"] += [n for n in names if n and not same_name(n, a["offered"])]
            for c in r["augments"]:                                               # longest read of each text
                if c and len(c["desc"]) > len(a.setdefault("desc", {}).get(c["name"], "")):
                    a["desc"][c["name"]] = c["desc"]
        for n, hp in (r.get("lobby") or {}).items():
            n = next((m for m in self.lobby_names if same_name(n, [m])), n)
            self.lobby_names[n] += 1
            self.lobby_reads.setdefault(n, []).append(hp)
        for n, lv in (r.get("lobby_levels") or {}).items():
            n = next((m for m in self.lobby_names if same_name(n, [m])), n)
            self.level_reads.setdefault(n, []).append(lv)
        for n in r.get("held_augments") or []:
            if n not in self.held:
                self.held.append(n)
        if "rerolls_before_2_carousel" in (r.get("tracker") or {}):
            self.first = "1-1"                               # the game told us the true count
        # a newly unlocked unit always shows up in the next shop, so any unlockable seen there is unlocked
        seen = self.unlockables & ({s["unit"] for s in r.get("shop", [])} | set(self.owned))
        for u in seen - self.unlocked:
            if (r.get("level") or 0) < self.gates.get(u, 0):    # in a shop before its gate: our rule is stale
                self.conflicts.add(f"{u} in shop at level {r.get('level')} (rule says level {self.gates[u]}+)")
        self.unlocked |= seen
        if r.get("hp") is not None:
            self.hp_seen.append(r["hp"])
        if r.get("streak_n") is not None:
            self.streak_reads.append(r["streak_n"])
        if own:
            self.shop_seen |= {x["unit"] for x in r.get("shop") or []}
        if r.get("item_offers"):
            self.item_offer = r["item_offers"]         # an item choice this round (the last one read)
        elif r.get("traits") and round_type(r["t"]) != "carousel":
            self.scout_reads.append(r["traits"])
        if r.get("traits") and own:
            self.trait_lens.append((len(r["traits"]), r.get("traits_hidden") or 0))
            for x in r["traits"]:
                self.trait_seen.setdefault(x["name"], []).append((x.get("count"), x.get("active"), len(r["traits"])))
        same = self.cur is not None and self.cur["stage"] == r["t"]
        self.cur = {"stage": r["t"], "level": r.get("level"), "xp": r.get("xp"),
                    "gold": r["gold"] if r.get("gold") is not None else (self.cur["gold"] if same else None),
                    "hp": r.get("hp"), "streak_n": r.get("streak_n"), "traits": r.get("traits", []),
                    "board_count": r.get("board_count"),
                    # the last shop seen this round (a dragged unit or a closed shop hides it for a moment)
                    "shop": r.get("shop") or (self.cur["shop"] if self.cur and self.cur["stage"] == r["t"] else []),
                    "counters": self._counters(),
                    # your units' bars and items (pixels, when read): last reading of the round with any
                    "units": r.get("units") or (self.cur.get("units") if self.cur and self.cur["stage"] == r["t"] else None),
                    "owned": [{"unit": u, "copies": c, "stars": stars_of(c)} for u, c in sorted(self.owned.items()) if c > 0],
                    "ledger_unattributed": self.unattributed, "unlocked": sorted(self.unlocked),
                    "augment_offers": [dict(a, offered=list(a["offered"]), desc=dict(a.get("desc", {})),
                                            picked=picked(a["final"], self.held)) for a in self.augments],
                    "quality": r.get("quality", {}), "ts": round(ts, 1)}
        self.prev = r
        return finished

    def _append(self, s):
        """A rewound video replays stages: the later reading of a stage replaces the earlier one."""
        self.phases = [p for p in self.phases if stage_key(p["stage"]) < stage_key(s["stage"])] + [s]

    def _close_phase(self, s):
        """Facts known only once a round is over: result, streaks, end-of-combat gold, derived counters."""
        prev = next((p for p in reversed(self.phases) if stage_key(p["stage"]) < stage_key(s["stage"])), None)
        if self.hp_seen:                                     # most common reading of the round
            mode = max(set(self.hp_seen), key=self.hp_seen.count)
            if prev and prev.get("hp") is not None and not (prev["hp"] - MAX_ROUND_LOSS <= mode <= prev["hp"] + 5):
                mode = prev["hp"]                    # HP doesn't rise, and no round costs more than ~35: a misread
            s["hp"] = mode
            self.hp_seen = []
        s["rule_conflicts"] = sorted(self.conflicts)
        # our units from our own view only (a raw reading may be a scouted board)
        s["units"] = consensus_units(self.unit_reads) if self.unit_reads else None
        self.unit_reads = []
        if len(self.bench_item_reads) >= 2:              # items held: the round's most common reading
            s["items_held"] = list(max(set(self.bench_item_reads), key=self.bench_item_reads.count))
        self.bench_item_reads = []
        # other players' HP this round: the most common of 2+ readings (one frame misreads digits)
        # the other 7 are read ~10 times a round all game; fragments ("ota") and toasts only now and then
        players = {n for n, k in self.lobby_names.most_common(7) if k >= MIN_PLAYER_READS}
        s["lobby_hp"] = {n: max(set(v), key=v.count) for n, v in self.lobby_reads.items() if len(v) >= 2 and n in players}
        self.lobby_reads = {}
        s["lobby_level"] = {n: max(set(v), key=v.count) for n, v in self.level_reads.items() if len(v) >= 2 and n in players}
        self.level_reads = {}
        if self.trait_lens:
            s["traits"] = self.smooth_traits(s.get("level"), (prev or {}).get("traits") or [])
        elif prev and prev.get("traits"):                 # no reading of our own panel (scouting, carousel)
            s["traits"] = [dict(x, carried=True) for x in prev["traits"]]
        kind = round_type(s["stage"])
        s["gold_end_combat"] = s.get("gold")
        # a planning phase shows the HP left by the previous round's combat, so "result" is that combat's
        # result (and the streak the game shows now); only PvP combats count toward streaks
        if prev and round_type(prev["stage"]) == "pvp" and None not in (s.get("hp"), prev.get("hp")):
            res = "loss" if s["hp"] < prev["hp"] else "win"
            s["result"] = res
            self.streak = (res, self.streak[1] + 1 if self.streak[0] == res else 1)
            self.streak8 = ((res, self.streak8[1] + 1 if self.streak8[0] == res else 1)
                            if (s.get("level") or 0) >= 8 else (None, 0))
        if kind != "carousel" and panel(s, "Rock").get("active"):
            self.counters["rock_combats"] += 1
        if panel(s, "Gu Feng").get("count") and s.get("gold") is not None:      # Xayah (or a Gu Feng unit) fielded
            self.counters["xayah_interest"] += min(s["gold"] // 10, 5)
        s["streak_n"] = self._streak_n(s["stage"])
        s["shop_seen"], self.shop_seen = sorted(self.shop_seen), set()
        if self.item_offer:
            s["item_offer"], self.item_offer = self.item_offer, None
        s["scouted"], self.scout_reads = scouted_boards(self.scout_reads, s.get("traits")), []
        # HUD gives the streak length, HP changes give its direction
        s["streak"] = {"type": self.streak[0], "n": s.get("streak_n") or self.streak[1]}
        s["streak_l8"] = {"type": self.streak8[0], "n": self.streak8[1]}
        s["counters"] = self._counters()

    def _streak_n(self, stage):
        """The HUD streak after this round: the latest reading the streak rule allows (after a PvP fight the
        last streak + 1 or a restart at 1, else unchanged). Misreads ("6" read as "9" in 42 frames of one
        game) fail the rule and are dropped; none allowed -> unread, and the next round allows both steps.
        Watched from 2-1 the streak starts at 0; joined later, the round's last reading starts it."""
        reads, self.streak_reads = self.streak_reads, []
        if self.hud_streak is None and self.first and stage_key(self.first) <= stage_key("2-1"):
            self.hud_streak = 0
        self.fights += round_type(stage) == "pvp"
        if self.hud_streak is None:
            ok = reads[-1:]
        else:
            allowed = {self.hud_streak + self.fights, *range(1, self.fights + 1)} if self.fights else {self.hud_streak}
            ok = [k for k in reads if k in allowed]
        if not ok:
            return None
        self.hud_streak, self.fights = ok[-1], 0
        return ok[-1]

    def close(self):
        self.close_pending()
        self.cap_owned((self.cur or {}).get("level"))
        if self.cur:
            self.cur["owned"] = [{"unit": u, "copies": c, "stars": stars_of(c)}
                                 for u, c in sorted(self.owned.items()) if c > 0]
        if self.cur and (not self.phases or self.phases[-1] is not self.cur):
            self._close_phase(self.cur)
            self._append(self.cur)
            return self.cur
        return None


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def scouted_boards(reads, own):
    """Other players' trait panels seen while scouting this round, one per board: readings grouped by the
    traits they list (half the names shared = the same board), groups read 2+ times, our own panel left out
    (an item choice or overlay hides the HUD bar too). Per board, the traits in 1/3+ of its readings with
    their most common count. A panel is ours when most of its (trait, count) pairs are ours: a board scouted
    at 6-6 shared Choreographer 2 and Arcanist 2 with ours but had Frontman 4 to our 2 and no Beach Pop."""
    mine, groups = {(x["name"], x.get("count")) for x in own or []}, []
    for traits in reads:
        names = {x["name"] for x in traits}
        g = next((g for g in groups if jaccard(names, g[0]) >= 0.5), None)
        if g:
            g[0] |= names
            g[1].append(traits)
        else:
            groups.append([set(names), [traits]])
    out = []
    for names, rs in groups:
        if len(rs) < 2:
            continue
        seen = {}
        for traits in rs:
            for x in traits:
                seen.setdefault(x["name"], []).append(x)
        panel = []
        for name, xs in seen.items():
            if 3 * len(xs) >= len(rs):
                counts = [x["count"] for x in xs if x.get("count") is not None]
                acts = [x["active"] for x in xs if x.get("active") is not None]
                panel.append({"name": name, "count": max(set(counts), key=counts.count) if counts else None,
                              "active": max(set(acts), key=acts.count) if acts else None,
                              "count_is_lower_bound": not counts})
        pairs = {(x["name"], x["count"]) for x in panel}
        if panel and not (mine and len(pairs & mine) >= 0.6 * min(len(pairs), len(mine))):
            out.append(sorted(panel, key=lambda x: (not x["active"], -(x["count"] or 0))))
    return out


def consensus_units(reads, near=0.012):
    """A round's units from all its readings: bars grouped by position; per slot, the item at least two
    readings and half of that unit's readings agree on (items don't change mid-round; one frame's misread
    doesn't count); stars = the most common star badge read. Units seen in under a third of readings are
    dropped (drag animations, flicker)."""
    groups = []                                           # [x, y, [item lists], unit, [star reads]]
    for units in reads:
        for u in units:
            g = next((g for g in groups if abs(g[0] - u["x"]) < near and abs(g[1] - u["y"]) < near), None)
            if g is None:
                groups.append([u["x"], u["y"], [], u, []])
                g = groups[-1]
            g[2].append([i[0] for i in u.get("items", [])])
            if u.get("stars"):
                g[4].append(u["stars"])
    out = []
    for x, y, lists, u, stars in groups:
        if len(lists) * 3 < len(reads):
            continue
        items = []
        for k in range(3):
            labels = [lst[k] for lst in lists if len(lst) > k]
            best = max(set(labels), key=labels.count) if labels else None
            if best is None or labels.count(best) < max(2, len(lists) / 2):
                break
            items.append(best)
        out.append({k: u[k] for k in ("x", "y", "w", "h")} | {"items": items, "reads": len(lists)}
                   | ({"stars": max(set(stars), key=stars.count)} if stars else {}))
    return sorted(out, key=lambda u: (u["y"], u["x"]))


def round_rows(rows):
    """Compact OCR rows for storage: 4-decimal boxes, 2-decimal confidence (~1 KB a frame gzipped)."""
    return [{"text": r["text"], "conf": round(r.get("conf", 1), 2),
             **{k: round(r[k], 4) for k in ("x", "y", "w", "h")}, **({"zoom": True} if r.get("zoom") else {})}
            for r in rows]


def live_frames(every, frames_dir, window=None):
    """(time, OCR rows) from the TFT window; waits while it's closed, stops on missing permission."""
    waiting = False
    while True:
        t0 = time.time()
        p = subprocess.run([str(TOOL), "read"] + ([str(frames_dir / "last.jpg")] if frames_dir else [])
                           + (["--window", window] if window else []), capture_output=True, text=True)
        if p.returncode == 2:
            if not waiting:
                print(f"waiting for the {window or 'TFT'} window ...")
            waiting = True
            time.sleep(5)
            continue
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip())
        waiting = False
        yield t0, [json.loads(x) for x in p.stdout.splitlines() if x.strip()], None, None
        time.sleep(max(0.0, every - (time.time() - t0)))


def vod_frames(video, every, area, frames_dir, speed=1.0):
    """(game seconds, OCR rows, units, held items) sampled every `every` game seconds; a sped-up video (speed 2)
    is read twice as often in video time, so each round gets the same number of readings. Units (health bars
    and their items) and the item bench are read when the item model exists."""
    cmd = [str(TOOL), "vod", str(video), "--every", str(every / speed)] + (["--area", area] if area else []) \
        + (["--jpeg-dir", str(frames_dir), "--jpeg-every", "60"] if frames_dir else []) \
        + (["--units", "--model", str(ITEM_MODEL)] if ITEM_MODEL.exists() else [])
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as p:
        for line in p.stdout:
            if line.strip():
                d = json.loads(line)
                yield d["t"] * speed, d["rows"], d.get("units"), d.get("held")
        if p.wait() != 0:
            raise RuntimeError(p.stderr.read().strip())


def replay_frames(path):
    """Stored OCR rows (rows.jsonl.gz) for re-parsing with a newer reader, no capture needed."""
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                yield d["t"], d["rows"], d.get("units"), d.get("held")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--vod", help="video file to read instead of the live TFT window")
    src.add_argument("--replay", help="rows.jsonl.gz from an earlier recording: re-parse without capture")
    ap.add_argument("--every", type=float, default=None, help="seconds between reads (live 1, vod 2)")
    ap.add_argument("--speed", type=float, default=1.0, help="vod: playback speed of the video (2 for a 2x edit)")
    ap.add_argument("--area", help="vod: crop to x0,y0,x1,y1 (fractions) before reading")
    ap.add_argument("--mask", action="append", default=[], help="ignore x0,y0,x1,y1 (frame fractions), e.g. a webcam; repeatable")
    ap.add_argument("--window", help="live: read the window whose app name or title contains this "
                                     "(e.g. 'YouTube' while a VOD plays in a browser) instead of TFT")
    ap.add_argument("--frames", action="store_true", help="keep small JPEGs (live: one per stage; vod: one a minute). "
                    "With --window the JPEG is the whole window: make the video full screen")
    ap.add_argument("--set", default="TFTSet19")
    a = ap.parse_args()
    masks = [tuple(float(x) for x in m.split(",")) for m in a.mask]
    if a.replay:
        out = Path(a.replay).resolve().parent
    else:
        tag = f"vod-{Path(a.vod).stem[:40]}-" if a.vod else (f"watch-{a.window[:20]}-" if a.window else "")
        out = HERE.parent / "recordings" / (tag + time.strftime("%Y%m%d-%H%M%S"))
        out.mkdir(parents=True, exist_ok=True)
    frames_dir = out / "frames" if a.frames and not a.replay else None
    if frames_dir:
        frames_dir.mkdir(exist_ok=True)
    static = load_set(a.set)
    roster = [u["name"] for u in static["units"]]
    targets = counter_targets(static["unlocks"])
    rec = Recorder({u["name"]: u["cost"] for u in static["units"]}, {u["unit"] for u in static["unlocks"]})
    rec.gates = {u["unit"]: u.get("min_level") or 0 for u in static["unlocks"]}
    rec.trait_info = {t["name"]: t for t in static["traits"]}
    state_path = out / ("state.replay.jsonl" if a.replay else "state.jsonl")
    log = open(state_path, "w")
    rows_log = None if a.replay else gzip.open(out / "rows.jsonl.gz", "at", compresslevel=9)
    frames = (replay_frames(a.replay) if a.replay else
              vod_frames(a.vod, a.every or 2, a.area, frames_dir, a.speed) if a.vod else live_frames(a.every or 1, frames_dir, a.window))
    print(f"recording to {out.relative_to(HERE.parent) if out.is_relative_to(HERE.parent) else out}; Ctrl-C to stop")

    def write(state):
        log.write(json.dumps(state) + "\n")
        log.flush()
        print(f"  saved {state['stage']}")

    transform, last, error = None, None, None
    import signal                                  # a stop from outside (kill/TaskStop) finishes files cleanly
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        for ts, rows, units, held in frames:
            r = read(rows, static["units"], static["traits"], targets=targets, masks=masks, transform=transform)
            plausible_traits(r["traits"], static)
            transform = r["quality"]["transform"] or transform        # stream layouts don't move
            # stage 1 shows no "Lvl." and its stage text sits off the usual spot, so no mapping is found; the reader
            # then read the frame as-is, and its rows are kept as-is (they were dropped: replays began at 2-1)
            tf = locate(masked(rows, masks)) or transform or ((1.0, 0.0, 1.0, 0.0) if r.get("t") else None)
            if rows_log and tf and r.get("t"):
                # keep only text inside the game area, in game coordinates: browser tabs, sidebars, chat and
                # ads never reach the log (privacy, and less storage); frames without the HUD keep nothing
                game_rows = [g for g in to_game(masked(rows, masks), tf) if 0 <= g["x"] <= 1 and 0 <= g["y"] <= 1]
                entry = {"t": round(ts, 1), "rows": round_rows(game_rows)}
                if units is not None:                  # units are frame fractions too: same mapping as the text
                    units = [dict(u, **{k: round(v, 4) for k, v in g.items() if k in "xywh"}, items=[
                        [x[0], round(x[1], 2)] for x in u["items"]]) for u, g in zip(units, to_game(units, tf))
                        if 0 <= g["x"] <= 1 and 0 <= g["y"] <= 1]
                    entry["units"] = units
                if held is not None:                   # item bench: [slot, item, conf, ...]
                    entry["held"] = [[h[0], h[1], round(h[2], 2)] for h in held]
                rows_log.write(json.dumps(entry, separators=(",", ":")) + "\n")
            if units is not None and r.get("t"):
                r["units"] = units
            if held is not None and r.get("t"):
                r["bench_items"] = [h[1] for h in held if h[2] >= BENCH_MIN_CONF]
            done = rec.feed(r, ts)
            if done:
                write(done)
            if frames_dir and not a.vod and r.get("t") and r["t"] != last:
                shutil.copy(frames_dir / "last.jpg", frames_dir / f"{r['t']}.jpg")
                last = r["t"]
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        error = str(e)
    final = rec.close()
    if final:
        write(final)
    log.close()
    state_path.write_text("".join(json.dumps(s) + "\n" for s in rec.phases))   # rewinds deduped
    if rows_log:
        rows_log.close()
    if frames_dir and (frames_dir / "last.jpg").exists():
        (frames_dir / "last.jpg").unlink()
    if not rec.phases and not a.replay:
        shutil.rmtree(out)                                        # nothing recorded: leave no empty folder
    else:
        size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
        print(f"{len(rec.phases)} planning phases -> {state_path.name}; folder {size / 1e6:.1f} MB")
    if error:
        sys.exit(error)


if __name__ == "__main__":
    main()
