#!/usr/bin/env python3
"""Post-game report from Riot's TFT match API: gold left, level and board value, measured against
the other players in your own lobbies.

    export RIOT_API_KEY=RGAPI-...       # developer.riotgames.com; development keys expire every 24 h
    python3 -I tools/postgame.py "Name#TAG" [--region americas] [--count 20]

Matches are cached in data/matches/, so a rerun costs two API calls plus any new games.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from riot import Riot, RiotError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "matches"
QUEUES = {1090: "normal", 1100: "ranked"}       # hyper roll / double up placements aren't comparable
RARITY_COST = {0: 1, 1: 2, 2: 3, 4: 4, 6: 5}    # fallback when CommunityDragon has no cost for a unit
GOLD_LEFT_FLAG = 10                             # knocked out holding this much = rolls/XP never bought


_client = None


def api(region, path, key):
    """GET through the shared rate-limited client; exits with Riot's message on errors."""
    global _client
    _client = _client or Riot(key)
    try:
        return _client.get(region, path)
    except RiotError as e:
        sys.exit(str(e))


def load_champs():
    """apiName -> (name, cost) from the CommunityDragon file tools/extract_unlocks.py downloads."""
    p = ROOT / "data/raw/pbe/en_us.json"
    if not p.exists():
        return {}
    return {c["apiName"].lower(): (c["name"], c["cost"])
            for s in json.loads(p.read_text())["setData"] for c in s["champions"] if c.get("apiName")}


def stage(last_round):
    """Riot counts rounds from 1-1: stage 1 has 4 rounds, later stages 7. Verify on a known game."""
    if last_round <= 4:
        return f"1-{last_round}"
    s, r = divmod(last_round - 5, 7)
    return f"{s + 2}-{r + 1}"


def unit_cost(u, champs):
    return champs.get(u["character_id"].lower(), (None, None))[1] or RARITY_COST.get(u.get("rarity"))


def board_value(units, champs):
    """Gold sunk into the final board: cost x copies (3 copies per star step)."""
    return sum((unit_cost(u, champs) or 0) * 3 ** (u["tier"] - 1) for u in units)


def board_text(units, champs):
    def name(u):
        return champs.get(u["character_id"].lower(), (u["character_id"].split("_", 1)[-1],))[0]
    units = sorted(units, key=lambda u: (-len(u.get("itemNames", [])), -(unit_cost(u, champs) or 0)))
    return " ".join(f"{name(u)}{'*' * u['tier']}" + (f"[{len(u['itemNames'])}]" if u.get("itemNames") else "")
                    for u in units)


def report(matches, puuid, champs):
    out, mine, lobby_b4_gold, level_gap, value_rank, aug_rows = [], [], [], [], [], [0, 0]
    out.append(f"{'date':<11}{'queue':<8}{'place':>5}{'lvl':>5}{'peer lvl':>9}{'out at':>8}"
               f"{'gold left':>10}{'board $':>8}{'rank':>6}  flags")
    for m in sorted(matches, key=lambda m: m["info"]["game_datetime"]):
        info, ps = m["info"], m["info"]["participants"]
        for p in ps:
            p["_value"] = board_value(p["units"], champs)
            aug_rows[0] += 1
            aug_rows[1] += bool(p.get("augments"))
        me = next(p for p in ps if p["puuid"] == puuid)
        others = [p for p in ps if p is not me]
        # players knocked out in the same stage are the fair comparison for level at elimination
        my_stage = stage(me["last_round"]).split("-")[0]
        peers = [p for p in others if stage(p["last_round"]).split("-")[0] == my_stage]
        peer_lvl = mean(p["level"] for p in peers) if peers else None
        peer_txt = "-" if peer_lvl is None else f"{peer_lvl:.1f}"
        rank = 1 + sum(p["_value"] > me["_value"] for p in others)
        flags = []
        if me["placement"] > 1 and me["gold_left"] >= GOLD_LEFT_FLAG:   # any elimination wastes it
            flags.append(f"died holding {me['gold_left']} gold")
        if peer_lvl is not None and me["level"] < peer_lvl - 0.5:
            flags.append("behind same-stage players on level")
        mine.append(me)
        lobby_b4_gold += [p["gold_left"] for p in others if p["placement"] > 4]
        if peer_lvl is not None:
            level_gap.append(me["level"] - peer_lvl)
        value_rank.append(rank)
        date = datetime.fromtimestamp(info["game_datetime"] / 1000).strftime("%Y-%m-%d")
        out.append(f"{date:<11}{QUEUES.get(info.get('queue_id'), '?'):<8}{me['placement']:>5}{me['level']:>5}"
                   f"{peer_txt:>9}{stage(me['last_round']):>8}"
                   f"{me['gold_left']:>10}{me['_value']:>8}{rank:>4}/8  {'; '.join(flags)}")
        out.append(f"{'':<11}{board_text(me['units'], champs)}")
    if not mine:
        return "No ranked or normal games in the fetched matches."
    b4 = [p["gold_left"] for p in mine if p["placement"] > 4]
    out += ["",
            f"{len(mine)} games: avg place {mean(p['placement'] for p in mine):.2f}, "
            f"top 4 {sum(p['placement'] <= 4 for p in mine) / len(mine):.0%}",
            f"gold left in bottom-4 finishes: you {mean(b4):.1f} vs your lobbies {mean(lobby_b4_gold):.1f}"
            if b4 and lobby_b4_gold else "no bottom-4 finishes",
            f"level vs players knocked out in the same stage: {mean(level_gap):+.2f}" if level_gap else None,
            f"final board value rank in lobby: {mean(value_rank):.1f} of 8 (placement {mean(p['placement'] for p in mine):.1f})",
            f"augments present in match data: {aug_rows[1]} of {aug_rows[0]} player records"]
    return "\n".join(line for line in out if line is not None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("riot_id", help='your Riot ID, e.g. "Name#NA1"')
    ap.add_argument("--region", default="americas", choices=["americas", "europe", "asia", "sea"])
    ap.add_argument("--count", type=int, default=20, help="recent matches to fetch (max 200)")
    a = ap.parse_args()
    key = os.environ.get("RIOT_API_KEY") or sys.exit("Set RIOT_API_KEY first (developer.riotgames.com).")
    name, _, tag = a.riot_id.partition("#")
    if not tag:
        sys.exit('Riot ID needs its tag, e.g. "Name#NA1".')
    account_region = "asia" if a.region == "sea" else a.region   # account-v1 has no sea cluster
    puuid = api(account_region, f"/riot/account/v1/accounts/by-riot-id/{quote(name, safe='')}/"
                                f"{quote(tag, safe='')}", key)["puuid"]
    ids = api(a.region, f"/tft/match/v1/matches/by-puuid/{puuid}/ids?count={a.count}", key)
    CACHE.mkdir(parents=True, exist_ok=True)
    matches = []
    for mid in ids:
        f = CACHE / f"{mid}.json"
        if not f.exists():
            f.write_text(json.dumps(api(a.region, f"/tft/match/v1/matches/{mid}", key)))
        m = json.loads(f.read_text())
        if m["info"].get("queue_id") in QUEUES:
            matches.append(m)
    print(report(matches, puuid, load_champs()))


if __name__ == "__main__":
    main()
