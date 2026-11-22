# Prüfplan für einen Testlauf durch einen Coding-Agenten

Stand: 22.11.2026, `main` nach PR 78. Der Plan sagt, **was** zu prüfen ist, **womit**, und
**was als bestanden gilt**. Er ändert keinen Code. Findet der Lauf einen Fehler, wird er nur
berichtet (Schritt, Befehl, kürzeste entscheidende Ausgabezeile), nicht repariert.

## 0. Regeln für den Lauf

- Arbeitsordner: `04-Prototyp/pm_agent` (Site) und `04-Prototyp/ki_lab` (Studienserver).
- **Keine bezahlten API-Aufrufe.** `.env` nicht laden, nicht lesen, nicht ausgeben.
  `tests/test_agent_live.py` überspringt sich ohne Schlüssel; so soll es bleiben.
- **Echte Daten schützen.** `data/`, `logs/` und `ki_lab/data/` werden nicht verändert.
  Vor und nach dem Lauf Prüfsummen bilden und vergleichen (Schritt 1 und 8).
- Server nur auf `localhost`. Keine Commits, kein Push, keine PRs, keine Kommentare in Issues.
- Keine Videos oder GIFs; Screenshots sind erlaubt.
- Windows: Pfade als `D:/...`, für Umlaute `PYTHONIOENCODING=utf-8`.

## 1. Vorbereitung

```bash
cd 04-Prototyp/pm_agent
uv sync --locked --python 3.11
# Prüfsummen der lokalen Daten (Ordner fehlen in einem frischen Checkout: dann notieren "nicht vorhanden")
find data logs ../ki_lab/data -type f -exec sha256sum {} + 2>/dev/null | sort > /tmp/vorher.txt
```

Bestanden: `uv sync` ohne Fehler.

## 2. Statische Prüfung (Lint, Format, Syntax)

| Was | Befehl | Bestanden |
|---|---|---|
| Lint Python | `uv run ruff check .` | 0 Befunde |
| Format Python | `uv run ruff format --check .` | „already formatted“ |
| Syntax KI-Lab-Frontend | `node --check web/app.js` (in `ki_lab`) | Exit 0 |

## 3. Unit-Tests (einzelne Module, ohne Streamlit, ohne Netz)

`uv run pytest <Datei> -q`, je Gruppe einzeln, damit ein Fehler eindeutig zuzuordnen ist.

| Bereich | Dateien | Was sie abdecken |
|---|---|---|
| Datenmodell | `test_models.py` | Validierung von Projekt, Mitglied, Aufgabe |
| Planung und Kalender | `test_planning.py`, `test_finish_dates.py` | Arbeitstage, Abhängigkeiten, Puffer, Enden (`working_shift`) |
| Durchführung und Kontrolle | `test_tracking.py`, `test_changes.py`, `test_history.py` | Ist-Stunden, Verzug, Prognose, Änderungen, Verlauf |
| Lebenszyklus | `test_lifecycle.py`, `test_testplan.py` | Projektauftrag, Anforderungen, Entwurf, Testplan |
| Abschluss, Folgeprojekt | `test_closing.py`, `test_followup.py` | Lessons learned, Kennzahlen, nächster Durchlauf |
| Team und Dateien | `test_workbench.py`, `test_reports.py` | Teamdatei, Exporte (Markdown, CSV) |
| Werkzeuge der Agenten | `test_tools.py`, `test_agent.py` | Einreichungswerkzeuge, Längengrenzen (`tools.LIMITS`), Antwortprüfung |
| Ergebniszeile | `test_verdict.py` | `check_verdict`, `phase_verdict`, `forecast_verdict` |
| Diagramme, Barrierefreiheit | `test_diagram.py`, `test_accessibility.py` | Gantt/Diagramme, Kontrast ≥ 4,5 : 1, Bildbeschreibungen |
| Quellregeln | `test_source_rules.py` | Verbotene Muster in allen Seiten (z. B. „Claude“ in der Oberfläche, Vorschauen, ISO-Daten) |
| KI-Lab | in `ki_lab`: `uv run --no-project --python 3.11 python -m unittest discover -s tests -v` | Freeze, Abläufe, Zeitlimit, Auswertung (`summarize`), HTTP, Stil |

Bestanden: alle grün. Erwartung zum Vergleich: 649 Tests `pm_agent` (+1 übersprungen), 43 `ki_lab`.
Abweichende Anzahl melden.

## 4. Integrations- und Kettentests (mehrere Module zusammen, weiter ohne Netz)

