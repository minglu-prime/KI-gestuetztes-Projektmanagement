# Hinweise für Coding-Agenten

Die Regeln für Änderungen stehen in `AGENTS.md`:

@AGENTS.md

Code, Tests und die Seiten liegen in `04-Prototyp/pm_agent` (Einstieg: dessen `README.md`), die
zehn Phasen und wie sie zusammenhängen in `04-Prototyp/pm_agent/docs/lebenszyklus.md`.

## Zusammenarbeit mit der Projektleitung

- **Sprachen.** Mit der Projektleitung im Chat Chinesisch. Oberfläche, Prüfmeldungen,
  Dokumente und PR-Texte Deutsch. Code, Kommentare und Commit-Nachrichten Englisch
  (Conventional Commits).
- **Nur auf ausdrückliches Wort:** pushen, PR öffnen, mergen, Branches löschen (lokal wie
  entfernt). Jede dieser Aktionen einzeln bestätigen lassen. Kein Force-Push, kein Auto-Merge.
- **Keine bezahlten API-Läufe ungefragt.** Den API-Schlüssel nie erfragen oder ausgeben; er
  steht lokal in `04-Prototyp/pm_agent/.env`.
- **Öffentliches Repository.** Nie committen: `data/`, `logs/`, `.env`, `ki_lab/data/`,
  `*.db`, Teamdaten, Namen von Gruppenmitgliedern, `.claude/`. Vor jedem Commit
  `git status` lesen.
- **Fremde Arbeit.** PR 12 (`feat/pm-experiment-lab`) und den Branch eines Teammitglieds
  (`test/planning-execution-control-flow`) nicht anfassen. Keine neuen Dateien im
  Wurzelverzeichnis, die mit PR 12 kollidieren.
- **Keine Videos oder GIFs** der Website aufnehmen, außer die Projektleitung fragt danach.
  Screenshots sind in Ordnung.
- **Arbeitsweise.** Erst ein Test, der den Fehler zeigt, dann die Reparatur; die Ursache
  benennen. Keine leeren `except`-Blöcke und keine stillen Ersatzwerte. Jede Funktion zeigt
  Laden, leeren Zustand und Fehler. Vor „fertig“: `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest`. Am Ende Annahmen und offene Randfälle
  nennen.

## Stolperstellen

- **Echte Daten.** Ein Skript, das Funktionen des Pakets direkt aufruft (Live-Lauf,
  Experiment), schreibt sonst in die echten Dateien: `tracking.adopt` speichert ohne `path`
  nach `data/projekt.json`. Vorher `tracking.PROJECT_FILE`, `lifecycle.FILE`,
  `workbench.TEAM_FILE` und die Protokollordner auf einen Temp-Ordner setzen (wie die
  Fixture `local` in `tests/test_app.py`) und `data/` vorher und nachher vergleichen.
- **Entwicklungsserver.** Streamlit führt `views/` bei jedem Lauf neu aus, behält aber das
  Paket unter `src/pm_agent` im Speicher. Nach Änderungen dort den Server neu starten. Der
  Seitenordner heißt `views/`, nicht `pages/` (sonst baut Streamlit ein zweites Menü). Server
  nur auf localhost.
- **Bewegung prüfen.** In einem verdeckten Browserfenster laufen Animationen nicht. Live
  prüfen mit Chrome im Headless-Modus über das DevTools-Protokoll: nach einem Klick im Menü
  je Bild `getComputedStyle` abtasten; `prefers-reduced-motion` über
  `Emulation.setEmulatedMedia`. Zahlen im Format „localized“ folgen `navigator.languages`.
- **Tabellen in AppTest.** Bearbeitungen eines `st.data_editor` über den Helfer `edit_table`
  in `tests/test_app.py` nachstellen.
- **Windows.** Python öffnet keine Pfade der Form `/d/...`, `D:/...` verwenden. Für Umlaute in
  der Konsole `PYTHONIOENCODING=utf-8` setzen.

