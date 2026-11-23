#!/usr/bin/env python3
"""Crawl high-rank ranked TFT matches for one set: ladders -> players -> match IDs -> slim, gzipped matches.

    export RIOT_API_KEY=RGAPI-...
    python3 -I tools/crawl.py --platform na1 --set 18 --max-matches 500
    python3 -I tools/crawl.py --platform na1 --set 19 --since 2026-12-02     # after Set 19 launches

Storage: data/crawl/<platform>/TFTSet<N>/matches-NNNN.jsonl.gz (gzip batches of 200 matches, ~2 KB each)
plus seen.txt (match IDs already handled) so a stopped crawl resumes. Player identities are dropped:
the dataset keeps boards, placements, levels, gold, rounds and traits, not puuids or names.
At personal-key rates (100 requests / 2 min) expect ~45 matches a minute after the ladder is fetched.
"""
import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from riot import Riot, RiotError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGION = {"na1": "americas", "br1": "americas", "la1": "americas", "la2": "americas", "euw1": "europe",
          "eun1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe", "kr": "asia", "jp1": "asia",
          "oc1": "sea", "sg2": "sea", "tw2": "sea", "vn2": "sea"}
RANKED = 1100
KEEP_PLAYER = ("placement", "level", "last_round", "gold_left", "time_eliminated", "total_damage_to_players",
               "players_eliminated", "augments")


def slim(m):
    """Only what the models use; no player identities."""
    info = m["info"]
    return {"id": m["metadata"]["match_id"],
            "info": {k: info.get(k) for k in ("game_datetime", "game_version", "queue_id", "tft_set_number")}
            | {"participants": [
                {k: p[k] for k in KEEP_PLAYER if k in p}
                | {"traits": [{k: t[k] for k in ("name", "num_units", "style", "tier_current", "tier_total")}
                              for t in p.get("traits", [])],
                   "units": [{"character_id": u["character_id"], "tier": u["tier"], "itemNames": u.get("itemNames", [])}
                             for u in p.get("units", [])]}
                for p in info["participants"]]}}


def read_matches(root=ROOT / "data"):
    """Every stored match: crawled gzip batches (slim) and data/matches/*.json (full, from postgame)."""
    for f in sorted(root.glob("crawl/*/*/matches-*.jsonl.gz")):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
    for f in sorted(root.glob("matches/*.json")):
        yield json.loads(f.read_text())


class Crawler:
    def __init__(self, get, platform, set_number, out=None, batch=200, log=print):
        self.get, self.platform, self.set = get, platform, set_number
        self.region = REGION[platform]
        self.out = out or ROOT / "data" / "crawl" / platform / f"TFTSet{set_number}"
        self.out.mkdir(parents=True, exist_ok=True)
        self.seen_file = self.out / "seen.txt"
        self.seen = set(self.seen_file.read_text().split()) if self.seen_file.exists() else set()
        self.batch, self.buf, self.new_seen, self.log = batch, [], [], log
        self.kept = 0

    def players(self, tiers):
        out = []
        for tier in tiers:
            try:
                league = self.get(self.platform, f"/tft/league/v1/{tier}")
            except RiotError as e:
                if e.code not in (403, 404):
                    raise                                      # a bad key (401) or outage stops the crawl
                self.log(f"skip {tier}: {e.code}")
                continue
            for e in sorted(league.get("entries", []), key=lambda e: -e.get("leaguePoints", 0)):
                puuid = e.get("puuid")
                if not puuid and e.get("summonerId"):          # older responses: resolve via summoner-v1
                    try:
                        puuid = self.get(self.platform, f"/tft/summoner/v1/summoners/{e['summonerId']}")["puuid"]
                    except RiotError:
                        continue
                if puuid:
                    out.append(puuid)
        return out

    def flush(self):
        if self.buf:
            n = len(list(self.out.glob("matches-*.jsonl.gz")))
            with gzip.open(self.out / f"matches-{n:04d}.jsonl.gz", "wt", compresslevel=9) as f:
                f.writelines(json.dumps(m, separators=(",", ":")) + "\n" for m in self.buf)
            self.buf = []
        if self.new_seen:
            with open(self.seen_file, "a") as f:
                f.writelines(i + "\n" for i in self.new_seen)
            self.new_seen = []

    def take(self, mid):
        try:
            m = self.get(self.region, f"/tft/match/v1/matches/{mid}")
        except RiotError as e:
            if e.code != 404:
                raise
            m = None
        self.seen.add(mid)
        self.new_seen.append(mid)
        if m and m["info"].get("queue_id") == RANKED and m["info"].get("tft_set_number") == self.set:
            self.buf.append(slim(m))
            self.kept += 1
            if self.kept % 25 == 0:
                self.log(f"  {self.kept} matches kept ({len(self.seen)} checked)")
            if len(self.buf) >= self.batch:
                self.flush()

    def run(self, tiers=("challenger", "grandmaster", "master"), per_player=20, max_matches=1000, since=None):
        try:
            players = self.players(tiers)
            self.log(f"{len(players)} players on {self.platform} {'/'.join(tiers)} ladders")
            q = f"count={per_player}" + (f"&startTime={since}" if since else "")   # no queue filter on this endpoint
            for i, puuid in enumerate(players):
                if self.kept >= max_matches:
                    break
                try:
                    ids = self.get(self.region, f"/tft/match/v1/matches/by-puuid/{puuid}/ids?{q}")
                except RiotError as e:
                    if e.code == 404:
                        continue
                    raise
                for mid in ids:
                    if mid not in self.seen and self.kept < max_matches:
                        self.take(mid)
                if i % 10 == 9:
                    self.log(f"  {i + 1} players, {self.kept} new matches")
        finally:
            self.flush()
        return self.kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="na1", choices=sorted(REGION))
    ap.add_argument("--set", type=int, required=True, help="TFT set number, e.g. 18 or 19")
    ap.add_argument("--tiers", default="challenger,grandmaster,master")
    ap.add_argument("--per-player", type=int, default=20)
    ap.add_argument("--max-matches", type=int, default=1000)
    ap.add_argument("--since", help="only matches after this date (YYYY-MM-DD), e.g. the set's launch day")
    a = ap.parse_args()
    key = os.environ.get("RIOT_API_KEY") or sys.exit("Set RIOT_API_KEY first (developer.riotgames.com).")
    since = int(datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) if a.since else None
    c = Crawler(Riot(key).get, a.platform, a.set)
    try:
        n = c.run(a.tiers.split(","), a.per_player, a.max_matches, since)
    except RiotError as e:
        sys.exit(str(e))
    size = sum(f.stat().st_size for f in c.out.glob("*.gz"))
    print(f"{n} new matches; {len(c.seen)} handled in total; {size / 1e6:.1f} MB in {c.out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
