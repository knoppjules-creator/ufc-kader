#!/usr/bin/env python3
"""
Sammelt alle aktiven UFC-Kämpfer und schreibt sie nach data/fighters.json.

Quellen (offizielle Wikimedia-Schnittstellen):
  1. "List of current UFC fighters"  -> Kader, Gewichtsklasse, Land, Geburtsdatum,
                                         Größe, Bilanz, letzter/nächster Kampf
  2. Artikel der einzelnen Kämpfer    -> Infobox: Geburtsdatum, Geburtsort, Größe,
                                         Gewicht, Reichweite, Kampfstil, Nationalität, Bilanz
  3. "List of UFC events"              -> Datum der angesetzten Events
  4. Wikipedia auf Russisch, Japanisch, Spanisch, Portugiesisch, Deutsch
                                      -> Reichweite, Gewicht, Kampfstil, Geburtsort
  5. Wikidata                         -> Gewicht, Geburtsort (für Kämpfer ohne engl. Artikel)
  Wikipedia: CC BY-SA 4.0 (Quellenangabe nötig), Wikidata: CC0.

Nicht verwendet (geprüft am 21.10.2026):
  - ufc.com: Nutzungsbedingungen verbieten "page-scrape", "robot", "spider".
  - ufcstats.com: blockiert automatische Abfragen mit einer Browser-Prüfung.
  - ESPN: Nutzungsbedingungen (Disney) verbieten Roboter und Web-Scraping.
  - Tapology: sperrt bereits den Abruf der Nutzungsbedingungen für Programme.
  - Sherdog: Nutzungsbedingungen verbieten Kopieren und Veröffentlichen der Inhalte.

Grundregel (siehe CLAUDE.md): Niemals raten. Fehlt ein Wert -> null.
Widersprechen sich zwei Quellen -> beide Werte unter "konflikte".

Aufruf:  python3 scraper/sammle_kaempfer.py
Nur Python-Standardbibliothek, keine Zusatzpakete nötig.
"""

import hashlib
import os
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent
CACHE = PROJEKT / "scraper" / "cache"
AUSGABE = PROJEKT / "data" / "fighters.json"

API = "https://en.wikipedia.org/w/api.php"
WIKI = "https://en.wikipedia.org/wiki/"
# Wikipedia verlangt einen eindeutigen User-Agent mit Kontaktmöglichkeit.
# Auf GitHub wird automatisch die Adresse des Repositorys als Kontakt angehängt.
_REPO = os.environ.get("GITHUB_REPOSITORY")
USER_AGENT = ("UFC-Kader-Fanprojekt/1.0 (privates, nicht-kommerzielles Projekt; "
              + (f"https://github.com/{_REPO}" if _REPO else "Python-urllib") + ")")
PAUSE_SEKUNDEN = 3        # Pause zwischen zwei Anfragen
CACHE_STUNDEN = 20        # so lange gilt eine bereits geladene Antwort
TITEL_PRO_ANFRAGE = 50    # Maximum der Wikipedia-API

LISTE = "List of current UFC fighters"
EVENTS = "List of UFC events"
RANGLISTEN = "UFC rankings"

# Abschnittsüberschrift in der Liste -> englischer Name der Gewichtsklasse
KLASSEN = [
    ("women's bantamweight", "Women's Bantamweight"),
    ("women's flyweight", "Women's Flyweight"),
    ("women's strawweight", "Women's Strawweight"),
    ("women's featherweight", "Women's Featherweight"),
    ("light heavyweight", "Light Heavyweight"),
    ("heavyweight", "Heavyweight"),
    ("middleweight", "Middleweight"),
    ("welterweight", "Welterweight"),
    ("lightweight", "Lightweight"),
    ("featherweight", "Featherweight"),
    ("bantamweight", "Bantamweight"),
    ("flyweight", "Flyweight"),
]

MONATE = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ---------------------------------------------------------------- Abruf

_letzte_anfrage = 0.0


def hole(params, api=API):
    """Fragt eine Wikipedia-API ab (mit Cache, Pause und Wiederholung bei Fehlern)."""
    global _letzte_anfrage
    params = dict(params, format="json", formatversion="2", maxlag="5")
    url = api + "?" + urllib.parse.urlencode(params)
    CACHE.mkdir(parents=True, exist_ok=True)
    datei = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if datei.exists() and time.time() - datei.stat().st_mtime < CACHE_STUNDEN * 3600:
        return json.loads(datei.read_text(encoding="utf-8"))

    for versuch in range(5):
        warten = PAUSE_SEKUNDEN - (time.time() - _letzte_anfrage)
        if warten > 0:
            time.sleep(warten)
        _letzte_anfrage = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                daten = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(int(e.headers.get("Retry-After", 0) or 0) or 10 * (versuch + 1))
                continue
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            time.sleep(10 * (versuch + 1))
            continue
        if daten.get("error", {}).get("code") == "maxlag":
            time.sleep(10 * (versuch + 1))
            continue
        datei.write_text(json.dumps(daten), encoding="utf-8")
        return daten
    raise RuntimeError("Wikipedia nicht erreichbar: " + url)


def hole_quelltexte(titel, api=API):
    """Liefert {angefragter Titel: (tatsächlicher Titel, Wikitext oder None)}."""
    ergebnis = {}
    titel = list(dict.fromkeys(titel))
    for i in range(0, len(titel), TITEL_PRO_ANFRAGE):
        teil = titel[i:i + TITEL_PRO_ANFRAGE]
        print(f"  Artikel {i + 1}–{i + len(teil)} von {len(titel)} …", flush=True)
        d = hole({"action": "query", "prop": "revisions", "rvprop": "content",
                  "rvslots": "main", "redirects": "1", "titles": "|".join(teil)}, api)
        q = d.get("query", {})
        umleitung = {}
        for art in ("normalized", "redirects"):
            for x in q.get(art, []):
                umleitung[x["from"]] = x["to"]
        seiten = {}
        for p in q.get("pages", []):
            text = None
            if not p.get("missing") and p.get("revisions"):
                text = p["revisions"][0]["slots"]["main"]["content"]
            seiten[p["title"]] = text
        for t in teil:
            ziel = t
            for _ in range(3):
                ziel = umleitung.get(ziel, ziel)
            ergebnis[t] = (ziel, seiten.get(ziel))
    return ergebnis


# ---------------------------------------------------------------- Wikitext lesen

def ohne_refs(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.I | re.S)
    return text