## Stand am 20.11.2026

- **Seiten.** Neun Schritte, vom Projektauftrag bis zum Abschluss; Betrieb und der nächste
  Durchlauf sind Reiter im Abschluss. Das Menü gruppiert nach Phase (Vorbereiten, Umsetzen).
- **Modell.** Die Agenten rufen die OpenAI Responses API auf (eigene Schleife in
  `agent._run`, Werkzeuge als `tools.Tool`, Reasoning `medium`). Das Paket `anthropic` ist
  entfernt. Die Oberfläche nennt den Akteur „der Agent“, nicht mehr „Claude“; eine Quellregel
  in `tests/test_source_rules.py` hält das fest (Kommentare und Docstrings dürfen es noch
  anders nennen).
- **Echte Läufe am 20.11.2026** (Endpunkt der Hochschule, `gpt-6-sol`): alle elf Agenten liefen
  je einmal ohne Fehler, auch die Abwesenheit aus einem Wunsch (`set_absence` trug Clara vom
  7. bis 11.12. ein). Ein Lauf des KI-Labs mit KI-Antwort ebenfalls. Die Läufe gingen in einen
  Temp-Ordner, `data/` blieb unberührt.
- **KI-Lab.** Liest `OPENAI_BASE_URL`, das Modell aus `PM_MODEL` oder ersatzweise
  `PM_AGENT_MODEL` und schickt Reasoning (`PM_LAB_REASONING_EFFORT`, Standard `medium`).

## Zugang zum Modell (lokal, nicht im Repository)

`04-Prototyp/pm_agent/.env`; die Werte nicht ausgeben:

- `OPENAI_API_KEY`: Schlüssel eines OpenAI-kompatiblen Dienstes der Hochschule (KI:connect),
  kein Schlüssel von api.openai.com. Ohne `OPENAI_BASE_URL` antwortet OpenAI mit 401.
- `OPENAI_BASE_URL`: Adresse dieses Dienstes.
- `PM_AGENT_MODEL`: die Modell-ID der Schnittstelle (klein, mit Bindestrichen), nicht der
  Anzeigename. Welche es gibt, sagt `OpenAI().models.list()`. Kein Standard im Code.
- Optional `PM_AGENT_REASONING_EFFORT` (Standard `medium`), `PM_LAB_REASONING_EFFORT`.

Ein Wert mit Leerzeichen bricht das Einlesen der Datei durch `uv run --env-file .env` ab.
Echter Test: `uv run --env-file .env pytest tests/test_agent_live.py` (verbraucht Kontingent,
nur auf Wort der Projektleitung). Chat Completions nimmt bei diesem Modell Werkzeuge nur mit
`reasoning_effort` „none“ an; deshalb Responses.

## Projekt in Zahlen (20.11.2026, `main` nach PR 65)

- 284 Commits auf `main` (223 ohne Merges) seit dem 28.10.2026, 53 gemergte PRs, **0 Releases,
  0 Tags**.
- Fachcode rund 9 900 Zeilen Python (ohne Leerzeilen und Kommentare) mit 356 Funktionen:
  `pm_agent` 9 260 Zeilen (Paket und Seiten), `ki_lab` 610. Dazu 9 Prompts, 8 Vorlagen, CSS.
- 666 Tests (629 `pm_agent`, 37 `ki_lab`), alle ohne Netz; dazu ein Live-Test, der sich ohne
  Schlüssel überspringt. CI: `pm-agent.yml` (Lint, Tests) und `static.yml` (README als Pages).
- Läuft lokal als Streamlit-Seite: geprüft in Chrome, Firefox und WebKit (Playwright), je 1440 px
  und 375 px. Nicht geprüft: Safari auf einem echten Mac, Edge. Kein öffentlicher Betrieb.
