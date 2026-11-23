# Crawler on a fake Riot API built from the cached matches; rate limiter on a fake clock. No network.
#   python3 -I tests/test_crawl.py
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if not any((ROOT / "data" / "matches").glob("*.json")):          # Riot match data: stays on this machine
    print("skip: needs data/matches from tools/postgame.py or tools/crawl.py")
    sys.exit()
sys.path.insert(0, str(ROOT / "tools"))
from crawl import Crawler, read_matches  # noqa: E402
from riot import RateLimiter, RiotError  # noqa: E402

matches = {json.loads(f.read_text())["metadata"]["match_id"]: json.loads(f.read_text())
           for f in (ROOT / "data/matches").glob("*.json")}
assert matches, "needs data/matches from tools/postgame.py"
ids = sorted(matches)
calls = []


def fake_get(host, path):
    calls.append(path)
    if path.startswith("/tft/league/v1/challenger"):
        return {"entries": [{"puuid": "p1", "leaguePoints": 900}, {"summonerId": "s2", "leaguePoints": 1200}]}
    if path.startswith("/tft/league/v1/"):
        raise RiotError(403, path, "")                      # other ladders unavailable: skipped, not fatal
    if path.startswith("/tft/summoner/v1/summoners/s2"):
        return {"puuid": "p2"}
    if "/by-puuid/p1/" in path:
        return ids[:12]
    if "/by-puuid/p2/" in path:
        return ids[8:] + ["NA1_missing"]
    if path.startswith("/tft/match/v1/matches/"):
        mid = path.rsplit("/", 1)[1]
        if mid not in matches:
            raise RiotError(404, path, "")
        return matches[mid]
    raise AssertionError(path)


tmp = Path(tempfile.mkdtemp())
try:
    c = Crawler(fake_get, "na1", 17, out=tmp / "crawl/na1/TFTSet17", batch=5, log=lambda *_: None)
    kept = c.run()
    set17 = sum(1 for m in matches.values() if m["info"]["tft_set_number"] == 17 and m["info"]["queue_id"] == 1100)
    assert kept == set17, (kept, set17)                     # only ranked Set 17; Set 18 games filtered out
    assert calls.index("/tft/summoner/v1/summoners/s2") < calls.index("/tft/league/v1/grandmaster")
    stored = list(read_matches(tmp))
    assert len(stored) == set17 and all(m["info"]["tft_set_number"] == 17 for m in stored)
    text = json.dumps(stored)
    assert "puuid" not in text and "riotIdGameName" not in text      # identities dropped
    raw = sum(len(json.dumps(m)) for m in matches.values() if m["info"]["tft_set_number"] == 17)
    packed = sum(f.stat().st_size for f in c.out.glob("*.gz"))
    assert packed < raw / 8, (packed, raw)                            # slim + gzip
    print(f"stored {set17} matches in {packed / 1024:.0f} KB (raw {raw / 1024:.0f} KB)")
    # resume: nothing fetched twice
    calls.clear()
    assert Crawler(fake_get, "na1", 17, out=c.out, log=lambda *_: None).run() == 0
    assert not [p for p in calls if p.startswith("/tft/match/v1/matches/NA1")]
    with gzip.open(next(c.out.glob("*.gz")), "rt") as f:
        assert {"placement", "level", "units", "traits"} <= set(json.loads(f.readline())["info"]["participants"][0])
finally:
    shutil.rmtree(tmp)

# rate limiter: 100 per 120 s and 20 per 1 s are never exceeded
now = [0.0]
lim = RateLimiter(clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
stamps = []
for _ in range(250):
    lim.wait()
    stamps.append(now[0])
assert all(sum(t - 120 < s <= t for s in stamps) <= 100 for t in stamps)
assert all(sum(t - 1 < s <= t for s in stamps) <= 20 for t in stamps)
assert stamps[-1] >= 240                                                # 250 requests need >2 windows
print("ok")
