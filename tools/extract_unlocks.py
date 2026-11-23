#!/usr/bin/env python3
"""Extract TFT unlockable-champion conditions from CommunityDragon game data.

    python3 -I tools/extract_unlocks.py                      # list set modes that have unlock data
    python3 -I tools/extract_unlocks.py --refresh            # same, after re-downloading PBE data
    python3 -I tools/extract_unlocks.py --set TFTSet16       # write data/pbe/TFTSet16.unlocks.json
    python3 -I tools/extract_unlocks.py --patch latest --set TFTSet16

Raw files are downloaded once into data/raw/<patch>/ (~120 MB) and reused.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "map22.bin.json": "game/data/maps/shipping/map22/map22.bin.json",
    "tft.stringtable.json": "game/en_us/data/menu/en_us/tft.stringtable.json",
    "en_us.json": "cdragon/tft/en_us.json",
}

# Field names CommunityDragon has not un-hashed. Meanings inferred from the values; verify in game.
UNLOCK_LIST = "{789ea797}"
CONDITIONS = "{d219bca8}"
MIN_LEVEL = "{86c68b6d}"    # player level gate; matches all 17 gates in Riot's 16.6 patch notes
COND_ID = "{9c2c3852}"
MILESTONES = "{9631656f}"   # tracker checkpoints; values above `required` = threshold escalates (Set 16 Azir)
FILTER = "{cfa2b9d6}"
KINDS = {                   # condition __type -> (kind, field holding the threshold)
    "{f9983033}": ("counter", "RequiredValue"),
    "{29124137}": ("trait_star_levels", "{2bbbc039}"),
    "{a630a690}": ("trait_unique_units", "{241519e9}"),
    "{bb04e22d}": ("unit_star_level", "RequiredLevel"),
}
KNOWN = {UNLOCK_LIST, CONDITIONS, MIN_LEVEL, "CharacterRecord", "__type"}
SET_PREFIX = "Maps/Shipping/Map22/Sets/"


def fetch(patch, refresh=False):
    raw = ROOT / "data" / "raw" / patch
    raw.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        if refresh or not (raw / name).exists():
            print(f"downloading {name} ...", file=sys.stderr)
            req = urllib.request.Request(f"https://raw.communitydragon.org/{patch}/{path}",
                                         headers={"User-Agent": "tftsolver/0.1"})  # Cloudflare 403s urllib's default
            tmp = raw / (name + ".part")
            with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            tmp.replace(raw / name)
    return raw


def load(raw):
    return (json.loads((raw / "map22.bin.json").read_text()),
            json.loads((raw / "tft.stringtable.json").read_text())["entries"],
            json.loads((raw / "en_us.json").read_text()))


def unlock_container(bins, set_name):
    """The unlock list a set mode points at, or None if the mode has no unlocks."""
    setobj = bins.get(SET_PREFIX + set_name)
    if setobj is None:
        return None
    for h in re.findall(r"\{[0-9a-f]{8}\}", json.dumps(setobj)):
        if UNLOCK_LIST in bins.get(h, {}):
            return bins[h][UNLOCK_LIST]
    return None


def sets_with_unlocks(bins):
    return sorted(k[len(SET_PREFIX):] for k in bins
                  if k.startswith(SET_PREFIX) and k.count("/") == 4
                  and unlock_container(bins, k[len(SET_PREFIX):]))


def tail(path):
    return path.rstrip("/").split("/")[-1] if "/" in path else path


def text(strings, key, required):
    s = strings.get((key or "").lower())
    if s is None:
        return None
    s = s.replace("@RequiredValue@", str(required)).replace("@Value@", "{value}")
    s = re.sub(r"%i:[^%]+%", "", s).replace("&nbsp;", "")
    return " ".join(re.sub(r"<[^>]+>", " ", s).split())


def condition(c, strings):
    kind, field = KINDS.get(c["__type"], (c["__type"], "RequiredValue"))
    req = c.get(field)
    out = {"kind": kind, "id": c.get(COND_ID), "required": req,
           "milestones": c.get(MILESTONES, []),
           "text": text(strings, c.get("DescriptionTra"), req),
           "progress_text": text(strings, c.get("MilestoneDescriptionTra"), req)}
    out["escalates"] = any(m > req for m in out["milestones"]) if req is not None else False
    if "traits" in c:
        out["traits"] = [tail(t["Trait"]) for t in c["traits"]]
    if "Trait" in c:
        out["traits"] = [tail(c["Trait"])]
    if "CharacterRecord" in c:
        out["unit"] = c["CharacterRecord"].split("/")[1]
    f = c.get(FILTER)
    if f:
        if "Item" in f:
            out["item"] = tail(f["Item"])
        elif "CharacterRecord" in f:
            out["unit"] = f["CharacterRecord"].split("/")[1]
            if "StarLevel" in f:
                out["unit_stars"] = f["StarLevel"]
        else:
            out["filter_hash"] = f.get("{d39d85bd}", f["__type"])  # e.g. "Caster or Marksman"; see text
    return out


def extract(bins, strings, cdragon, set_name):
    container = unlock_container(bins, set_name)
    if container is None:
        raise SystemExit(f"{set_name}: no unlock data. Sets with unlocks: {sets_with_unlocks(bins)}")
    champs = {c["apiName"]: c for s in cdragon["setData"] if s["mutator"] == set_name
              for c in s["champions"]}
    out = []
    for u in container.values():
        api = u["CharacterRecord"].split("/")[1]
        ch = champs.get(api, {})
        out.append({"unit": ch.get("name", api), "api": api, "cost": ch.get("cost"),
                    "traits": ch.get("traits", []), "min_level": u.get(MIN_LEVEL),
                    "conditions": [condition(c, strings) for c in u[CONDITIONS]],
                    "unknown_fields": {k: v for k, v in u.items() if k not in KNOWN}})
    return sorted(out, key=lambda x: (x["cost"] or 0, x["unit"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", default="pbe", help="CommunityDragon patch dir: pbe, latest, 16.22, ...")
    ap.add_argument("--set", help="set mode, e.g. TFTSet16; omit to list modes with unlock data")
    ap.add_argument("--refresh", action="store_true", help="re-download raw files (pbe/latest move)")
    a = ap.parse_args()
    bins, strings, cdragon = load(fetch(a.patch, a.refresh))
    if not a.set:
        print("\n".join(sets_with_unlocks(bins)))
        return
    unlocks = extract(bins, strings, cdragon, a.set)
    dest = ROOT / "data" / a.patch / f"{a.set}.unlocks.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(unlocks, indent=1, ensure_ascii=False))
    for u in unlocks:
        for c in u["conditions"]:
            print(f"{u['cost'] or '?':>2} {u['unit']:<16} L{u['min_level'] or '-':<3} "
                  f"{c['kind']:<19} {'ESC ' if c['escalates'] else ''}{c['text']}")
    bad = [u["api"] for u in unlocks for c in u["conditions"]
           if c["required"] is None or not c["text"] or "@" in c["text"]]
    print(f"\n{len(unlocks)} unlocks -> {dest.relative_to(ROOT)}"
          + (f"\nUNRESOLVED: {bad}" if bad else ""))


if __name__ == "__main__":
    main()
