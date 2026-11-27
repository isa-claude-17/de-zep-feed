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
import hashlib
import html
import io
import json
import re
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
    max_tekens = bron.get("max_tekens_kop", inst["max_tekens_kop"])
    weg = {c.strip().lower() for c in bron.get("zonder_categorie", [])}
    items, overgeslagen = [], 0
    for item in root.iter("item"):
        titel = (item.findtext("title") or "").strip()
        datum = item.findtext("pubDate")
        if not titel:
            continue
        if weg and {(c.text or "").strip().lower() for c in item.findall("category")} & weg:
            overgeslagen += 1
            continue
        ts = int(parsedate_to_datetime(datum).timestamp()) if datum else 0
        if ts and ts < grens:
            continue
        items.append({"t": kort_in(titel, max_tekens), "ts": ts})
    if overgeslagen:
        print(f"    {overgeslagen} bericht(en) overgeslagen op categorie")
    items.sort(key=lambda i: i["ts"], reverse=True)
    koppen = bron.get("koppen", inst.get("koppen", inst["max_koppen_per_bron"]))
    kaart = {
        "type": "nieuws",
        "id": bron["id"],
        "naam": bron["naam"],
        "kleur": bron.get("kleur", "#FFFFFF"),
        "items": items[: int(koppen)],
        "koppen": int(koppen),
    }
    regels = bron.get("regels", inst.get("regels"))
    if regels:
        kaart["regels"] = int(regels)
    return kaart


# ── "Op deze dag" (onthisday.com): gebeurd, geboren, overleden ──

# Woorden die op Europa wijzen. Een regel met zo'n woord komt eerder op het scherm.
EUROPA = re.compile(
    r"\b(?:british|britain|english|england|welsh|wales|scotland|scottish|irish|ireland|"
    r"dutch|netherlands|belgi|flemish|flanders|german|france|french|ital|spain|spanish|"
    r"swiss|switzerland|austria|swed|danish|denmark|norw|finnish|finland|polish|poland|"
    r"hungar|czech|slovak|ukrain|russia|soviet|portug|greek|greece|europe|london|paris|"
    r"berlin|rome|vienna|brussels|madrid|bavaria|prussia|holy roman)",
    re.I,
)
# Nederland en België tellen extra mee
THUIS = re.compile(
    r"\b(?:dutch|netherlands|belgi|flemish|flanders|amsterdam|rotterdam|the hague|utrecht|antwerp|brussels)",
    re.I,
)
REGEL = re.compile(
    r"<b>\s*<a[^>]*>\s*([^<]+?)\s*</a>\s*</b>\s*[-–]\s*(.*?)(?=<br\s*/?>|</p>|<b>|$)",
    re.S | re.I,
)


def europa_score(tekst):
    return (1 if EUROPA.search(tekst) else 0) + (2 if THUIS.search(tekst) else 0)


def lees_regels(beschrijving):
    """Haalt (jaar, tekst) uit de HTML van een bericht."""
    uit = []
    for jaar, tekst in REGEL.findall(beschrijving):
        tekst = " ".join(html.unescape(re.sub(r"<[^>]+>", "", tekst)).split())
        if tekst:
            uit.append((jaar.strip(), tekst))
    return uit


def schoon(soort, tekst):
    """Korter maken: bij geboortes weg met geboorteplaats en sterfjaar."""
    if soort == "geboren":
        tekst = re.sub(r"\s*\(d\.\s*\d{3,4}\)\s*$", "", tekst)
        tekst = re.sub(r",?\s*born (?:in|on|at) .*$", "", tekst, flags=re.I)
    return tekst.strip(" ,")


def handtekening(bron, inst):
    """Korte code van de instellingen. Verandert die, dan bouwen we de kaart opnieuw."""
    delen = [bron.get(k) for k in ("naam", "soort", "koppen", "regels", "europa")]
    delen.append(bron.get("max_tekens_kop", inst["max_tekens_kop"]))
    return hashlib.md5(json.dumps(delen).encode()).hexdigest()[:6]


def spreid(lijst, n):
    """Kiest n regels gelijkmatig verdeeld over de lijst (de site sorteert op jaartal)."""
    if len(lijst) <= n:
        return list(lijst)
    return [lijst[round(i * (len(lijst) - 1) / (n - 1))] for i in range(n)] if n > 1 else lijst[:1]


