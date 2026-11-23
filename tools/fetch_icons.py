"""Icons for the team builder: champions, traits, items and augments. Set 19 isn't in CommunityDragon or Riot's
Data Dragon yet (checked 2026-11-23: no tft19 assets), so:
  champions  Set 19 portraits (the Set 19 skins) from MetaTFT's CDN, which hosts Riot's Set 19 art (downloaded with
             the user's OK, 2026-11-23; private, gitignored); else the champion's art from the latest TFT set in
             CommunityDragon, or its League portrait.
  traits     Set 19 trait icons from MetaTFT's CDN (Riot's internal names differ for some: Slayer is "mosher").
  items      CommunityDragon icons (the item-classifier cache first); Set 19 trait emblems from our own VOD
             crops (data/raw/labels/items, read from item tooltips).
  augments   CommunityDragon icons matched by name (augments that carried over); new Set 19 augments have none.
Anything without art gets a drawn tile in the page. Saved under data/assets/icons/ (gitignored: Riot's art)
with index.json {kind: {name: file}}. Rerun after CommunityDragon adds Set 19: it refetches nothing it has.

    python3 -I tools/fetch_icons.py
"""
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
OUT = ROOT / "data" / "assets" / "icons"
GAME = "https://raw.communitydragon.org/pbe/game/"
LOL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/"
UA = {"User-Agent": "tftsolver/0.1"}                   # CommunityDragon 403s Python's default agent
ALIAS = {"Akali (K/DA)": "Akali", "Akali (True Damage)": "Akali"}
SET19 = "https://cdn.metatft.com/file/metatft/"        # MetaTFT's CDN: Riot's Set 19 art (da_<name>19.png)
UNIT19 = {"Akali (K/DA)": "akalikda", "Akali (True Damage)": "akali_truedamage", "Seraphine": "seraphinesuperstar",
          "Nunu & Willump": "nunu"}                     # file keys that aren't the name without punctuation
TRAIT19 = {"Slayer": "mosher19", "Gu Feng": "heavenscale19", "Rock": "demonvision19", "R&B": "rnb19", "Beach Pop": "oceansong19",
           "Hyperpop": "glitterbomb19", "Classical": "virtuosos19", "Disco": "nunu19_uniquetrait",
           "Freestyle": "akali_truedamage19_uniquetrait", "Indie": "seraphine19_indietrait"}   # Riot's internal names


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def get(url, pause=0.05):
    time.sleep(pause)                                   # a reading pace, not a flood
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()


def png(path):
    return GAME + path.lower().replace(".tex", ".png")


def save(kind, name, data_or_path, index):
    d = OUT / kind
    d.mkdir(parents=True, exist_ok=True)
    f = d / (slug(name) + ".png")
    if isinstance(data_or_path, Path):
        shutil.copyfile(data_or_path, f)
    else:
        f.write_bytes(data_or_path)
    index.setdefault(kind, {})[name] = f"{kind}/{f.name}"


