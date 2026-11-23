#!/usr/bin/env python3
"""Set 19 launch-day pipeline: crawl ranked games, train the board model, learn trait values, refresh plans.

    export RIOT_API_KEY=RGAPI-...
    python3 -I tools/launch_day.py                       # na1, 2000 matches since 2026-12-02
    python3 -I tools/launch_day.py --skip-crawl          # retrain on what's already stored

Why 2000: on Set 18 the board model was still gaining ~0.8 points per 100 lobbies at 400 (83.0%), and
Set 19 has 94 units, some rare. Re-running adds matches without refetching (the crawl resumes).
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def step(title, *args):
    print(f"\n== {title}")
    r = subprocess.run([sys.executable, "-I", *map(str, args)], cwd=ROOT)
    if r.returncode:
        sys.exit(f"stopped at: {title}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="na1")
    ap.add_argument("--matches", type=int, default=2000)
    ap.add_argument("--since", default="2026-12-02")
    ap.add_argument("--skip-crawl", action="store_true")
    a = ap.parse_args()
    if not a.skip_crawl:
        step("crawl Set 19 ranked matches", "tools/crawl.py", "--platform", a.platform, "--set", "19",
             "--since", a.since, "--max-matches", a.matches)
    step("train the board model (unit-stars, trait tiers, items/BIS), starting from what Set 18 taught",
         "engine/board_model.py", "fit", "19", "--prior", "18")
    step("learn per-trait values from our own games", "engine/strength.py", "traits", "19")
    step("refresh synergy plans with those values", "engine/strength.py", "search", "TFTSet19", "8", "--save")
    step("what the model learned", "engine/board_model.py", "show", "19")
    print("\nStill manual: check data/constants.json TFTSet19 (copied from Set 18) against the 19.1 patch notes,\n"
          "and look for 'unit ids not on the roster' above (a naming gap would drop units from training).")


if __name__ == "__main__":
    main()
