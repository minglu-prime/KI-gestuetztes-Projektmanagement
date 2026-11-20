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
  Durchlauf sind Reiter im Abschluss. Das Menü gruppiert nach Phase (Vorbereiten, Umsetzen),
  nicht danach, wo ein Agent arbeitet. `main` nach PR 62, 626 Tests, CI grün.
- **Modell.** Die Agenten rufen die OpenAI API auf (Chat Completions, eigene Schleife in
  `agent._run`, Werkzeuge als `tools.Tool`). Das Paket `anthropic` ist entfernt.
- **Echte Läufe.** Gegen die OpenAI-Schnittstelle lief bisher nur die Planung (20.11.2026,
  `gpt-6-sol` an einem kompatiblen Endpunkt: 3 Runden, 38 s, Plan ohne Fehler). Alle übrigen
  Agenten liefen zuletzt am 18.11.2026 gegen die Claude API, also vor dem Wechsel. Noch nie
  live gelaufen: eine Abwesenheit, die der Agent beim Umplanen einträgt (`set_absence`).

## Zugang zum Modell (lokal, nicht im Repository)

`04-Prototyp/pm_agent/.env` enthält vier Einstellungen; die Werte nicht ausgeben:

- `OPENAI_API_KEY`: Schlüssel eines OpenAI-kompatiblen Dienstes der Hochschule, kein
  Schlüssel von api.openai.com. Ohne `OPENAI_BASE_URL` antwortet OpenAI mit 401.
- `OPENAI_BASE_URL`: Adresse dieses Dienstes.
- `PM_AGENT_MODEL`: die Modell-ID der Schnittstelle (klein, mit Bindestrichen), nicht der
  Anzeigename. Welche es gibt, sagt `OpenAI().models.list()`. Kein Standard im Code.
- `PM_AGENT_REASONING_EFFORT=none`: Das gewählte Modell nimmt Werkzeuge in Chat Completions
  nur so an (sonst 400). Die Schnittstelle `/v1/responses` nimmt Werkzeuge mit Reasoning;
  der Dienst unterstützt sie (einmal geprüft), die Schleife nutzt sie noch nicht.

Ein Wert mit Leerzeichen bricht das Einlesen der Datei durch `uv run --env-file .env` ab.
Der echte Test: `uv run --env-file .env pytest tests/test_agent_live.py` (verbraucht
Kontingent, nur auf Wort der Projektleitung).

## Offen, in dieser Reihenfolge sinnvoll

1. **„Claude“ in der Oberfläche.** Seiten, Meldungen, Tests und Dokumente nennen das Modell
   weiter „Claude“ (rund 350 Stellen), obwohl ein anderes Modell arbeitet. Die Projektleitung
   hat noch nicht entschieden, wie es heißen soll. Vorher fragen; dann in eigenen PRs unter
   etwa 800 Zeilen.
2. **Übrige Agenten live prüfen** (Projektauftrag, Anforderungen, Entwurf, Testplan, Plan im
   Gespräch ändern, Durchführung, Kontrolle, Lessons Learned). Die Prompts sind unverändert
   und waren für Claude geschrieben.
3. **Reasoning.** Mit „none“ plant das Modell ohne Nachdenken. Für größere Projekte auf
   `/v1/responses` umstellen oder es als zweite Schnittstelle anbieten.
4. **Zustimmungstexte.** Sie nennen die „OpenAI API“; mit `OPENAI_BASE_URL` gehen die Daten an
   den dort eingetragenen Dienst.
5. **Vergleich mit Versuchspersonen im KI-Lab.** Das Lab ruft `/v1/responses` bei
   api.openai.com direkt auf (`ki_lab/lab.py`, ohne `OPENAI_BASE_URL`); mit dem Schlüssel der
   Hochschule läuft es so nicht. Ein erfolgreicher KI-Aufruf des Labs steht noch aus.
6. **Arbeit der Gruppe außerhalb des Prototyps:** die Ordner `01-Projektplanung`,
   `02-Recherche`, `03-Experiment` und `05-Ergebnisse` sind leer.
7. Kleineres: Prüfung in Firefox und Safari; die drei Reiter des Abschlusses bei 375 px.

## Lokaler Stand dieses Rechners

- `data/` enthält ein erfundenes Beispielprojekt (Team Anna, Ben, Clara) mit freigegebenem
  Projektauftrag, Anforderungen, Entwurf und Testplan aus den Läufen vom 18.11.2026.
- `.claude/` (nicht im Repository): `launch.json` für den Entwicklungsserver und der Skill
  `sibling-fix` für Fehlerbehebungen.
- Entfernte Branches außer `main`: `feat/polish` (zusammengeführt, bleibt auf Wunsch),
  `feat/pm-experiment-lab` (PR 12) und `test/planning-execution-control-flow` (Teammitglied):
  die letzten beiden nicht anfassen.