def links_aufloesen(text):
    text = re.sub(r"\[\[(?:File|Image|Datei):[^\[\]]*\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[([^\[\]|]*)\|([^\[\]]*)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\[\]|]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    return text


def link_ziele(text):
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\[\]|#]+)[^\[\]]*\]\]", text)]


def positionale(args):
    return [a.strip() for a in args if "=" not in a.split("|")[0]]


def benannte(args):
    d = {}
    for a in args:
        if "=" in a:
            k, v = a.split("=", 1)
            d[k.strip().lower()] = v.strip()
    return d


def datum_aus(pos):
    """['1988','9','29'] -> '1988-09-29' (nur wenn vollständig)."""
    zahlen = [p for p in pos if re.fullmatch(r"\d{1,4}", p)]
    if len(zahlen) >= 3:
        j, m, t = (int(x) for x in zahlen[:3])
        if 1900 < j < 2100 and 1 <= m <= 12 and 1 <= t <= 31:
            return f"{j:04d}-{m:02d}-{t:02d}"
    return None


def vorlage(name, args):
    """Wandelt eine einzelne Vorlage {{name|args}} in einfachen Text um."""
    n = name.strip().lower().replace("_", " ")
    pos, kw = positionale(args), benannte(args)
    if n in ("birth date and age", "birth date", "bda", "birth-date and age", "age nts",
             "birth date and age2", "dob"):
        return datum_aus(pos) or ""
    if n in ("convert", "cvt"):
        # {{convert|5|ft|6|in|m}} -> "5 ft 6 in";  {{convert|145|lb|kg}} -> "145 lb"
        teile, i = [], 0
        while i + 1 < len(pos) and re.fullmatch(r"[\d.+/]+", pos[i]):
            teile.append(pos[i] + " " + pos[i + 1])
            i += 2
        return " ".join(teile)
    if n == "height":
        if kw.get("ft") or kw.get("in"):
            return f"{kw.get('ft', '0')} ft {kw.get('in', '0')} in"
        if kw.get("m"):
            return f"{kw['m']} m"
        if kw.get("cm"):
            return f"{kw['cm']} cm"
        return ""
    if n in ("sortname",):
        return " ".join(p for p in pos[:2] if p)
    if n in ("color", "colour", "font color"):
        return pos[-1] if pos else ""
    if n in ("nowrap", "small", "nobr", "big", "nobold", "sup", "sub"):
        return pos[0] if pos else ""
    if n in ("ubl", "unbulleted list", "plainlist", "flatlist", "hlist", "plain list",
             "bulleted list", "ublist"):
        return ", ".join(p for p in pos if p)
    if n in ("dts", "date table sorting", "start date", "start date and age"):
        if len(pos) >= 3 and pos[1][:3].lower() in MONATE:
            return f"{int(pos[0]):04d}-{MONATE[pos[1][:3].lower()]:02d}-{int(pos[2]):02d}"
        return datum_aus(pos) or ""
    if n in ("tooltip", "abbr", "abbreviation"):
        return pos[0] if pos else ""
    if n in ("!",):
        return "|"
    if n in ("snd", "spaced ndash", "ndash", "spnd"):
        return " – "
    if n.startswith("flag") or n.startswith("#invoke:flag"):
        # {{flagicon|USA}} bzw. {{#invoke:flag|icon|USA}} -> nur der Code
        return "§FLAG:" + (pos[-1] if pos else "") + "§"
    return ""  # unbekannte Vorlage: lieber weglassen als raten


def vorlagen_aufloesen(text):
    """Löst Vorlagen von innen nach außen auf."""
    muster = re.compile(r"\{\{([^{}]*)\}\}")
    for _ in range(20):
        neu = muster.sub(lambda m: vorlage(m.group(1).split("|")[0],
                                           m.group(1).split("|")[1:]), text)
        if neu == text:
            break
        text = neu
    return text


def klartext(text):
    text = links_aufloesen(ohne_refs(text))
    text = vorlagen_aufloesen(text)
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = text.replace("&nbsp;", " ").replace("&ndash;", "–")
    text = re.sub(r"§FLAG:[^§]*§", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    return text


def finde_vorlage(text, start_muster):
    """Findet den vollständigen Block {{Infobox …}} mit Klammerzählung."""
    m = re.search(r"\{\{\s*" + start_muster, text, flags=re.I)
    if not m:
        return None
    tiefe, i = 0, m.start()
    while i < len(text) - 1:
        if text[i:i + 2] == "{{":
            tiefe += 1
            i += 2
        elif text[i:i + 2] == "}}":
            tiefe -= 1
            i += 2
            if tiefe == 0:
                return text[m.start() + 2:i - 2]
        else:
            i += 1
    return None


def oberste_teile(text):
    """Teilt an '|', aber nur außerhalb von {{ }} und [[ ]]."""
    teile, tiefe, aktuell, i = [], 0, [], 0
    while i < len(text):
        zwei = text[i:i + 2]
        if zwei in ("{{", "[["):
            tiefe += 1
            aktuell.append(zwei)
            i += 2
            continue
        if zwei in ("}}", "]]"):
            tiefe -= 1
            aktuell.append(zwei)
            i += 2
            continue
        if text[i] == "|" and tiefe == 0:
            teile.append("".join(aktuell))
            aktuell = []
        else:
            aktuell.append(text[i])
        i += 1
    teile.append("".join(aktuell))
    return teile


def infobox(wikitext):
    block = finde_vorlage(wikitext, r"Infobox\s+(martial artist|mma|boxer|wrestler|"
                                     r"professional wrestler|sportsperson|person)")
    if not block:
        return None
    block = ohne_refs(block)
    felder = {}
    for teil in oberste_teile(block)[1:]:
        if "=" in teil:
            k, v = teil.split("=", 1)
            felder[k.strip().lower()] = v.strip()
    return felder


# ---------------------------------------------------------------- Werte umrechnen

def zahl(s):
    s = s.strip().replace("½", ".5").replace("¼", ".25").replace("¾", ".75")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*\+?\s*(\d+)/(\d+))?", s)
    if not m:
        return None
    x = float(m.group(1))
    if m.group(2):
        x += int(m.group(2)) / int(m.group(3))
    return x


def groesse_cm(text):
    if not text:
        return None
    m = re.search(r"(\d+)\s*(?:ft|feet|foot|′|')\s*(?:(\d+(?:\.\d+)?(?:\s*\+?\s*\d/\d)?|\d+½)\s*"
                  r"(?:in|inch|inches|″|\")?)?", text)
    if m:
        zoll = int(m.group(1)) * 12 + (zahl(m.group(2)) or 0 if m.group(2) else 0)
        if 48 <= zoll <= 96:
            return round(zoll * 2.54)
    m = re.search(r"(\d\.\d{1,2})\s*m\b", text)
    if m:
        return round(float(m.group(1)) * 100)
    m = re.search(r"(\d{3})\s*cm", text)
    if m:
        return int(m.group(1))
    return None


def reichweite_cm(text):
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?(?:\s*\+\s*\d/\d|½)?)\s*(?:in\b|inch|inches|″|\")", text)
    if m:
        x = zahl(m.group(1))
        if x and 50 <= x <= 95:
            return round(x * 2.54)
    m = re.search(r"(\d{3})\s*cm", text)
    if m:
        return int(m.group(1))
    return None


def gewicht_kg(felder):
    for k in ("weight_lb", "weight_lbs"):
        x = zahl(klartext(felder.get(k, "")))
        if x:
            return round(x * 0.45359237, 1), felder[k]
    x = zahl(klartext(felder.get("weight_kg", "")))
    if x:
        return round(x, 1), felder["weight_kg"]
    text = klartext(felder.get("weight", ""))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lb|lbs|pounds)\b", text)
    if m:
        return round(float(m.group(1)) * 0.45359237, 1), text
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", text)
    if m:
        return round(float(m.group(1)), 1), text
    return None, None


def bilanz_normal(text):
    text = klartext(text).replace("–", "-").replace("—", "-").replace(",", " ").strip("* ")
    m = re.search(r"\d+-\d+(?:-\d+)?(?:\s*\(\d+\s*NC\))?", text)
    if not m:
        return None
    b = re.sub(r"\s+", " ", m.group(0))
    return re.sub(r"-0(?= |$)", "", b, count=1) if re.fullmatch(r"\d+-\d+-0.*", b) else b


def bilanz_aus_infobox(f):
    def summe(art):
        direkt = f.get(f"mma_{art}", "")
        if re.fullmatch(r"\d+", klartext(direkt)):
            return int(klartext(direkt)), True
        werte = [klartext(v) for k, v in f.items()
                 if re.fullmatch(rf"mma_\w+_{art}", k)]
        zahlen = [int(v) for v in werte if re.fullmatch(r"\d+", v)]
        return sum(zahlen), bool(zahlen)
    s, s_da = summe("win")
    n, n_da = summe("loss")
    if not (s_da or n_da):
        return None
    d = klartext(f.get("mma_draw", ""))
    nc = klartext(f.get("mma_nc", ""))
    b = f"{s}-{n}"
    if re.fullmatch(r"\d+", d) and int(d):
        b += f"-{d}"
    if re.fullmatch(r"\d+", nc) and int(nc):
        b += f" ({nc} NC)"
    return b


# ---------------------------------------------------------------- Kaderliste

def kampf_zelle(roh):
    """Ergebnis/nächster Kampf/Status aus der Spalte 'Result / next fight / status'."""
    ziele = link_ziele(ohne_refs(roh))
    text = klartext(roh)
    if not text:
        return None, None, None
    teile = [t.strip() for t in re.split(r"\s+[–-]\s+", text)]
    ergebnis = None
    if re.match(r"(Win|Loss|Draw|No contest|NC)\b", teile[0], flags=re.I):
        ergebnis = teile.pop(0)
    if not teile:
        return None, None, text
    m = re.match(r"(.*?)\s*\(([^)]*)\)\s*$", teile[0])
    event, ort = (m.group(1), m.group(2)) if m else (teile[0], None)
    gegner = teile[1] if len(teile) > 1 else None
    if not re.search(r"\bUFC\b|Road to|Contender|Noche|Freedom", event, flags=re.I):
        return None, None, text  # keine Kampfangabe, sondern Status (z. B. verletzt)
    event_ziele = [z for z in ziele if re.search(r"UFC|Road to|Noche", z)]
    kampf = {"event": event, "event_wiki": event_ziele[0] if event_ziele else None,
             "ort": ort, "gegner": gegner}
    if ergebnis:
        kampf["ergebnis"] = ergebnis
        return kampf, None, None
    return None, kampf, None


def lies_kader(wikitext):
    start = wikitext.find("==Debuted fighters==")
    if start < 0:
        start = wikitext.find("== Debuted fighters ==")
    ende = wikitext.find("==See also==", start)
    teil = wikitext[start:ende if ende > 0 else None]
    abschnitte = re.split(r"^===\s*(.+?)\s*===.*$", teil, flags=re.M)
    kader, probleme = [], []
    for i in range(1, len(abschnitte), 2):
        titel = abschnitte[i].lower()
        klasse = next((en for key, en in KLASSEN if titel.startswith(key)), None)
        if not klasse:
            probleme.append("Unbekannte Gewichtsklasse: " + abschnitte[i])
            continue
        for zeile in re.split(r"\n\|-[^\n]*", abschnitte[i + 1])[1:]:
            zeile = zeile.split("\n|}")[0]
            if not zeile.strip():
                continue
            zellen = [z.strip() for z in re.split(r"\n\|", "\n" + zeile.strip("\n"))[1:]]
            if len(zellen) < 9:
                probleme.append(f"Zeile übersprungen ({klasse}): {zeile[:80]!r}")
                continue
            flagge, name_roh, alter, groesse, _spitz, kampf, _ref, _endeavor, mma = zellen[:9]
            land = re.search(r"\|\s*([A-Z]{3})\s*\}\}", flagge)
            sm = re.search(r"\{\{\s*sortname\s*\|([^}]*)\}\}", name_roh, flags=re.I)
            if sm:
                p = [x.strip() for x in sm.group(1).split("|")]
                pos = [x for x in p if "=" not in x]
                name = " ".join(x for x in pos[:2] if x)
                artikel = pos[2] if len(pos) > 2 and pos[2] else name
                if any(x.strip().lower() in ("nolink=1", "nolink=yes") for x in p):
                    artikel = None
            else:
                ziele = link_ziele(name_roh)
                name = klartext(name_roh)
                artikel = ziele[0] if ziele else None
            name = name.strip("* ")
            if not name:
                probleme.append(f"Kein Name ({klasse}): {zeile[:80]!r}")
                continue
            letzter, naechster, status = kampf_zelle(kampf)
            kader.append({
                "name": name,
                "artikel": artikel,
                "gewichtsklasse": klasse,
                "land_iso": land.group(1) if land else None,
                "geburtsdatum": klartext(alter) or None,
                "groesse_cm": groesse_cm(klartext(groesse)),
                "bilanz": bilanz_normal(mma),
                "letzter_kampf": letzter,
                "naechster_kampf": naechster,
                "status": status,
            })
    return kader, probleme