def main():
    from linefinder import catalog
    from unlocks import load_set
    static = load_set("TFTSet19")
    cat = catalog(static)
    cd = json.loads((ROOT / "data/raw/cdragon/tft_pbe.json").read_text())
    idx_file = OUT / "index.json"
    index = json.loads(idx_file.read_text()) if idx_file.exists() else {}
    have = lambda kind, n: n in index.get(kind, {}) and (OUT / index[kind][n]).exists()   # noqa: E731
    missing = {"units": [], "items": [], "augments": []}

    # Set 19 art first: portraits and trait icons from MetaTFT's CDN; they replace older sets' art
    got = index.setdefault("_set19", {"units": [], "traits": []})
    missing["traits"] = []
    key = lambda n: re.sub(r"[^a-z0-9]", "", n.lower())                                       # noqa: E731
    for u in static["units"]:
        n = u["name"]
        if n in got["units"] and have("units", n):
            continue
        try:
            save("units", n, get(SET19 + f"champions/da_{UNIT19.get(n) or key(n)}19.png", 0.3), index)
            got["units"].append(n)
        except OSError:
            pass                                                     # falls back to an older set's art below
    for t in static["traits"]:
        n = t["name"]
        if have("traits", n):
            continue
        members = [u["name"] for u in static["units"] if n in u["traits"]]
        names = [TRAIT19[n]] if n in TRAIT19 else ([f"{key(members[0])}19_uniquetrait"] if len(members) == 1 else []) + [f"{key(n)}19"]
        for f in names:
            try:
                save("traits", n, get(SET19 + f"traits/da_{f}.png", 0.3), index)
                got["traits"].append(n)
                break
            except OSError:
                pass
        else:
            missing["traits"].append(n)

    # champions: the latest set's art per name (the splash tile; the HUD square if there's no tile)
    art = {}
    for s in cd["setData"]:
        for c in s.get("champions", []):
            pics = [x for x in (c.get("squareIcon"), c.get("tileIcon")) if x]
            if c.get("name") and pics and s.get("number", 0) >= art.get(c["name"], (0, []))[0]:
                art[c["name"]] = (s.get("number", 0), pics)
    lol = {c["name"]: c for c in json.loads(get(LOL + "champion-summary.json")) if c["id"] < 10000}
    for u in cat["units"]:
        n = u["name"]
        if have("units", n):
            continue
        key = ALIAS.get(n, n)
        try:
            data = None
            for pic in art.get(key, (0, []))[1]:              # the splash tile, else the HUD square
                try:
                    data = get(png(pic))
                    break
                except OSError:
                    pass
            if data:
                save("units", n, data, index)
            elif key in lol:
                save("units", n, get(LOL + f"champion-icons/{lol[key]['id']}.png"), index)
            else:
                missing["units"].append(n)
        except OSError as e:
            missing["units"].append(f"{n} ({e})")

    # items: the classifier's cached icons by name, then CommunityDragon, then our emblem crops
    cache = ROOT / "data/raw/cdragon/items"
    cached = {e["name"]: cache / e["file"] for e in json.loads((cache / "index.json").read_text())} if (cache / "index.json").exists() else {}
    by_name = {}
    for it in cd["items"]:
        if it.get("name") and it.get("icon") and not it.get("isAugment"):
            by_name.setdefault(it["name"], it["icon"])
    crops = ROOT / "data/raw/labels/items"
    for kind in ("components", "completed", "artifacts", "radiants", "emblems"):
        for n in cat[kind]:
            if have("items", n):
                continue
            try:
                if n in cached and cached[n].exists():
                    save("items", n, cached[n], index)
                elif n in by_name:
                    save("items", n, get(png(by_name[n])), index)
                elif (crops / n).is_dir() and any((crops / n).glob("*.png")):
                    save("items", n, sorted((crops / n).glob("*.png"))[0], index)
                else:
                    missing["items"].append(n)
            except OSError as e:
                missing["items"].append(f"{n} ({e})")

    # augments: by name, the latest set's entry
    aug = {}
    for it in cd["items"]:
        if it.get("name") and it.get("icon") and ("augments" in it["icon"].lower() or it.get("isAugment")):
            aug[it["name"]] = it["icon"]                    # later entries are newer sets
    for a in cat["augments"]:
        n = a["name"]
        if have("augments", n):
            continue
        try:
            if n in aug:
                save("augments", n, get(png(aug[n])), index)
            else:
                missing["augments"].append(n)
        except OSError as e:
            missing["augments"].append(f"{n} ({e})")

    if shutil.which("sips"):                            # 512 px splash tiles -> 160 px: the page loads 94 of them
        for n, f in index.get("units", {}).items():     # (Set 19 portraits are 128 px already: never upscale)
            if n not in got["units"]:
                subprocess.run(["sips", "-Z", "160", str(OUT / f)], capture_output=True)
    index["_missing"] = missing
    idx_file.write_text(json.dumps(index, indent=1, ensure_ascii=False))
    print(f"Set 19 art: {len(got['units'])} portraits, {len(got['traits'])} trait icons")
    for k in ("units", "traits", "items", "augments"):
        print(f"{k}: {len(index.get(k, {}))} icons, {len(missing[k])} without art"
              + (f" ({', '.join(missing[k][:8])}{'...' if len(missing[k]) > 8 else ''})" if missing[k] else ""))


if __name__ == "__main__":
    main()
