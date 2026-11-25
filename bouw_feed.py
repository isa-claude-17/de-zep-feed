"""
Tussenserver voor het sportscherm.

Leest bronnen.yaml, haalt elke bron op en schrijft één klein bestand:
site/feed.json. Dat bestand leest het schermpje elke paar minuten.

Een nieuw SOORT bron (bijv. een API voor Ajax-uitslagen) toevoegen:
  1. schrijf hieronder een functie  def mijn_soort(bron, inst): ...
     die een "kaart" teruggeeft (een dict met minstens "type")
  2. zet hem in OPHALERS onderaan
  3. gebruik  type: mijn_soort  in bronnen.yaml
Een extra RSS-feed toevoegen hoeft alleen in bronnen.yaml.
"""

import csv
import datetime as dt
import io
import json
import sys
import time
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

MAP = Path(__file__).parent
UIT = MAP / "site" / "feed.json"
USER_AGENT = "de-zep-feed/1.0 (prive sportscherm)"


# ── hulpjes ──────────────────────────────────────────────────

def haal_op(adres: str) -> bytes:
    """Haalt een url op. Werkt ook met file:// (handig om te testen)."""
    if "://" not in adres:                       # gewoon een bestandsnaam
        return (MAP / adres).read_bytes()
    req = urllib.request.Request(adres, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def kort_in(tekst: str, max_tekens: int) -> str:
    tekst = " ".join(tekst.split())              # rare witruimte weg
    if len(tekst) <= max_tekens:
        return tekst
    return tekst[: max_tekens - 1].rsplit(" ", 1)[0] + "…"


# ── ophalers: één functie per soort bron ─────────────────────

def rss(bron, inst):
    root = ET.fromstring(haal_op(bron["url"]))
    grens = time.time() - inst["max_leeftijd_dagen"] * 86400
    items = []
    for item in root.iter("item"):
        titel = (item.findtext("title") or "").strip()
        datum = item.findtext("pubDate")
        if not titel:
            continue
        ts = int(parsedate_to_datetime(datum).timestamp()) if datum else 0
        if ts and ts < grens:
            continue
        items.append({"t": kort_in(titel, inst["max_tekens_kop"]), "ts": ts})
    items.sort(key=lambda i: i["ts"], reverse=True)
    return {
        "type": "nieuws",
        "id": bron["id"],
        "naam": bron["naam"],
        "kleur": bron.get("kleur", "#FFFFFF"),
        "items": items[: inst["max_koppen_per_bron"]],
    }


def uitspraken(bron, inst):
    adres = bron.get("url") or bron["bestand"]
    tekst = haal_op(adres).decode("utf-8-sig")
    rijen = [r for r in csv.DictReader(io.StringIO(tekst)) if r.get("tekst")]
    if not rijen:
        raise ValueError("geen uitspraken gevonden")
    # elke dag een andere, maar wel de hele dag dezelfde
    dagnummer = dt.date.today().toordinal()
    r = rijen[dagnummer % len(rijen)]
    return {
        "type": "uitspraak",
        "id": bron["id"],
        "naam": bron["naam"],
        "tekst": r["tekst"].strip(),
        "wie": r.get("wie", "").strip(),
        "foto": r.get("foto", "").strip(),
    }


OPHALERS = {
    "rss": rss,
    "uitspraken": uitspraken,
}


# ── hoofdprogramma ───────────────────────────────────────────

def main(config_pad="bronnen.yaml"):
    config = yaml.safe_load((MAP / config_pad).read_text(encoding="utf-8"))
    inst = config["instellingen"]

    # vorige versie bewaren: als een bron even plat ligt, tonen we de oude kaart
    oud = {}
    if UIT.exists():
        try:
            oud = {k["id"]: k for k in json.loads(UIT.read_text())["kaarten"]}
        except Exception:
            pass

    kaarten, fouten = [], 0
    for bron in config["bronnen"]:
        if not bron.get("aan", True):
            continue
        ophaler = OPHALERS.get(bron["type"])
        if not ophaler:
            print(f"!! onbekend type '{bron['type']}' bij {bron['id']}")
            continue
        try:
            kaart = ophaler(bron, inst)
            print(f"ok  {bron['id']}")
        except Exception as e:
            fouten += 1
            print(f"!!  {bron['id']} mislukt: {e}")
            kaart = oud.get(bron["id"])
        if kaart:
            kaarten.append(kaart)

    feed = {"v": 1, "bijgewerkt": int(time.time()), "kaarten": kaarten}
    UIT.parent.mkdir(exist_ok=True)
    data = json.dumps(feed, ensure_ascii=False, separators=(",", ":"))
    UIT.write_text(data, encoding="utf-8")
    print(f"feed.json geschreven: {len(kaarten)} kaarten, {len(data.encode())} bytes")
    return fouten


if __name__ == "__main__":
    main(*sys.argv[1:])