def weiterleitungen(titel):
    """{Titel: Zieltitel} – z. B. 'UFC Fight Night 294' -> 'UFC Fight Night: X vs. Y'."""
    ziel = {}
    titel = sorted(set(titel))
    for i in range(0, len(titel), TITEL_PRO_ANFRAGE):
        teil = titel[i:i + TITEL_PRO_ANFRAGE]
        q = hole({"action": "query", "redirects": "1", "titles": "|".join(teil)}).get("query", {})
        weiter = {}
        for art in ("normalized", "redirects"):
            for x in q.get(art, []):
                weiter[x["from"]] = x["to"]
        for t in teil:
            z = t
            for _ in range(3):
                z = weiter.get(z, z)
            ziel[t] = z
    return ziel


def lies_events(wikitext):
    """{Event-Artikel: Datum} aus der Tabelle 'Scheduled events'."""
    i = wikitext.find('id="Scheduled events"')
    if i < 0:
        return {}
    tabelle = wikitext[i:wikitext.find("\n|}", i)]
    daten = {}
    for zeile in re.split(r"\n\|-[^\n]*", tabelle)[1:]:
        ziele = link_ziele(zeile)
        dm = re.search(r"\{\{\s*dts\s*\|([^}]*)\}\}", zeile, flags=re.I)
        if ziele and dm:
            datum = vorlage("dts", dm.group(1).split("|"))
            if datum:
                daten[ziele[0]] = datum
    return daten


# ---------------------------------------------------------------- Tabellen
# Liest Wikitabellen ({| … |}) und löst zusammengefasste Zellen (rowspan/colspan) auf.

def _teile(text, trenner):
    """Teilt an 'trenner', aber nur außerhalb von {{ }} und [[ ]]."""
    teile, tiefe, start, i = [], 0, 0, 0
    while i < len(text):
        zwei = text[i:i + 2]
        if zwei in ("{{", "[["):
            tiefe += 1
            i += 2
        elif zwei in ("}}", "]]"):
            tiefe -= 1
            i += 2
        elif tiefe == 0 and text.startswith(trenner, i):
            teile.append(text[start:i])
            i += len(trenner)
            start = i
        else:
            i += 1
    teile.append(text[start:])
    return teile


def _attribute_und_inhalt(zelle):
    teile = _teile(zelle, "|")
    if len(teile) > 1 and re.fullmatch(
            r"\s*(?:[\w-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"']+)\s*)*", teile[0]):
        return teile[0], "|".join(teile[1:])
    return "", zelle


def tabelle(text):
    """-> Liste von Zeilen; jede Zeile ist eine Liste von (Inhalt, ist_Kopfzelle)."""
    zeilen, aktuell = [], None
    for zeile in ohne_refs(text).split("\n"):
        s = zeile.strip()
        if s.startswith("{|") or s.startswith("|+"):
            continue
        if s.startswith("|}"):
            break
        if s.startswith("|-"):
            aktuell = []
            zeilen.append(aktuell)
        elif s[:1] in ("|", "!"):
            if aktuell is None:
                aktuell = []
                zeilen.append(aktuell)
            kopf = s[0] == "!"
            rest = s[1:]
            stuecke = [x for t in _teile(rest, "||") for x in (_teile(t, "!!") if kopf else [t])]
            for t in stuecke:
                attr, inhalt = _attribute_und_inhalt(t)
                aktuell.append([attr, inhalt.strip(), kopf])
        elif aktuell:
            aktuell[-1][1] += "\n" + zeile

    raster, offen = [], {}   # offen: Spalte -> [verbleibende Zeilen, Inhalt, Kopf]
    for z in zeilen:
        if not z:
            continue
        zeile, spalte, zellen = [], 0, list(z)
        while zellen or any(k >= spalte for k in offen):
            if spalte in offen:
                o = offen[spalte]
                zeile.append((o[1], o[2]))
                o[0] -= 1
                if o[0] == 0:
                    del offen[spalte]
                spalte += 1
                continue
            if not zellen:
                zeile.append(("", False))
                spalte += 1
                continue
            attr, inhalt, kopf = zellen.pop(0)
            rs = re.search(r"rowspan\s*=\s*\"?(\d+)", attr)
            cs = re.search(r"colspan\s*=\s*\"?(\d+)", attr)
            for _ in range(int(cs.group(1)) if cs else 1):
                zeile.append((inhalt, kopf))
                if rs and int(rs.group(1)) > 1:
                    offen[spalte] = [int(rs.group(1)) - 1, inhalt, kopf]
                spalte += 1
        raster.append(zeile)
    return raster


def tabellen_im_abschnitt(wikitext, ueberschrift):
    """Alle Tabellen unterhalb einer Überschrift (bis zur nächsten gleichrangigen)."""
    m = re.search(r"^(=+)\s*" + re.escape(ueberschrift) + r"\s*=+\s*$", wikitext,
                  flags=re.M | re.I)
    if not m:
        return []
    ende = re.search(r"^={1," + str(len(m.group(1))) + r"}[^=]", wikitext[m.end():], flags=re.M)
    teil = wikitext[m.end():m.end() + ende.start() if ende else None]
    return [teil[i.start():] for i in re.finditer(r"^\{\|", teil, flags=re.M)]


def flagge(roh):
    m = re.search(r"flag(?:icon)?\s*\|\s*(?:icon\s*\|\s*)?([A-Z]{3})\s*[|}]", roh)
    if m:
        return m.group(1)
    # manchmal steht statt des Codes der Ländername: {{flagicon|Islamic Republic of Afghanistan}}
    m = re.search(r"\{\{\s*flag(?:icon)?\s*\|\s*([^|}]+)", roh, flags=re.I)
    return m.group(1).strip() if m else None


def person(roh):
    """Name (wie angezeigt) und verlinkter Artikel aus einer Tabellenzelle."""
    ziele = [z for z in link_ziele(roh) if ":" not in z]
    sm = re.search(r"\{\{\s*sortname\s*\|([^}]*)\}\}", roh, flags=re.I)
    if sm:
        pos = [x.strip() for x in sm.group(1).split("|") if "=" not in x]
        name = " ".join(x for x in pos[:2] if x)
        return name, (pos[2] if len(pos) > 2 and pos[2] else name)
    name = re.sub(r"\s*\((?:c|ic|C|IC)\)\s*", " ", klartext(roh)).strip(" *")
    return name or None, (ziele[0] if ziele else None)


MONATSNAMEN = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}


def datum_englisch(text):
    """'December 13, 2024' oder '13 December 2024' -> '2024-12-13'."""
    t = klartext(text)
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", t) or \
        re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", t)
    if not m:
        return t if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else None
    a, b, j = m.groups()
    monat, tag = (a, b) if not a.isdigit() else (b, a)
    if monat.lower() not in MONATSNAMEN:
        return None
    return f"{int(j):04d}-{MONATSNAMEN[monat.lower()]:02d}-{int(tag):02d}"


def klasse_englisch(text):
    t = klartext(text).lower()
    return next((en for key, en in KLASSEN if t.startswith(key)), klartext(text) or None)


# ---------------------------------------------------------------- Ranglisten, Zu- und Abgänge

def lies_ranglisten(wikitext):
    """Offizielle (Meta-)Ranglisten aller Gewichtsklassen aus 'UFC rankings'."""
    ergebnis = {}
    start = wikitext.find("Meta rankings")
    ende = wikitext.find("media rankings", start)
    teil = wikitext[start:ende if ende > 0 else None]
    abschnitte = re.split(r"^===\s*(.+?)\s*===\s*$", teil, flags=re.M)
    for i in range(1, len(abschnitte), 2):
        klasse = klasse_englisch(abschnitte[i])
        text = abschnitte[i + 1]
        stand = re.search(r"Rankings released on ([^.<]*?\d{4})(?:,\s*after\s*(\[\[[^\]]*\]\]))?", text)
        tab = re.search(r"^\{\|", text, flags=re.M)
        if not tab:
            continue
        plaetze = []
        for z in tabelle(text[tab.start():]):
            if len(z) < 12 or all(k for _, k in z):
                continue
            rang = klartext(z[0][0]).replace("(T)", "").strip()
            name, artikel = person(z[2][0])
            if not rang or not name:
                continue
            serie = re.match(r"\d+", klartext(z[5][0]))
            ergebnis_kampf = klartext(z[6][0])
            naechster, hinweis = None, None
            e_ziele = [x for x in link_ziele(z[10][0]) if re.search(r"UFC|Road to|Noche", x)]
            g_name, g_art = person(z[11][0])
            if e_ziele and z[11][0] != z[10][0]:
                naechster = {"event": klartext(z[10][0]), "event_wiki": e_ziele[0],
                             "gegner": g_name, "gegner_artikel": g_art}
            elif not re.fullmatch(r"(TBD|TBA|To be (determined|announced))?",
                                  klartext(z[10][0]), flags=re.I):
                hinweis = klartext(z[10][0])
            l_ziele = link_ziele(z[7][0])
            g_name, g_art = person(z[8][0])
            plaetze.append({
                "rang": rang, "land_iso": flagge(z[1][0]), "name": name, "artikel": artikel,
                "bilanz": bilanz_normal(z[3][0]),
                "serie": int(serie.group(0)) if serie else None,
                "letzter_kampf": {"ergebnis": ergebnis_kampf or None, "event": klartext(z[7][0]) or None,
                                  "event_wiki": l_ziele[0] if l_ziele else None,
                                  "gegner": g_name, "gegner_artikel": g_art},
                "naechster_kampf": naechster,
                "hinweis": hinweis,
            })
        ergebnis[klasse] = {
            "stand": datum_englisch(stand.group(1)) if stand else None,
            "nach_event": klartext(stand.group(2)) if stand and stand.group(2) else None,
            "plaetze": plaetze,
        }
    return ergebnis