def moet_ophalen(vorige, sig=None, nu=None):
    """De site maakt elke dag rond 05:05 UTC een nieuw bericht. Vaker ophalen is zinloos."""
    nu = nu or dt.datetime.now(dt.timezone.utc)
    if not vorige or not vorige.get("ts"):
        return True
    if sig is not None and vorige.get("sig") != sig:
        return True                           # instellingen veranderd
    gemaakt = dt.datetime.fromtimestamp(vorige["ts"], dt.timezone.utc)
    if gemaakt.date() == nu.date():
        return False                          # kaart van vandaag staat er al
    return (nu.hour, nu.minute) >= (5, 15)    # eerder is er nog niets nieuws


def opdezedag(bron, inst):
    vorige = inst.get("_oud", {}).get(bron["id"])
    sig = handtekening(bron, inst)
    if not moet_ophalen(vorige, sig):
        print("    kaart van vandaag staat er al, niet opnieuw opgehaald")
        return vorige
    root = ET.fromstring(haal_op(bron["url"]))
    item = root.find(".//item")
    if item is None:
        raise ValueError("geen bericht in de feed")
    datum = item.findtext("pubDate")
    ts = int(parsedate_to_datetime(datum).timestamp()) if datum else int(time.time())
    regels = lees_regels(item.findtext("description") or "")
    if not regels:
        raise ValueError("geen regels gevonden in het bericht")
    soort = bron.get("soort", "")
    n = bron.get("koppen", 5)
    # standaard gelijkmatig verspreid over de dag-lijst; met  europa: true  komen eerst de
    # Europese regels (bij gelijke score blijft de volgorde van de site). Altijd op jaartal getoond.
    keuze = list(enumerate(regels))
    if bron.get("europa", False):
        keuze.sort(key=lambda x: (-europa_score(x[1][1]), x[0]))
        keuze = keuze[:n]
    else:
        keuze = spreid(keuze, n)
    keuze = sorted(keuze, key=lambda x: x[0])
    max_tekens = bron.get("max_tekens_kop", inst["max_tekens_kop"])
    kaart = {
        "type": "lijst",
        "id": bron["id"],
        "naam": bron["naam"],
        "ts": ts,
        "sig": sig,
        "items": [{"j": j, "t": kort_in(schoon(soort, t), max_tekens)} for _, (j, t) in keuze],
    }
    for veld in ("koppen", "regels"):
        if veld in bron:
            kaart[veld] = int(bron[veld])
    return kaart


def lees_uitspraken(adres):
    tekst = haal_op(adres).decode("utf-8-sig")
    rijen = [r for r in csv.DictReader(io.StringIO(tekst)) if (r.get("tekst") or "").strip()]
    if not rijen:
        raise ValueError(f"geen uitspraken gevonden in {adres[:60]}")
    return rijen


def uitspraken(bron, inst):
    # eerst de Google Sheet; lukt dat niet, dan het reservebestand in de repo
    rijen = None
    if bron.get("url"):
        try:
            rijen = lees_uitspraken(bron["url"])
            print(f"    {len(rijen)} uitspraken uit de Google Sheet")
        except Exception as e:
            print(f"    Google Sheet niet bereikbaar ({e}), reservebestand gebruikt")
    if rijen is None:
        rijen = lees_uitspraken(bron["bestand"])
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


def bouw_weer(data, bron):
    """Maakt van het antwoord van Open-Meteo een kleine weerkaart."""
    nu, dag = data["current"], data["daily"]
    dagen = []
    for i in range(1, 4):                     # morgen, overmorgen en de dag daarna
        d = dt.date.fromisoformat(dag["time"][i])
        dagen.append({
            "d": (d.weekday() + 1) % 7,       # 0 = zondag, zoals JavaScript
            "c": int(dag["weather_code"][i]),
            "max": round(dag["temperature_2m_max"][i]),
            "min": round(dag["temperature_2m_min"][i]),
        })
    return {
        "type": "weer",
        "id": bron["id"],
        "naam": bron["naam"],
        "plaats": bron["plaats"],
        "nu": {
            "t": round(nu["temperature_2m"]),
            "voelt": round(nu["apparent_temperature"]),
            "c": int(nu["weather_code"]),
            "wind": round(nu["wind_speed_10m"]),
            "kans": int(dag["precipitation_probability_max"][0] or 0),
            "max": round(dag["temperature_2m_max"][0]),
            "min": round(dag["temperature_2m_min"][0]),
        },
        "dagen": dagen,
    }


def weer(bron, inst):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={bron['lat']}&longitude={bron['lon']}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=Europe%2FAmsterdam&forecast_days=4&wind_speed_unit=kmh"
    )
    return bouw_weer(json.loads(haal_op(url)), bron)


OPHALERS = {
    "rss": rss,
    "uitspraken": uitspraken,
    "weer": weer,
    "opdezedag": opdezedag,
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

    inst["_oud"] = oud      # sommige bronnen (opdezedag) hergebruiken de vorige kaart

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
