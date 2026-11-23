"""Small Riot API client: User-Agent (Cloudflare blocks urllib's), rate limits, clear errors.

Limits default to a personal/development key: 20 requests per second and 100 per 2 minutes.
"""
import json
import time
import urllib.error
import urllib.request
from collections import deque

HINT = {401: "Riot doesn't recognise the key: it is mistyped, not exported in this terminal, or expired "
             "(development keys last 24 h; click 'Regenerate API Key').",
        403: "Forbidden: the key can't use this endpoint, or the request was blocked upstream.",
        404: "Not found: check the Riot ID, its tag, and the region."}


class RiotError(Exception):
    def __init__(self, code, path, body):
        super().__init__(f"Riot API {code} on {path.split('?')[0]}\nRiot said: {body[:200]}\n{HINT.get(code, '')}")
        self.code = code


TRIES = 10                # 1+2+4+...+32+60+60+60+60 s of backoff: about 5 minutes


class RateLimiter:
    def __init__(self, limits=((20, 1.0), (100, 120.0)), clock=time.monotonic, sleep=time.sleep):
        self.limits, self.clock, self.sleep = limits, clock, sleep
        self.sent = deque()

    def wait(self):
        """Block until one more request fits every (count, seconds) window."""
        longest = max(w for _, w in self.limits)
        while True:
            now = self.clock()
            while self.sent and now - self.sent[0] >= longest:
                self.sent.popleft()
            delay = 0.0
            for n, w in self.limits:
                recent = [t for t in self.sent if now - t < w]
                if len(recent) >= n:
                    delay = max(delay, recent[-n] + w - now)
            if delay <= 0:
                self.sent.append(now)
                return
            self.sleep(delay)


class Riot:
    def __init__(self, key, limiter=None):
        self.key, self.limiter = key, limiter or RateLimiter()

    def get(self, host, path):
        """GET https://{host}.api.riotgames.com{path} -> parsed JSON. Retries 429/5xx; raises RiotError."""
        url = f"https://{host}.api.riotgames.com{path}"
        for attempt in range(TRIES):
            self.limiter.wait()
            req = urllib.request.Request(url, headers={"X-Riot-Token": self.key, "User-Agent": "tftsolver/0.1"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    # a key limit says how long (Retry-After); Riot's own overload ("service" limit) often
                    # doesn't and can last minutes: back off up to a minute a try, ~5 minutes in all
                    time.sleep(int(e.headers.get("Retry-After", min(2 ** attempt, 60))))
                    continue
                raise RiotError(e.code, path, e.read().decode(errors="replace")) from None
            except urllib.error.URLError:
                time.sleep(min(2 ** attempt, 60))
        raise RiotError(429, path, f"still rate limited or unreachable after {TRIES} tries (~5 min); run again "
                                   "later: the crawl resumes where it stopped")