def grund_deutsch(text):
    """Übersetzt nur feste Standardbegriffe; alles andere bleibt im Original."""
    t = klartext(text)
    tl = t.lower()
    if tl.startswith("released"):
        return "Entlassen"
    if tl.startswith("retire"):
        return "Karriereende"
    if any(x in tl for x in ("contract expired", "contract concluded", "contract not renewed",
                             "not re-signed")):
        return "Vertrag ausgelaufen"
    if tl.startswith(("died", "deceased", "passed away")):
        return "Verstorben"
    if "request" in tl and "release" in tl:
        return "Auf eigenen Wunsch"
    m = re.match(r"(?:returned to|re-signed with)\s+(?:the\s+)?(.+)", t, flags=re.I)
    if m:
        return "Zurück zu " + m.group(1)
    m = re.match(r"(?:signed with|joined|moved to|left for)\s+(?:the\s+)?(.+)", t, flags=re.I)
    if m:
        return "Wechsel zu " + m.group(1)
    return t or None


def lies_jahrestabelle(wikitext, ueberschrift, jahr, art):
    """Debüts bzw. Abgänge aus '<Jahr> in UFC' (Spalten: Monat, Tag, ISO, Name, Klasse, …)."""
    eintraege = []
    for t in tabellen_im_abschnitt(wikitext, ueberschrift)[:1]:
        for z in tabelle(t):
            if len(z) < 6 or all(k for _, k in z):
                continue
            monat = MONATSNAMEN.get(klartext(z[0][0]).lower())
            tag = re.match(r"\d+", klartext(z[1][0]))
            name, artikel = person(z[3][0])
            if not (monat and tag and name):
                continue
            e = {"datum": f"{jahr}-{monat:02d}-{int(tag.group(0)):02d}",
                 "land_iso": flagge(z[2][0]), "name": name, "artikel": artikel,
                 "gewichtsklasse": klasse_englisch(z[4][0])}
            if art == "debuet":
                ziele = link_ziele(z[5][0])
                e["event"] = klartext(z[5][0]) or None
                e["event_wiki"] = ziele[0] if ziele else None
            else:
                e["grund"] = grund_deutsch(z[5][0])
                e["grund_original"] = klartext(z[5][0]) or None
                e["kategorie"] = grund_kategorie(e["grund"])
            eintraege.append(e)
    return eintraege


# feste Kategorien für das Abgänge-Diagramm (Reihenfolge = Farbreihenfolge auf der Seite)
KATEGORIEN = ["Entlassen", "Karriereende", "Wechsel zu anderer Liga", "Vertrag ausgelaufen",
              "Sonstiges", "Grund unbekannt"]


def grund_kategorie(grund):
    """Ordnet den (übersetzten) Grund einer festen Kategorie zu. Ohne Grund: 'Grund unbekannt'."""
    if not grund:
        return "Grund unbekannt"
    if grund in ("Entlassen", "Karriereende", "Vertrag ausgelaufen"):
        return grund
    if grund.startswith(("Wechsel zu ", "Zurück zu ")):
        return "Wechsel zu anderer Liga"
    return "Sonstiges"


# ---------------------------------------------------------------- Kalender

def lies_angesetzte_events(wikitext):
    """Tabelle 'Scheduled events' aus 'List of UFC events'."""
    i = wikitext.find('id="Scheduled events"')
    if i < 0:
        return []
    events = []
    for z in tabelle(wikitext[wikitext.rfind("\n", 0, i) + 1:]):
        if len(z) < 4 or all(k for _, k in z):
            continue
        ziele = link_ziele(z[0][0])
        dm = re.search(r"\{\{\s*dts\s*\|([^}]*)\}\}", z[1][0], flags=re.I)
        datum = vorlage("dts", dm.group(1).split("|")) if dm else None
        if not (ziele and datum):
            continue
        events.append({"name": klartext(z[0][0]), "artikel": ziele[0], "datum": datum,
                       "halle": klartext(z[2][0]) or None, "ort": klartext(z[3][0]) or None})
    return events


def lies_kampfkarte(wikitext):
    """Alle Kämpfe aus den Vorlagen {{MMAevent bout|Klasse|A|vs.|B|…|Hinweis}}."""
    kaempfe, karte, pos = [], None, 0
    muster = re.compile(r"\{\{\s*MMAevent (card|bout)", flags=re.I)
    while True:
        m = muster.search(wikitext, pos)
        if not m:
            break
        block = finde_vorlage(wikitext[m.start():], r"MMAevent (?:card|bout)")
        pos = m.start() + (len(block) if block else 10)
        if not block:
            continue
        teile = [t.strip() for t in oberste_teile(ohne_refs(block))]
        if m.group(1).lower() == "card":
            karte = klartext(teile[1]) if len(teile) > 1 else None
            continue
        if len(teile) < 5:
            continue
        a, a_art = person(teile[2])
        b, b_art = person(teile[4])
        hinweis = klartext(teile[8]) if len(teile) > 8 else ""
        titel = bool(re.search(r"\((?:c|ic)\)", teile[2] + teile[4], flags=re.I)
                     or re.search(r"Championship", hinweis))
        kaempfe.append({"gewichtsklasse": klasse_englisch(teile[1]), "a": a, "a_artikel": a_art,
                        "b": b, "b_artikel": b_art, "titelkampf": titel, "karte": karte,
                        "hinweis": hinweis or None})
    return kaempfe


def lies_kalender(events_liste_text):
    events = lies_angesetzte_events(events_liste_text)
    if not events:
        return []
    seiten = hole_quelltexte([e["artikel"] for e in events])
    for e in events:
        titel, text = seiten.get(e["artikel"], (e["artikel"], None))
        e["artikel"] = titel
        e["wikipedia"] = WIKI + urllib.parse.quote(titel.replace(" ", "_"))
        box = infobox_event(text or "")
        if box.get("name"):
            e["name"] = klartext(box["name"])
        e["kaempfe"] = lies_kampfkarte(text or "")
        # Beginn der Hauptkarte (ISO, UTC). Keine erlaubte Quelle nennt ihn bisher -> leer.
        e["hauptkarte_utc"] = None
        e["hauptkarte_quelle"] = None
    return sorted(events, key=lambda e: e["datum"])


def infobox_event(wikitext):
    block = finde_vorlage(wikitext, r"Infobox MMA event")
    if not block:
        return {}
    felder = {}
    for teil in oberste_teile(ohne_refs(block))[1:]:
        if "=" in teil:
            k, v = teil.split("=", 1)
            felder[k.strip().lower()] = v.strip()
    return felder


