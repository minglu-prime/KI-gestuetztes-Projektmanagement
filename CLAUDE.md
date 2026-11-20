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

- Neun Schritte als Seiten, vom Projektauftrag bis zum Abschluss; Betrieb und der nächste
  Durchlauf sind Reiter im Abschluss. Das Menü gruppiert nach Phase (Vorbereiten, Umsetzen),
  nicht danach, wo ein Agent arbeitet. 625 Tests.
- Seit dem 20.11.2026 rufen die Agenten die OpenAI API auf (Chat Completions, `agent._run`;
  `OPENAI_API_KEY` und `PM_AGENT_MODEL` in `.env`). Gegen sie ist noch kein Agent gelaufen. Die
  Oberfläche nennt das Modell weiter „Claude“; die Umbenennung steht aus.
- Am 18.11.2026 liefen alle Agenten einmal ohne Fehler gegen die Claude API: Projektauftrag,
  Anforderungen, Entwurf, Testplan, Planung, Plan im Gespräch ändern, Durchführung,
  Kontrolle, Lessons Learned. Noch nicht live gelaufen: eine Abwesenheit, die der Agent beim
  Umplanen selbst einträgt (`set_absence`).
- Offen: der Vergleich mit Versuchspersonen im KI-Lab (ein erfolgreicher KI-Aufruf des Labs
  steht noch aus), eine Prüfung in Firefox und Safari, die Ordner `01-Projektplanung`,
  `02-Recherche`, `03-Experiment` und `05-Ergebnisse`.