| Kette | Datei | Was durchläuft |
|---|---|---|
| Agentenschleife | `test_agent_loop.py` | echter OpenAI-SDK-Client gegen eine geskriptete Fake-API: Runden, Ablehnung, Protokolle, fehlende Zugangsdaten |
| Seiten mit Streamlit AppTest | `test_app.py` | jede Seite rendert; Menü und Reiter (`ui.GROUPS`); Ergebniszeile oben; Tabellen bearbeiten → Seite wechseln → zurück → speichern (`edit_table`) |
| Robustheit | `test_robustness.py` | unlesbare/beschädigte Dateien, beschädigte Teamdatei, KI-Lab-Kindprozess |
| Site ↔ KI-Lab | `test_lab_server.py` | echter Start des Studienservers, Antwort, erlaubter Frame, Stopp, belegter Port |
| Start | `test_launch.py` | Streamlit bindet an Loopback |

**Fachliche Kette** (AGENTS.md: ein Fall über alle Phasen): mit
`uv run pytest tests/test_app.py -q -k "plan or durchf or kontroll or abschluss"` die Fälle
heraussuchen, die einen Plan übernehmen und danach Durchführung, Kontrolle und Exporte
prüfen. Berichten, welche Phasenübergänge **kein** Test abdeckt (Lücke, keine Reparatur).

Bestanden: alle grün, keine Warnung über offene Dateien oder hängende Prozesse.

## 5. Gesamtlauf wie in der CI

```bash
uv run pytest -q
```

Muss dasselbe Ergebnis wie die Summe aus 3 und 4 liefern. Zusätzlich die Laufzeit melden
und `uv run pytest -q --durations=10` für die langsamsten Tests.

## 6. Smoke-Test der laufenden Site (Browser, ohne Agentenlauf)

```bash
uv run streamlit run app.py --server.headless true --server.address localhost \
  --server.port 8501 --browser.gatherUsageStats false
```

In einem Browser `http://localhost:8501` öffnen und **nur ansehen, nichts speichern, keinen
Agenten starten**:

1. Startseite lädt, keine rote Fehlermeldung, keine Fehler in der Browserkonsole.
2. Menü hat genau 8 Einträge: Startseite, Vorbereiten, Planung, Durchführung, Kontrolle,
   Abschluss, KI-Lab, Info.
3. Jeder Eintrag öffnet seine Seite. Auf Vorbereiten die Reiter Projektauftrag,
   Anforderungen, Entwurf, Testplan; auf Kontrolle der Reiter Test; auf Info Impressum.
4. Seiten mit Prüfung beginnen mit einer Ergebniszeile („Achtung“, „Zu entscheiden“ oder
   „In Ordnung“).
5. Ohne `data/` (frischer Checkout): jede Seite zeigt einen leeren Zustand statt eines Fehlers.
6. Breite 375 px: kein waagrechtes Scrollen (`document.documentElement.scrollWidth <= 375`).
7. Je ein Screenshot von Startseite und Planung bei 1440 px.

Danach Server beenden. Bestanden: 1–6 erfüllt.

## 7. Smoke-Test KI-Lab (ohne KI-Aufruf)

```bash
cd ../ki_lab
uv run --no-project --python 3.11 python server.py --port 8874 --db /tmp/lab-smoke.db
```

`http://localhost:8874` öffnen: Startseite des Labs lädt, keine Konsolenfehler. Keine Frage an
die KI stellen. Server beenden, `/tmp/lab-smoke.db` löschen.

```bash
uv run --no-project --python 3.11 python manage.py --db /tmp/lab-smoke.db status
```

Bestanden: Seite lädt; `status` antwortet ohne Traceback.

## 8. Abschluss

```bash
cd ../pm_agent
find data logs ../ki_lab/data -type f -exec sha256sum {} + 2>/dev/null | sort > /tmp/nachher.txt
diff /tmp/vorher.txt /tmp/nachher.txt && echo "Daten unverändert"
git status --short
```

Bestanden: „Daten unverändert“ und `git status` ohne Änderungen (außer diesem Plan, falls er
noch nicht eingecheckt ist).

## Nicht Teil dieses Laufs

- **Live-Test mit dem Modell** (`uv run --env-file .env pytest tests/test_agent_live.py`,
  `03-Experiment/agentenlauf-2026-11-21/run_agents.py`): kostet Kontingent, nur auf Wort der
  Projektleitung.
- Firefox und WebKit: offen laut `CLAUDE.md`, nicht automatisiert.
- Bewegung/Animationen: nur mit Chrome headless über DevTools prüfbar (siehe `CLAUDE.md`).

## Bericht

Eine Tabelle je Schritt: Schritt, Befehl, Ergebnis (bestanden/fehlgeschlagen/übersprungen),
Anzahl Tests, Dauer, bei Fehlern die kürzeste entscheidende Zeile. Getrennt angeben:
Offline-Tests, Browserprüfung, Provider-Aufruf (hier: keiner).