def artikel_aufloesen(daten, kaempfer):
    """Gleicht verlinkte Artikelnamen (auch Weiterleitungen) mit dem Kader ab."""
    felder = ("artikel", "gegner_artikel", "a_artikel", "b_artikel", "event_wiki")
    titel = set()

    def sammle(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in felder and v:
                    titel.add(v)
                else:
                    sammle(v)
        elif isinstance(x, list):
            for v in x:
                sammle(v)
    sammle(daten)
    ziel = weiterleitungen(list(titel))

    def ersetze(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in felder and v:
                    x[k] = ziel.get(v, v)
                else:
                    ersetze(v)
        elif isinstance(x, list):
            for v in x:
                ersetze(v)
    ersetze(daten)


# ---------------------------------------------------------------- Kalenderdateien (.ics)
# ufc-events.ics: alle kommenden Events zum Abonnieren (täglich neu erzeugt).
# <event>.ics: einzelne Events – nur, wenn der Beginn der Hauptkarte belegt ist.
# Ohne belegte Uhrzeit steht ein Event im Abo als ganztägiger Termin (das Datum ist belegt).

KALENDER = PROJEKT / "data" / "kalender"
ABO_DATEI = "ufc-events.ics"
VTIMEZONE_BERLIN = [
    "BEGIN:VTIMEZONE", "TZID:Europe/Berlin",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:+0100", "TZOFFSETTO:+0200", "TZNAME:CEST",
    "DTSTART:19700329T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:+0200", "TZOFFSETTO:+0100", "TZNAME:CET",
    "DTSTART:19701025T030000", "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU", "END:STANDARD",
    "END:VTIMEZONE",
]


def _ics_text(t):
    return (str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def _falten(zeile):
    """Zeilen nach RFC 5545 bei 75 Bytes umbrechen (ohne UTF-8-Zeichen zu zerteilen)."""
    teile, aktuell = [], ""
    for zeichen in zeile:
        grenze = 75 if not teile else 74
        if len((aktuell + zeichen).encode("utf-8")) > grenze:
            teile.append(aktuell)
            aktuell = ""
        aktuell += zeichen
    teile.append(aktuell)
    return "\r\n ".join(teile)


def _slug(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def _vevent(e, stempel):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    kaempfe = []
    for b in e["kaempfe"]:
        zusatz = ", Titelkampf" if b["titelkampf"] else ""
        kaempfe.append(f"{b['a'] or 'Gegner folgt'} vs. {b['b'] or 'Gegner folgt'}"
                       f" ({b['gewichtsklasse'] or 'Gewichtsklasse folgt'}{zusatz})")
    beschreibung = ("Kämpfe:\n" + "\n".join(kaempfe) if kaempfe else "Kämpfe folgen")
    if not e.get("hauptkarte_utc"):
        beschreibung += "\n\nUhrzeit folgt."
    beschreibung += f"\n\nQuelle: {e['wikipedia']}"
    ort = ", ".join(x for x in (e.get("halle"), e.get("ort")) if x and x not in ("TBA", "TBD"))
    z = ["BEGIN:VEVENT", f"UID:{_slug(e['artikel'])}@ufc-kader", f"DTSTAMP:{stempel}",
         f"SUMMARY:{_ics_text(e['name'])}"]
    if ort:
        z.append(f"LOCATION:{_ics_text(ort)}")
    z += [f"DESCRIPTION:{_ics_text(beschreibung)}", f"URL:{e['wikipedia']}"]
    if e.get("hauptkarte_utc"):
        beginn = datetime.fromisoformat(e["hauptkarte_utc"].replace("Z", "+00:00"))
        berlin = beginn.astimezone(ZoneInfo("Europe/Berlin"))
        z += [f"DTSTART;TZID=Europe/Berlin:{berlin:%Y%m%dT%H%M%S}", "DURATION:PT3H",
              "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(e['name'])}",
              "TRIGGER:-PT30M", "END:VALARM"]
    else:
        tag = datetime.strptime(e["datum"], "%Y-%m-%d")
        z += [f"DTSTART;VALUE=DATE:{tag:%Y%m%d}",
              f"DTEND;VALUE=DATE:{tag + timedelta(days=1):%Y%m%d}", "TRANSP:TRANSPARENT"]
    return z + ["END:VEVENT"]


def _kalender(events, name):
    stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    zeilen = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UFC-Kader//Wikipedia//DE",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_text(name)}",
              "X-WR-TIMEZONE:Europe/Berlin", "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
              "X-PUBLISHED-TTL:PT12H"] + VTIMEZONE_BERLIN
    for e in events:
        zeilen += _vevent(e, stempel)
    zeilen.append("END:VCALENDAR")
    return "\r\n".join(_falten(z) for z in zeilen) + "\r\n"


def schreibe_kalender(events):
    """Schreibt die .ics-Dateien und trägt bei Events mit Uhrzeit den Dateipfad ein."""
    heute = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
    kommend = [e for e in events if e["datum"] >= heute.strftime("%Y-%m-%d")]
    KALENDER.mkdir(parents=True, exist_ok=True)
    behalten = {ABO_DATEI}
    for e in events:
        e["ics"] = None
        if e in kommend and e.get("hauptkarte_utc"):
            datei = _slug(e["artikel"]) + ".ics"
            (KALENDER / datei).write_bytes(_kalender([e], e["name"]).encode("utf-8"))
            e["ics"] = f"data/kalender/{datei}"
            behalten.add(datei)
    (KALENDER / ABO_DATEI).write_bytes(_kalender(kommend, "UFC-Events").encode("utf-8"))
    for alt in KALENDER.glob("*.ics"):
        if alt.name not in behalten:
            alt.unlink()
    return len(kommend), len(behalten) - 1


# ---------------------------------------------------------------- Ranglisten-Archiv
# Jede neue offizielle Rangliste wird mit Datum in data/ranglisten_archiv.json gespeichert.
# Verglichen wird pro Gewichtsklasse mit der letzten gespeicherten Rangliste, die sich
# tatsächlich unterscheidet (andere Plätze UND anderes offizielles Datum).
# Beim allerersten Lauf wird die vorige Rangliste aus der Versionsgeschichte des
# Wikipedia-Artikels "UFC rankings" geholt – ebenfalls eine belegte Quelle.

ARCHIV = PROJEKT / "data" / "ranglisten_archiv.json"


def _platz_schluessel(p):
    return p.get("artikel") or "name:" + p["name"].lower()


def _kurzfassung(r):
    return {"stand": r["stand"], "nach_event": r["nach_event"],
            "plaetze": [{"rang": p["rang"], "name": p["name"], "artikel": p["artikel"]}
                        for p in r["plaetze"]]}


def _gleiche_plaetze(a, b):
    return [(p["rang"], _platz_schluessel(p)) for p in a["plaetze"]] == \
           [(p["rang"], _platz_schluessel(p)) for p in b["plaetze"]]


def _anders(alt, neu):
    return alt["stand"] != neu["stand"] and not _gleiche_plaetze(alt, neu)


def fruehere_ranglisten(aktuell, gesucht, max_abrufe=30):
    """Sucht in der Versionsgeschichte von 'UFC rankings' die vorige Rangliste je Klasse."""
    gefunden = {}
    versionen = hole({"action": "query", "prop": "revisions", "titles": RANGLISTEN,
                      "rvprop": "ids|timestamp", "rvlimit": "500"})
    revs = (versionen.get("query", {}).get("pages") or [{}])[0].get("revisions", [])
    # pro Kalendertag die letzte Version, vom neuesten Tag rückwärts
    pro_tag = {}
    for r in revs:
        pro_tag.setdefault(r["timestamp"][:10], r["revid"])
    for tag in sorted(pro_tag, reverse=True)[1:max_abrufe + 1]:
        if len(gefunden) == len(gesucht):
            break
        d = hole({"action": "query", "prop": "revisions", "revids": str(pro_tag[tag]),
                  "rvprop": "content", "rvslots": "main"})
        seiten = d.get("query", {}).get("pages") or [{}]
        text = (seiten[0].get("revisions") or [{}])[0].get("slots", {}).get("main", {}).get("content")
        if not text:
            continue
        alt = lies_ranglisten(text)
        artikel_aufloesen(alt, None)
        for klasse in gesucht:
            if klasse in gefunden or klasse not in alt or not alt[klasse]["plaetze"]:
                continue
            kurz = _kurzfassung(alt[klasse])
            if kurz["stand"] and _anders(kurz, _kurzfassung(aktuell[klasse])):
                kurz["quelle"] = f"Wikipedia: {RANGLISTEN} (Version vom {tag})"
                gefunden[klasse] = kurz
    return gefunden


def rang_zahl(rang):
    return 0 if rang in ("C", "IC") else int(re.match(r"\d+", rang).group(0)) \
        if re.match(r"\d+", rang or "") else None


def ranglisten_bewegung(ranglisten):
    """Aktualisiert das Archiv und trägt Auf-/Abstiege in die aktuellen Ranglisten ein."""
    archiv = json.loads(ARCHIV.read_text(encoding="utf-8")) if ARCHIV.exists() else {}
    klassen = archiv.setdefault("klassen", {})
    for klasse, r in ranglisten.items():
        verlauf = klassen.setdefault(klasse, [])
        kurz = _kurzfassung(r)
        if not verlauf or not _gleiche_plaetze(verlauf[-1], kurz) or verlauf[-1]["stand"] != kurz["stand"]:
            kurz["quelle"] = f"Wikipedia: {RANGLISTEN}"
            kurz["gespeichert"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            verlauf.append(kurz)

    # Erster Lauf: vorige Rangliste aus der Versionsgeschichte holen (nur einmal versuchen)
    fehlend = [k for k, v in klassen.items()
               if k in ranglisten and not any(_anders(x, _kurzfassung(ranglisten[k])) for x in v)]
    if fehlend and not archiv.get("versionsgeschichte_geprueft"):
        print(f"     Suche vorige Ranglisten in der Wikipedia-Versionsgeschichte ({len(fehlend)} Klassen) …",
              flush=True)
        for klasse, alt in fruehere_ranglisten(ranglisten, fehlend).items():
            klassen[klasse].insert(0, alt)
        archiv["versionsgeschichte_geprueft"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for klasse, r in ranglisten.items():
        kurz = _kurzfassung(r)
        vergleich = next((x for x in reversed(klassen.get(klasse, [])) if _anders(x, kurz)), None)
        r["vergleich"] = ({"stand": vergleich["stand"], "nach_event": vergleich.get("nach_event"),
                           "quelle": vergleich.get("quelle")} if vergleich else None)
        vorher = {_platz_schluessel(p): p["rang"] for p in vergleich["plaetze"]} if vergleich else {}
        alter_champ = next((_platz_schluessel(p) for p in vergleich["plaetze"] if p["rang"] == "C"),
                           None) if vergleich else None
        for p in r["plaetze"]:
            p["bewegung"] = None
            if not vergleich:
                continue
            alt = vorher.get(_platz_schluessel(p))
            if p["rang"] in ("C", "IC"):
                if alt != p["rang"]:
                    p["bewegung"] = {"art": "neuer_champion" if p["rang"] == "C" else "neuer_interims_champion"}
                continue
            if _platz_schluessel(p) == alter_champ:
                p["bewegung"] = {"art": "titel_verloren"}
            elif alt is None:
                p["bewegung"] = {"art": "neu"}
            elif rang_zahl(alt) is not None and rang_zahl(p["rang"]) is not None:
                d = rang_zahl(alt) - rang_zahl(p["rang"])
                p["bewegung"] = {"art": "auf" if d > 0 else "ab" if d < 0 else "gleich", "plaetze": abs(d)}
    ARCHIV.write_text(json.dumps(archiv, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- Siegesserie
# Aus der Tabelle "Mixed martial arts record" im englischen Artikel (neuester Kampf oben).
# Nur übernommen, wenn die Bilanz in der obersten Zeile genau der aktuellen Bilanz
# aus der Kaderliste entspricht – sonst ist die Tabelle evtl. veraltet -> weglassen.
# Serie = Siege in Folge seit der letzten Niederlage, dem letzten Unentschieden oder No Contest.

def _bilanz_teile(text):
    t = (text or "").replace("–", "-").replace("—", "-")
    m = re.search(r"(\d+)-(\d+)(?:-(\d+))?(?:\s*\((\d+)(?:\s*NC)?\))?", t)
    return tuple(int(x or 0) for x in m.groups()) if m else None


def siegesserie_aus_artikel(wikitext, bilanz_liste):
    m = re.search(r"^(==+)\s*Mixed martial arts record\s*==+\s*$", wikitext or "", flags=re.M)
    if not m or not bilanz_liste:
        return None
    rest = wikitext[m.end():]
    ende = re.search(r"^={1," + str(len(m.group(1))) + r"}[^=]", rest, flags=re.M)
    abschnitt = ohne_refs(rest[:ende.start()] if ende else rest)
    start = re.search(r"\{\{\s*MMA record start\s*\}\}", abschnitt, flags=re.I)
    if not start:
        return None
    ergebnisse = []
    for zeile in re.split(r"\n\|-[^\n]*", abschnitt[start.end():])[1:]:
        zeile = re.split(r"\n\|\}|\{\{\s*(?:end|MMA record end)\s*\}\}", zeile)[0]
        zellen = [z.strip() for z in re.split(r"\n\|", "\n" + zeile.strip("\n"))[1:]]
        if len(zellen) < 2:
            continue
        ergebnisse.append((klartext(zellen[0]).strip(), _bilanz_teile(klartext(zellen[1]))))
    if not ergebnisse:
        return None
    oben_ergebnis, oben_bilanz = ergebnisse[0]
    if oben_bilanz != _bilanz_teile(bilanz_liste):
        return None
    serie = 0
    for ergebnis, _ in ergebnisse:
        e = ergebnis.lower()
        if e == "win":
            serie += 1
        elif e in ("loss", "draw", "nc", "no contest"):
            break
        else:
            return None  # unbekannter Eintrag -> nicht sicher bestimmbar
    return serie


# ---------------------------------------------------------------- Weitere Quellen
# Wikidata (CC0) und Wikipedia in anderen Sprachen (CC BY-SA) füllen Lücken bei
# Gewicht, Reichweite, Kampfstil und Geburtsort.
# Zuordnung nur, wenn eindeutig: über den verknüpften englischen Artikel oder –
# bei Kämpfern ohne englischen Artikel – über identischen Namen UND Geburtsdatum.
# Fremdsprachige Begriffe werden nur über die offizielle Sprachverknüpfung des
# verlinkten Artikels ins Englische übertragen (z. B. ru "Бокс" -> en "Boxing").

SPARQL = "https://query.wikidata.org/sparql"

# Sprache -> (Infobox-Name, {Feld: [Parameternamen]})
SPRACHEN = {
    "ru": (r"Боец смешанного стиля",
           {"reichweite": ["размах рук"], "kampfstil": ["стиль"],
            "geburtsort": ["место рождения"]}),
    "ja": (r"MMA statsbox",
           {"reichweite": ["reach"], "kampfstil": ["style"], "geburtsort": ["place"],
            "gewicht": ["kg"]}),
    "es": (r"ficha de (?:luchadores MMA|luchador|artista marcial)",
           {"reichweite": ["alcance"], "kampfstil": ["estilo"],
            "geburtsort": ["lugar_nacimiento", "lugar de nacimiento"], "gewicht": ["peso"]}),
    "pt": (r"Info/Artista marcial",
           {"reichweite": ["envergadura"], "kampfstil": ["modalidade"],
            "geburtsort": ["nascimento_local"], "gewicht": ["peso"]}),
    "de": (r"Infobox Mixed-Martial-Arts-Kämpfer",
           {"reichweite": ["reichweite"], "kampfstil": ["kampfstil"],
            "geburtsort": ["geburtsort"]}),
}
SPRACHNAME = {"ru": "russisch", "ja": "japanisch", "es": "spanisch", "pt": "portugiesisch",
              "de": "deutsch"}
# Vorlagen, die einen Link auf den Geburtsort erzeugen ({{МР|Юклид}} -> [[Юклид]])
ORT_VORLAGEN = r"МР|МестоРождения|Место рождения|МестоРожд"


def sparql(abfrage):
    """Wikidata-Abfrage (POST, mit Cache und Pause)."""
    global _letzte_anfrage
    CACHE.mkdir(parents=True, exist_ok=True)
    datei = CACHE / ("wd_" + hashlib.sha1(abfrage.encode()).hexdigest() + ".json")
    if datei.exists() and time.time() - datei.stat().st_mtime < CACHE_STUNDEN * 3600:
        return json.loads(datei.read_text(encoding="utf-8"))
    for versuch in range(5):
        warten = PAUSE_SEKUNDEN - (time.time() - _letzte_anfrage)
        if warten > 0:
            time.sleep(warten)
        _letzte_anfrage = time.time()
        req = urllib.request.Request(
            SPARQL, data=urllib.parse.urlencode({"query": abfrage, "format": "json"}).encode(),
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                daten = json.loads(r.read().decode("utf-8"))["results"]["bindings"]
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            time.sleep(15 * (versuch + 1))
            continue
        datei.write_text(json.dumps(daten), encoding="utf-8")
        return daten
    raise RuntimeError("Wikidata nicht erreichbar")


def _wert(b, k):
    return b[k]["value"] if k in b else None


def wikidata_daten(items):
    """{Item-ID: {enwiki, geburtsdatum, gewicht_kg, geburtsort, artikel: {sprache: titel}}}"""
    daten = {}
    items = sorted(set(items))
    for i in range(0, len(items), 50):
        werte = " ".join("wd:" + x for x in items[i:i + 50])
        opt = "".join(
            f'OPTIONAL {{ ?a_{s} schema:about ?item; schema:isPartOf <https://{s}.wikipedia.org/>;'
            f' schema:name ?t_{s} }}\n' for s in ["en"] + list(SPRACHEN))
        zeilen = sparql(f"""SELECT ?item ?dob ?m ?munit ?ortLabel {' '.join('?t_' + s for s in ['en'] + list(SPRACHEN))} WHERE {{
          VALUES ?item {{ {werte} }}
          OPTIONAL {{ ?item wdt:P569 ?dob }}
          OPTIONAL {{ ?item p:P2067/psv:P2067 [wikibase:quantityAmount ?m; wikibase:quantityUnit ?munit] }}
          OPTIONAL {{ ?item wdt:P19 ?ort . ?ort rdfs:label ?ortLabel FILTER(LANG(?ortLabel)="en") }}
          {opt}}}""")
        for b in zeilen:
            qid = _wert(b, "item").rsplit("/", 1)[1]
            d = daten.setdefault(qid, {"artikel": {}, "geburtsdatum": set(), "gewicht_kg": set(),
                                       "geburtsort": set()})
            if _wert(b, "dob"):
                d["geburtsdatum"].add(_wert(b, "dob")[:10])
            if _wert(b, "m"):
                einheit = _wert(b, "munit").rsplit("/", 1)[1]
                if einheit == "Q11570":       # Kilogramm
                    d["gewicht_kg"].add(round(float(_wert(b, "m")), 1))
                elif einheit == "Q100995":    # Pfund
                    d["gewicht_kg"].add(round(float(_wert(b, "m")) * 0.45359237, 1))
            if _wert(b, "ortLabel"):
                d["geburtsort"].add(_wert(b, "ortLabel"))
            for s in ["en"] + list(SPRACHEN):
                if _wert(b, "t_" + s):
                    d["artikel"][s] = _wert(b, "t_" + s)
    return daten


def sprachlinks(titel):
    """{englischer Titel: {"qid": Wikidata-ID, sprache: fremder Titel}} über die Wikipedia-API."""
    ergebnis = {t: {} for t in titel}
    for i in range(0, len(titel), TITEL_PRO_ANFRAGE):
        teil = titel[i:i + TITEL_PRO_ANFRAGE]
        for p in hole({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                       "titles": "|".join(teil)}).get("query", {}).get("pages", []):
            if p.get("pageprops", {}).get("wikibase_item") and p["title"] in ergebnis:
                ergebnis[p["title"]]["qid"] = p["pageprops"]["wikibase_item"]
        for sprache in SPRACHEN:
            for p in hole({"action": "query", "prop": "langlinks", "lllang": sprache,
                           "lllimit": "max", "titles": "|".join(teil)}).get("query", {}).get("pages", []):
                if p.get("langlinks") and p["title"] in ergebnis:
                    ergebnis[p["title"]][sprache] = p["langlinks"][0]["title"]
    return ergebnis


def wikidata_zuordnung(eintraege):
    """Ordnet Kämpfern OHNE englischen Artikel ein Wikidata-Item zu –
    nur bei gleichem Namen UND gleichem Geburtsdatum und nur, wenn genau ein Treffer."""
    zuordnung = {}
    ohne = {}
    for i, e in enumerate(eintraege):
        if not e.get("_titel") and e.get("geburtsdatum"):
            ohne.setdefault(e["name"], []).append(i)
    namen = list(ohne)
    for i in range(0, len(namen), 50):
        werte = " ".join(json.dumps(n, ensure_ascii=False) + "@en" for n in namen[i:i + 50])
        treffer = {}
        for b in sparql(f"""SELECT ?item ?name ?dob WHERE {{ VALUES ?name {{ {werte} }}
              ?item rdfs:label|skos:altLabel ?name; wdt:P31 wd:Q5; wdt:P569 ?dob }}"""):
            treffer.setdefault((_wert(b, "name"), _wert(b, "dob")[:10]), set()).add(
                _wert(b, "item").rsplit("/", 1)[1])
        for n in namen[i:i + 50]:
            for idx in ohne[n]:
                items = treffer.get((n, eintraege[idx]["geburtsdatum"]), set())
                if len(items) == 1:
                    zuordnung[idx] = next(iter(items))
    return zuordnung


def englische_titel(sprache, titel):
    """{fremder Titel: englischer Titel} über die Sprachverknüpfungen der Wikipedia."""
    api = f"https://{sprache}.wikipedia.org/w/api.php"
    ergebnis = {}
    titel = sorted(set(t for t in titel if t))
    for i in range(0, len(titel), TITEL_PRO_ANFRAGE):
        teil = titel[i:i + TITEL_PRO_ANFRAGE]
        q = hole({"action": "query", "prop": "langlinks", "lllang": "en", "lllimit": "max",
                  "redirects": "1", "titles": "|".join(teil)}, api).get("query", {})
        weiter = {}
        for art in ("normalized", "redirects"):
            for x in q.get(art, []):
                weiter[x["from"]] = x["to"]
        en = {p["title"]: p["langlinks"][0]["title"] for p in q.get("pages", [])
              if p.get("langlinks")}
        for t in teil:
            z = t
            for _ in range(3):
                z = weiter.get(z, z)
            if z in en:
                # Begriffsklärungszusatz weglassen: "Sambo (martial art)" -> "Sambo"
                ergebnis[t] = re.sub(r"\s*\([^)]*\)$", "", en[z])
    return ergebnis


def fremde_link_ziele(wert):
    wert = re.sub(r"\{\{\s*(?:" + ORT_VORLAGEN + r")\s*\|([^|}]+)[^}]*\}\}", r"[[\1]]",
                  ohne_refs(wert), flags=re.I)
    return [z for z in link_ziele(wert) if ":" not in z]


def mass_aus(wert, art):
    """Zahl + Einheit aus fremdsprachigem Text -> cm bzw. kg (sonst None)."""
    t = klartext(wert).replace(" ", " ")
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    if art == "kg":
        m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|кг)\b", t, flags=re.I)
        if m:
            return round(float(m.group(1)), 1)
        m = re.search(r"(\d+(?:\.\d+)?)\s*(lb|lbs)\b", t, flags=re.I)
        return round(float(m.group(1)) * 0.45359237, 1) if m else None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(cm|см)", t, flags=re.I)
    if m and 140 <= float(m.group(1)) <= 240:
        return round(float(m.group(1)))
    m = re.search(r"(\d\.\d{1,2})\s*(m|м)\b", t)
    if m:
        return round(float(m.group(1)) * 100)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(in\b|дюйм|″)", t)
    if m and 50 <= float(m.group(1)) <= 95:
        return round(float(m.group(1)) * 2.54)
    return None


def weitere_quellen(eintraege, kandidaten):
    """Ergänzt kandidaten[i][feld] um Werte aus Wikidata und anderen Sprachen."""
    print("     Sprachverknüpfungen der englischen Artikel …", flush=True)
    links_en = sprachlinks([e["_titel"] for e in eintraege if e.get("_titel")])
    print("     Wikidata: Kämpfer ohne englischen Artikel zuordnen …", flush=True)
    zuordnung = wikidata_zuordnung(eintraege)
    wd = wikidata_daten(zuordnung.values())
    print(f"     {len(zuordnung)} davon eindeutig bei Wikidata gefunden.", flush=True)
    for i, e in enumerate(eintraege):
        if e.get("_titel") and links_en.get(e["_titel"], {}).get("qid"):
            sl = links_en[e["_titel"]]
            e["wikidata"] = "https://www.wikidata.org/wiki/" + sl["qid"]
            zuordnung[i] = sl["qid"]
            wd[sl["qid"]] = {"artikel": {s: t for s, t in sl.items() if s != "qid"}}

    for i, qid in zuordnung.items():
        d = wd.get(qid, {})
        q = f"Wikidata: {qid}"
        eintraege[i]["wikidata"] = "https://www.wikidata.org/wiki/" + qid
        for kg in sorted(d.get("gewicht_kg", ())):
            kandidaten[i]["gewicht_kg"].append((kg, q))
        for ort in sorted(d.get("geburtsort", ())):
            kandidaten[i]["geburtsort"].append((ort, q))

    for sprache, (box_name, felder) in SPRACHEN.items():
        artikel_von = {i: wd[qid]["artikel"][sprache] for i, qid in zuordnung.items()
                       if sprache in wd.get(qid, {}).get("artikel", {})}
        if not artikel_von:
            continue
        print(f"     Wikipedia {SPRACHNAME[sprache]}: {len(artikel_von)} Artikel", flush=True)
        api = f"https://{sprache}.wikipedia.org/w/api.php"
        texte = hole_quelltexte(list(artikel_von.values()), api)
        boxen, links = {}, []
        for i, titel in artikel_von.items():
            text = texte.get(titel, (None, None))[1]
            block = finde_vorlage(text or "", box_name)
            if not block:
                continue
            box = {}
            for teil in oberste_teile(ohne_refs(block))[1:]:
                if "=" in teil:
                    k, v = teil.split("=", 1)
                    box[k.strip().lower()] = v.strip()
            boxen[i] = (titel, box)
            for feld in ("kampfstil", "geburtsort"):
                for k in felder.get(feld, []):
                    links += fremde_link_ziele(box.get(k, ""))
        uebersetzt = englische_titel(sprache, links)

        for i, (titel, box) in boxen.items():
            q = f"Wikipedia ({SPRACHNAME[sprache]}): {titel}"

            def feld(name):
                return next((box[k] for k in felder.get(name, []) if box.get(k)), "")

            if feld("reichweite"):
                kandidaten[i]["reichweite_cm"].append((mass_aus(feld("reichweite"), "cm"), q))
            if feld("gewicht"):
                kandidaten[i]["gewicht_kg"].append((mass_aus(feld("gewicht"), "kg"), q))
            stile = [uebersetzt.get(z) for z in fremde_link_ziele(feld("kampfstil"))]
            if stile and all(stile):
                kandidaten[i]["kampfstil"].append((", ".join(dict.fromkeys(stile)), q))
            orte = fremde_link_ziele(feld("geburtsort"))
            if orte:
                # genauester Ort: im Japanischen der letzte Link, sonst der erste
                ort = uebersetzt.get(orte[-1] if sprache == "ja" else orte[0])
                if ort:
                    kandidaten[i]["geburtsort"].append((ort, q))


# ---------------------------------------------------------------- Zusammenführen

# Abweichungen bis zu dieser Größe entstehen nur durch Runden beim Umrechnen
# (z. B. 71,5 Zoll = 181,6 cm -> mal 181, mal 182 cm) und gelten nicht als Widerspruch.
TOLERANZ = {"groesse_cm": 1, "reichweite_cm": 1, "gewicht_kg": 0.5}


def _vereinfacht(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def gleich(feld, a, b):
    if feld in TOLERANZ:
        return abs(a - b) <= TOLERANZ[feld]
    if feld == "geburtsort":
        # gleich, wenn der genaueste Ort (erster Teil) der einen Angabe in der anderen steckt
        a, b = _vereinfacht(a), _vereinfacht(b)
        return a.split(",")[0].split(" (")[0].strip() in b or \
            b.split(",")[0].split(" (")[0].strip() in a
    if feld == "kampfstil":
        # gleich, wenn sich die genannten Stile überschneiden
        teile = lambda s: {x.strip() for x in re.split(r"[,/;]| and ", _vereinfacht(s)) if x.strip()}
        return bool(teile(a) & teile(b))
    return a == b


def vergleiche(eintrag, feld, werte):
    """werte = [(wert, quelle), …]. Setzt Feld + Quelle; bei Widerspruch -> konflikte."""
    vorhanden = [(w, q) for w, q in werte if w not in (None, "")]
    if not vorhanden:
        eintrag[feld] = None
        return
    eintrag[feld] = vorhanden[0][0]
    eintrag["quellen"][feld] = vorhanden[0][1]
    if any(not gleich(feld, w, x) for w, _ in vorhanden for x, _ in vorhanden):
        eintrag["konflikte"][feld] = [{"wert": w, "quelle": q} for w, q in vorhanden]


def main():
    print("1/4  Lade Kaderliste von Wikipedia …", flush=True)
    seiten = hole_quelltexte([LISTE, EVENTS])
    liste_text, events_text = seiten[LISTE][1] or "", seiten[EVENTS][1] or ""
    kader, probleme = lies_kader(liste_text)
    events = lies_events(events_text)
    print(f"     {len(kader)} Kämpfer in der Liste, {len(events)} angesetzte Events.")

    print("2/4  Lade Kämpfer-Artikel (Infoboxen) …", flush=True)
    artikel = hole_quelltexte([k["artikel"] for k in kader if k["artikel"]])

    print("3/4  Lese Infoboxen und Kampftermine …", flush=True)
    event_titel = {k["naechster_kampf"]["event_wiki"] for k in kader
                   if k["naechster_kampf"] and k["naechster_kampf"]["event_wiki"]}
    event_ziel = weiterleitungen(list(event_titel) + list(events))
    events = {event_ziel.get(t, t): d for t, d in events.items()}
    q_liste = "Wikipedia: " + LISTE
    ausgabe, kandidaten = [], []
    for k in kader:
        e = {"name": k["name"], "artikel": None, "wikipedia": None,
             "gewichtsklasse": k["gewichtsklasse"], "land_iso": k["land_iso"],
             "quellen": {}, "konflikte": {}}
        e["quellen"]["gewichtsklasse"] = e["quellen"]["land_iso"] = q_liste
        info, q_art = None, None
        if k["artikel"] and artikel.get(k["artikel"], (None, None))[1]:
            titel, text = artikel[k["artikel"]]
            e["artikel"] = titel
            info = infobox(text)
            if info is not None:
                e["wikipedia"] = WIKI + urllib.parse.quote(titel.replace(" ", "_"))
                e["_titel"] = titel
                q_art = "Wikipedia: " + titel
        info = info or {}

        vergleiche(e, "bilanz", [(k["bilanz"], q_liste),
                                 (bilanz_aus_infobox(info) if info else None, q_art)])
        # nur ein eindeutiges Datum aus der Vorlage {{birth date|J|M|T}} übernehmen
        geb = klartext(info.get("birth_date", ""))
        geb = geb if re.fullmatch(r"\d{4}-\d{2}-\d{2}", geb) else None
        vergleiche(e, "geburtsdatum", [(k["geburtsdatum"], q_liste), (geb, q_art)])
        vergleiche(e, "groesse_cm", [(k["groesse_cm"], q_liste),
                                     (groesse_cm(klartext(info.get("height", ""))), q_art)])
        kg, _roh = gewicht_kg(info)
        kandidaten.append({
            "gewicht_kg": [(kg, q_art)],
            "reichweite_cm": [(reichweite_cm(klartext(info.get("reach", ""))), q_art)],
            "kampfstil": [(klartext(info.get("style", "")) or None, q_art)],
            "geburtsort": [(klartext(info.get("birth_place", "")) or None, q_art)],
        })
        vergleiche(e, "nationalitaet", [(klartext(info.get("nationality", "")) or None, q_art)])

        # Siegesserie: aus der Kampftabelle (nur wenn sie zur aktuellen Bilanz passt) oder,
        # bei Kämpfern ohne Niederlage, Unentschieden und No Contest, direkt aus der Bilanz.
        serie, q_serie = None, None
        if q_art:
            serie = siegesserie_aus_artikel(artikel[k["artikel"]][1], k["bilanz"])
            if serie is not None:
                q_serie = f"{q_art} (Tabelle „Mixed martial arts record“)"
        teile = _bilanz_teile(k["bilanz"])
        if serie is None and teile and teile[1:] == (0, 0, 0) and "bilanz" not in e["konflikte"]:
            serie, q_serie = teile[0], q_liste + " (nur Siege)"
        e["siegesserie"] = serie
        if q_serie:
            e["quellen"]["siegesserie"] = q_serie

        e["letzter_kampf"] = k["letzter_kampf"]
        n = k["naechster_kampf"]
        if n:
            ziel = event_ziel.get(n["event_wiki"], n["event_wiki"])
            n = dict(n, datum=events.get(ziel))
        e["naechster_kampf"] = n
        if k["letzter_kampf"] or n:
            e["quellen"]["kaempfe"] = q_liste
        if n and n["datum"]:
            e["quellen"]["kampfdatum"] = "Wikipedia: " + EVENTS
        e["status"] = k["status"]
        ausgabe.append(e)

    print("4/4  Ergänze Lücken aus Wikidata und anderen Wikipedia-Sprachen …", flush=True)
    weitere_quellen(ausgabe, kandidaten)
    for e, kand in zip(ausgabe, kandidaten):
        for feld, werte in kand.items():
            vergleiche(e, feld, werte)
        e.pop("_titel", None)
        e.setdefault("wikidata", None)

    jahr = datetime.now(timezone.utc).year
    jahresartikel = f"{jahr} in UFC"
    print("     Ranglisten, Debüts, Abgänge und Kampfkarten …", flush=True)
    seiten = hole_quelltexte([RANGLISTEN, jahresartikel])
    weitere = {
        "ranglisten": lies_ranglisten(seiten[RANGLISTEN][1] or ""),
        "debuets": lies_jahrestabelle(seiten[jahresartikel][1] or "", "Debut UFC fighters",
                                      jahr, "debuet"),
        "abgaenge": lies_jahrestabelle(seiten[jahresartikel][1] or "", "Releases and retirements",
                                       jahr, "abgang"),
        "events": lies_kalender(events_text),
    }
    artikel_aufloesen([weitere, ausgabe], ausgabe)

    # Schutz: Hat sich der Aufbau einer Wikipedia-Seite geändert und kommt dadurch kaum
    # etwas an, wird die alte Datei NICHT überschrieben. Die Webseite bleibt dann
    # beim letzten guten Stand, und die GitHub Action meldet einen Fehler.
    fehler = []
    if len(ausgabe) < 300:
        fehler.append(f"nur {len(ausgabe)} Kämpfer in der Kaderliste (erwartet: über 300)")
    if len(weitere["ranglisten"]) < 11:
        fehler.append(f"nur {len(weitere['ranglisten'])} Ranglisten (erwartet: 11)")
    if not weitere["events"]:
        fehler.append("keine angesetzten Events gefunden")
    if fehler:
        sys.exit("ABGEBROCHEN, Daten wurden nicht gespeichert: " + "; ".join(fehler))

    ranglisten_bewegung(weitere["ranglisten"])
    anzahl_abo, anzahl_einzeln = schreibe_kalender(weitere["events"])

    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    AUSGABE.write_text(json.dumps({
        "stand": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "jahr": jahr,
        "quellen": [WIKI + LISTE.replace(" ", "_"), WIKI + EVENTS.replace(" ", "_"),
                    WIKI + RANGLISTEN.replace(" ", "_"), WIKI + jahresartikel.replace(" ", "_"),
                    "Wikipedia-Artikel der einzelnen Events (siehe Feld 'wikipedia')",
                    "Wikipedia-Artikel der einzelnen Kämpfer (siehe Feld 'wikipedia')",
                    "Wikidata (siehe Feld 'wikidata')",
                    "Wikipedia auf Russisch, Japanisch, Spanisch, Portugiesisch, Deutsch"],
        "lizenz": "Wikipedia-Inhalte: CC BY-SA 4.0; Wikidata: CC0",
        "anzahl": len(ausgabe),
        "kaempfer": ausgabe,
        **weitere,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    bericht(ausgabe, probleme)
    print(f"\nRanglisten: {len(weitere['ranglisten'])} Gewichtsklassen, "
          f"{sum(len(r['plaetze']) for r in weitere['ranglisten'].values())} Plätze")
    mit_vergleich = [k for k, r in weitere["ranglisten"].items() if r["vergleich"]]
    print(f"Ranglisten mit Vergleich (Pfeile): {len(mit_vergleich)} von {len(weitere['ranglisten'])}")
    print(f"Debüts {jahr}: {len(weitere['debuets'])}, Abgänge {jahr}: {len(weitere['abgaenge'])}")
    print(f"Angesetzte Events: {len(weitere['events'])}, "
          f"Kämpfe darin: {sum(len(e['kaempfe']) for e in weitere['events'])}")
    print(f"Kalender: Abo mit {anzahl_abo} Events, {anzahl_einzeln} Einzeldateien mit Uhrzeit")
    print(f"Siegesserie sicher bestimmt: {sum(1 for e in ausgabe if e['siegesserie'] is not None)} Kämpfer")


def bericht(ausgabe, probleme):
    felder = [("name", "Name"), ("gewichtsklasse", "Gewichtsklasse"), ("bilanz", "Bilanz"),
              ("geburtsdatum", "Geburtsdatum"), ("groesse_cm", "Größe"),
              ("gewicht_kg", "Gewicht"), ("reichweite_cm", "Reichweite"),
              ("kampfstil", "Kampfstil"), ("geburtsort", "Geburtsort"),
              ("land_iso", "Land"), ("naechster_kampf", "Nächster Kampf")]
    n = len(ausgabe)
    print(f"\nFertig: {n} aktive Kämpfer -> {AUSGABE.relative_to(PROJEKT)}\n")
    print(f"{'Feld':<16}{'vorhanden':>10}{'fehlt':>8}{'Konflikte':>11}")
    for feld, titel in felder:
        da = sum(1 for e in ausgabe if e.get(feld) not in (None, ""))
        ko = sum(1 for e in ausgabe if feld in e["konflikte"])
        print(f"{titel:<16}{da:>10}{n - da:>8}{ko:>11}")
    ohne = sum(1 for e in ausgabe if not e["wikipedia"])
    print(f"\nOhne eigenen Wikipedia-Artikel: {ohne}")
    termin = sum(1 for e in ausgabe if e["naechster_kampf"] and e["naechster_kampf"]["datum"])
    print(f"Nächster Kampf mit Datum: {termin}")
    if probleme:
        print(f"\nHinweise beim Einlesen ({len(probleme)}):")
        for p in probleme[:15]:
            print("  -", p)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Abgebrochen.")