- 11 Issues (#1–#11, Meilensteine M1–M4), alle offen, keines zugewiesen.

## Offen, nach Wirkung geordnet

1. **Die Forschungsarbeit.** Alle Issues sind offen, die Ordner `01-Projektplanung`,
   `02-Recherche`, `03-Experiment` und `05-Ergebnisse` sind leer. Das Werkzeug ist weit, die
   Frage des Projekts („Was ändert KI im Projektmanagement?“) hat noch keine Daten.
2. **KI-Lab für die formale Studie.** Der „Freeze“ des Protokolls verlangt eine datierte
   Modell-Snapshot-ID (Name endet auf `YYYY-MM-DD`, `ki_lab/lab.py`, `freeze`). `gpt-6-sol` hat
   keine: der Pilot geht, die formale Studie nicht. Bei KI:connect nach einem datierten Modell
   fragen, sonst mit der Gruppe entscheiden, wie der feste Modellstand belegt wird. Das ist
   eine Studienentscheidung, keine des Coding-Agenten.
3. **Vorhandene Vergleichsdaten auswerten.** Alle Agenten liefen je einmal mit Claude
   (18.11.2026) und mit `gpt-6-sol` (20.11.2026); die Protokolle liegen lokal in `logs/` (die vom
   20.11. im Unterordner `logs/gpt-6-sol-20261120/`). Vergleichbar: Runden, Ablehnungen durch
   Python, Dauer, Token, Plan vor der Deadline. Für belastbare Aussagen je Agent mehrere Läufe
   (z. B. fünf; kostet Kontingent, nur auf Wort der Projektleitung).
4. **Einen Stand festhalten.** Es gibt kein Release. Ein `v0.1` mit „was geht, mit welchem
   Modell geprüft“ gibt Gruppe und Betreuung einen Bezugspunkt (öffentlich: nur auf Wort der
   Projektleitung).
5. **Issues pflegen.** Zuständige eintragen; die Meilenstein-Issues in Aufgaben für einen Tag
   zerlegen, damit morgens geplant und abends mit Nachweis geschlossen werden kann. #9 ist am
   weitesten: echter KI-Aufruf und Browserprüfung haben jetzt Nachweise, das datierte Modell
   fehlt noch.
6. **Genauigkeit.** Die Zustimmungstexte nennen die „OpenAI API“, die Daten gehen aber an den
   Dienst in `OPENAI_BASE_URL` (KI:connect); für die Datenschutzangaben genau benennen. Die
   Prompts sind für Claude geschrieben und mit dem neuen Modell je einmal gelaufen: Qualität
   der Ergebnisse lesen, nicht nur „Prüfung bestanden“.
7. **Code, nicht dringend.** `views/planung.py` hat rund 1 190 Zeilen und ist am schwersten zu
   ändern; teilen, wenn dort wieder gearbeitet wird. Englische Kommentare und Docstrings sagen
   noch „Claude“. Die Prüfung in Firefox und WebKit lief nur lokal; sie könnte in die CI.
8. **Betrieb, vorsichtig.** Die Seite läuft nur auf dem eigenen Rechner. Für die Gruppe auf
   einem Server erst mit Anmeldung und geschütztem Schlüssel, sonst nutzt jeder das Kontingent.

## Lokaler Stand dieses Rechners

- `data/` enthält ein erfundenes Beispielprojekt (Team Anna, Ben, Clara) mit freigegebenem
  Projektauftrag, Anforderungen, Entwurf und Testplan aus den Läufen vom 18.11.2026.
- `logs/` enthält die Protokolle der echten Läufe: mit Claude (11. bis 18.11.2026) und mit
  `gpt-6-sol` (20.11.2026, Unterordner `gpt-6-sol-20261120/`). Nicht im Repository.
- `.claude/` (nicht im Repository): `launch.json` für den Entwicklungsserver und der Skill
  `sibling-fix` für Fehlerbehebungen.
- Entfernte Branches außer `main`: `feat/polish` (zusammengeführt, bleibt auf Wunsch),
  `feat/pm-experiment-lab` (PR 12) und `test/planning-execution-control-flow` (Teammitglied):
  die letzten beiden nicht anfassen.
