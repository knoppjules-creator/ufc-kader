# UFC-Kader – Projektregeln

## Grundregel: Niemals raten

- **Nur Daten eintragen, die aus einer Quelle stammen.** Keine Schätzungen, keine Werte aus dem Gedächtnis, keine "wahrscheinlich richtigen" Ergänzungen.
- **Fehlt ein Wert, bleibt das Feld leer.** Auf der Webseite wird dann "folgt" angezeigt. In der JSON-Datei steht `null`.
- **Widersprechen sich Quellen, werden beide Werte angezeigt**, jeweils mit Angabe der Quelle (z. B. "185 cm (UFCStats) / 183 cm (Wikipedia)"). Es wird nicht stillschweigend einer ausgewählt.
- Jeder Wert soll nachvollziehbar sein: Zu jedem Kämpfer wird gespeichert, aus welcher Quelle (URL) die Daten stammen.
- Zuordnung zu einer zweiten Quelle nur, wenn eindeutig: über eine offizielle Verknüpfung (z. B. Sprachlink des Wikipedia-Artikels) oder über gleichen Namen **und** gleiches Geburtsdatum. Nie über den Namen allein.
- Fremdsprachige Begriffe (Kampfstil, Geburtsort) werden nur über die offizielle Sprachverknüpfung des verlinkten Wikipedia-Artikels übersetzt. Ohne Verknüpfung wird der Wert nicht übernommen.
- Rundungsunterschiede beim Umrechnen (bis 1 cm bzw. 0,5 kg) gelten nicht als Widerspruch.

## Erlaubte Quellen (geprüft am 21.10.2026)

- Erlaubt: Wikipedia (alle Sprachen) und Wikidata über die offiziellen Schnittstellen. Pflicht: Quellenangabe „Wikipedia, CC BY-SA 4.0“ auf der Seite.
- Nicht erlaubt: ufc.com, ESPN, Sherdog (Nutzungsbedingungen verbieten es), ufcstats.com und Tapology (sperren Programme aus). Nicht verwenden und Sperren nicht umgehen.

## Darstellung

- Gewichtsklassen auf Englisch (z. B. "Lightweight", "Women's Strawweight").
- Maße in cm und kg (Umrechnung aus Zoll/Pfund ist erlaubt, das ist kein Raten – die Originalwerte bleiben in den Rohdaten erhalten).
- Keine Uhrzeiten anzeigen (vom Nutzer so entschieden), nur das Datum der Events.
- Design und Funktionen der bisherigen Seite `ufc-kader.html` bleiben erhalten.

## Datenabruf

- Vor dem Abfragen einer Seite robots.txt und Nutzungsbedingungen beachten.
- Langsam abfragen (mindestens einige Sekunden Pause zwischen Anfragen), eindeutigen User-Agent mit Kontakt angeben.
- Bereits geladene Seiten zwischenspeichern, damit nicht unnötig oft abgefragt wird.

## Projektaufbau

- `scraper/sammle_kaempfer.py` – sammelt die Kämpferdaten (nur Python-Standardbibliothek, keine Zusatzpakete nötig).
- `data/fighters.json` – Ergebnis, aus dem die Webseite liest. Enthält: `kaempfer` (Profile), `ranglisten`, `events` (Kalender mit Kampfkarten), `debuets`, `abgaenge`, `neu_unter_vertrag`.
- `ufc-kader.html` – die Webseite. Enthält keine eigenen Kämpferdaten mehr, nur Darstellung und feste Tabellen (Gewichtslimits, deutsche Ländernamen).
- `.github/workflows/aktualisieren.yml` – GitHub Action: holt täglich um 04:00 UTC neue Daten, speichert `data/fighters.json` im Repository und veröffentlicht die Seite auf GitHub Pages (`ufc-kader.html` wird dort auch als `index.html` abgelegt). Schlägt das Datenholen fehl, bleibt die Seite beim letzten guten Stand.
- Schutz im Skript: Kommen weniger als 300 Kämpfer, weniger als 11 Ranglisten oder keine Events an, wird nichts gespeichert (vermutlich hat sich der Aufbau einer Wikipedia-Seite geändert).
- Lokal ansehen: Im Projektordner `python3 -m http.server` starten, dann `http://localhost:8000/ufc-kader.html` öffnen. Per Doppelklick geöffnet kann der Browser die JSON-Datei nicht laden.
