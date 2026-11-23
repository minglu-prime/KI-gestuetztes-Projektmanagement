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
  Protokollordner sind drei Namen: `agent.LOG_DIR` (dort schreiben die Agenten),
  `tracking.LOG_DIR` und `workbench.LOG_DIR` (beim Import kopiert, dort wird gelesen). Seit
  PR 83 lesen alle Funktionen Pfade und Port beim Aufruf (Quellregel), nicht beim Import.
- **Vorführen ohne Kontingent.** Für Demo oder Video die Agentenfunktionen
  (`agent.run_planning`, `lifecycle.run_*`, `followup.run_*`, `closing.run_lessons`) durch
  feste Antworten ersetzen und die Pfade wie oben umleiten, in einer eigenen Startdatei
  neben `app.py`, die nicht ins Repository kommt. Bearbeitbare Tabellen sind ein Canvas:
  Playwright kann dort nicht zuverlässig tippen, Werte dann über die Paketfunktionen setzen.
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

## Stand am 22.11.2026

- **Seiten.**
  - Neun Schritte, vom Projektauftrag bis zum Abschluss.
  - Das Menü hat acht Einträge: Startseite; Vorbereiten; Planung, Durchführung, Kontrolle, Abschluss; KI-Lab; Info.
  - Die übrigen Seiten einer Gruppe sind im Menü verborgen (`st.Page(visibility="hidden")`) und erscheinen als Reiter oben auf der Seite (`ui.GROUPS`, `ui.group_tabs`), wobei der zugehörige Gruppeneintrag im Menü hervorgehoben bleibt:
    - Vorbereiten: Projektauftrag, Anforderungen, Entwurf, Testplan
    - Kontrolle: Test
    - Info: Impressum
  - Betrieb und nächster Durchlauf sind Reiter im Abschluss.
- **Ergebnis zuerst.**
  - Jede Seite mit einer Prüfung beginnt mit einer Ergebniszeile (`ui.verdict`): rot „Achtung“, golden „Zu entscheiden“, grün „In Ordnung“.
  - Helfer: `check_verdict`, `phase_verdict`, `forecast_verdict`.
  - `forecast_verdict` nennt neben der Prognose auch Mehraufwand: Fertige Aufgaben mehr als `ui.COST_TOLERANCE` (10 %, Vorschlag) über Plan geben „Zu entscheiden“. Der CPI zählt Begonnenes als 0 und ist früh zu niedrig, deshalb nicht er (PR 82).
  - Der Abschluss zählt Lücken im Betriebshandbuch als Warnungen der Ergebniszeile; den neuen Durchlauf blockieren sie nicht (PR 82, 84).
  - In der Planung heißt Schritt 6 „Übernehmen“ (dort liegt „Plan als Projekt übernehmen“).
  - Test: Ein fehlgeschlagener Fall mit nur behobenem Fehler bleibt ein Fehler (PR 84). Fehler haben ein Behebungsdatum (`fixed_on`); damit trennt die Prüfung „noch nicht wiederholt“ (`Testfall wiederholen`) von „an einem späteren Tag wieder fehlgeschlagen“ (`neuen Fehler erfassen oder Fehler wieder öffnen`), am selben Tag nennt die Meldung beides. Bestehende Fehler und Störungen lassen sich im Formular auswählen, ändern und wieder öffnen.
  - Eine Quellregel verlangt sie überall, wo `messages(` steht.
  - Die Runden eines Laufs stehen nur noch im Statuskasten (nach Erfolg zugeklappt).
  - Markdown-Vorschauen unter Downloads sind entfernt (Quellregel).
- **Modell.**
  - Die Agenten rufen die OpenAI Responses API auf (eigene Schleife in `agent._run`, Werkzeuge als `tools.Tool`, Reasoning `medium`).
  - Die Oberfläche sagt „der Agent“ (Quellregel).
  - Freitexte der Agenten haben Längengrenzen: `tools.LIMITS`, etwa ein Satz, die Zusammenfassung 400 Zeichen. Jedes Einreichungswerkzeug schickt zu Langes zurück (`tools.too_long`); die Modelle nehmen längere Texte weiter an.
  - Eingaben der Agenten vor und nach dem Plan schreiben Daten und Zahlen deutsch (`tracking.as_shown`, `key_figures`; Quellregel). Der Planungsagent behält ISO-Daten für `set_absence`.
- **Echte Läufe am 21.11.2026** (Endpunkt der Hochschule, `gpt-6-sol`):
  - Alle elf Agenten und das KI-Lab je einmal ohne Fehler, Auswertung in `03-Experiment/agentenlauf-2026-11-21/`.
  - Mit den Grenzen lag kein Freitext darüber, und keiner ging wegen Länge zurück; die Texte sind 26 % kürzer als am 20.11.
  - Danach Durchführung und Testplan nach der Datumskorrektur: keine ISO-Daten oder Dezimalpunkte mehr.
  - `data/` blieb jeweils unberührt.
- **KI-Lab.**
  - Liest `OPENAI_BASE_URL`, das Modell aus `PM_MODEL` oder ersatzweise `PM_AGENT_MODEL`, Reasoning `PM_LAB_REASONING_EFFORT`.
  - Der Freeze verlangt Key und Modellnamen, kein Datum (Entscheidung E01). Die Auswertung nennt die antwortenden Modelle (`models_returned`, `model_varies`).
  - Issue #9 ist geschlossen, Nachweis in `04-Prototyp/ki_lab/VERIFIKATION.md`.
  - Formale Fälle aus einer privaten Datei (#6): `PM_LAB_MATERIALS` oder `--materials`, gleiches Format wie `cases.json`, Prüfung beim Laden; der Freeze hält Version, Prüfsumme und Quelle (`öffentlich`/`privat`) fest. Die Fälle selbst schreibt die Gruppe.
  - Einwilligungen nennen den Dienst, an den die Daten gehen: `ui.ai_service` (Host aus `OPENAI_BASE_URL`) auf den Seiten, der eingefrorene Endpunkt im Lab; eine Quellregel verbietet „an (die) OpenAI (API)“.
- **Prüfen.**
  - `04-Prototyp/pm_agent/docs/pruefplan.md`: Prüfplan für einen Testlauf durch einen Coding-Agenten (statisch, Unit, Integration, Smoke im Browser, Datenvergleich). Codex lief ihn am 22.11.2026 auf `701337c`: alles grün, eine Lücke (keine Kette über alle Phasen).
  - Die Lücke schließt `test_one_project_goes_from_the_auftrag_to_the_next_run` in `tests/test_app.py` (PR 80): ein Projekt nur über die Seiten vom Auftrag bis zum neuen Durchlauf.
- **Betrieb im Netz (Plan).** `04-Prototyp/pm_agent/docs/betrieb-cloud.md` (PR 81): Streamlit bleibt als dauerhafter Container, Daten in Supabase Postgres (EU), Speicher hinter `store.py`, fünf PRs. Nichts davon umgesetzt; zuerst Vorbedingung 1 (siehe Offen, Punkt 8).
- **Videos** (auf Wunsch der Projektleitung, 22.11.2026, nicht im Repository): ein Demo-Durchlauf (3 min) und zwei Werbefassungen mit Titelkarten, Übergängen, selbst erzeugter Musik, Lupe an Klicks und Zoom auf Diagramme. Erzeugt mit Playwright, OpenCV und PyAV aus einer Demo mit festen Agentenantworten.
- **Forschungsordner** (Entwürfe, von der Gruppe zu bestätigen):
  - `01-Projektplanung/entscheidungen.md`: Entscheidungslog, E01; `agenda-entscheidungen.md`: alle offenen Entscheidungen der Gruppe als Agenda (#1).
  - `02-Recherche/`: Baseline, KI-Lösungen, Chancen und Risiken; 20 Quellen, 13 im Volltext.
  - `03-Experiment/`: Versuchsdesign, Pilot-Checkliste, Bewertungsrubrik, Teilnahmeinformation (#8), Durchführungsprotokoll (#10), Agentenlauf.
  - `05-Ergebnisse/berichtsvorlage.md`.

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

## Projekt in Zahlen (22.11.2026, `main` nach PR 84)

- **Repository:** 324 Commits auf `main` (244 ohne Merges) seit dem 28.10.2026, 72 gemergte PRs, **0 Releases, 0 Tags**.
- **Fachcode:** rund 10 100 Zeilen Python (ohne Leerzeilen und Kommentare).
  - `pm_agent` 9 445 (Paket und Seiten)
  - `ki_lab` 656
  - dazu 9 Prompts, 8 Vorlagen, CSS
- **Tests:** 704, alle ohne Netz (661 `pm_agent`, 43 `ki_lab`); dazu ein Live-Test, der sich ohne Schlüssel überspringt. CI: `pm-agent.yml` (Lint, Tests) und `static.yml` (README als Pages).
- **Betrieb:** läuft lokal als Streamlit-Seite. Das Menü in 8 Einträgen ist in Chrome geprüft (1440 px und 375 px), am 22.11. auch in Edge (Codex, 13 Seiten bei 375 px ohne waagrechtes Scrollen); Firefox und WebKit nur für den Stand vor dem 21.11. Kein öffentlicher Betrieb.
- **Issues:** 11 (#1–#11, Meilensteine M1–M4).
  - #9 geschlossen.
  - #2–#5, #7 und #11 haben Entwürfe und einen Kommentar dazu.
  - #1, #6, #8 und #10 liegen bei der Gruppe.
  - Keines ist zugewiesen.

## Offen, nach Wirkung geordnet

1. **Die Forschungsarbeit liegt bei der Gruppe.**
   - Ausgangspunkt ist `01-Projektplanung/agenda-entscheidungen.md`: alle offenen Entscheidungen in der Reihenfolge, in der sie voneinander abhängen.
   - Entwürfe prüfen und beschließen (#2–#5, #7, #11). Dabei die schweren Fehler aus `02-Recherche/baseline.md`, Abschnitt 5, und `03-Experiment/bewertungsrubrik.md` zu einer Liste machen.
   - Dann folgen, in dieser Reihenfolge:
     - Rollen und Termine (#1)
     - private formale Fälle (#6)
     - Piloten und Rater (#7)
     - Teilnehmende (#8)
     - Erhebung (#10)
     - Bericht (#11)
   - Daten zur Frage des Projekts gibt es noch nicht.
2. **Teilnahmeinformation fertig machen (#8).** Die Einwilligungen nennen seit PR 77 den richtigen Dienst. In `03-Experiment/teilnahmeinformation.md` fehlen noch Kontakt, Löschdatum und Name des Dienstes. Die Einwilligung zu Zitaten fragt das Lab nicht ab: auf Papier einholen oder im Lab ergänzen (Agenda M2).
3. **Mehrere Läufe je Agent.** Ein Lauf je Agent und Tag reicht nicht für Aussagen über Runden, Token oder Dauer. `03-Experiment/agentenlauf-2026-11-21/run_agents.py` wiederholt den Lauf (kostet Kontingent, nur auf Wort der Projektleitung).
4. **Agenten fachlich.**
   - Bei einer Abwesenheit trägt die Umplanung sie ein, verteilt aber keine Aufgabe um: Das Ende rückt hinter die Deadline (21.11.: 24.12.2026). `replanning.md` verlangt jetzt die Umverteilung blockierter Aufgaben (noch nicht live geprüft).
   - Die neue Zusammenfassung der Durchführung nannte das Ende nur als „nach der Deadline“, ohne Datum. `check_summary` verlangt jetzt das Prognosedatum, wenn das Ende nach der Deadline liegt (noch nicht live geprüft).
5. **Einen Stand festhalten.** Es gibt kein Release. Ein `v0.1` mit „was geht, mit welchem Modell geprüft“ (öffentlich: nur auf Wort der Projektleitung).
6. **Issues pflegen.** Zuständige eintragen; die Meilenstein-Issues in Aufgaben für einen Tag zerlegen.
7. **Code, nicht dringend.**
   - `views/planung.py` (rund 1 200 Zeilen) teilen, wenn dort wieder gearbeitet wird.
   - Englische Kommentare und Docstrings sagen noch „Claude“.
   - Firefox und WebKit nach den Menü-Änderungen erneut prüfen, gern in der CI.
   - `tracking.LOG_DIR` und `workbench.LOG_DIR` sind Kopien von `agent.LOG_DIR`: auf einen Namen zurückführen (ändert die Test-Fixtures).
   - Ein direkter Aufruf einer Unterseite (etwa `/planung`) erzeugt zwei 404 auf `/planung/_stcore/…` in der Konsole; die Seite lädt normal. Vermutlich Streamlit selbst, nicht geprüft.
8. **Betrieb im Netz.** Plan in `04-Prototyp/pm_agent/docs/betrieb-cloud.md`, Weg A (Streamlit-Container, Supabase). Vorher klären, Antwort steht aus:
   - Darf der KI:connect-Schlüssel auf einem Server für die Gruppe genutzt werden, und ist die API von außerhalb des Hochschulnetzes erreichbar? Ansprechpartner: KI:connect-Verantwortliche der HSBI, sonst `kiconnect@cls.rwth-aachen.de`.
   - Laut Hilfeseite von KI:connect gelten API-Schlüssel einen Monat, und die Hochschule legt Monatsbudget und parallele Anfragen je Gruppe fest. Ein Server braucht also einen Schlüsselwechsel je Monat.
   - Bis dahin: nur auf dem eigenen Rechner, ohne Anmeldung nicht für andere öffnen.

## Lokaler Stand dieses Rechners

- `data/` enthält ein erfundenes Beispielprojekt (Team Anna, Ben, Clara) mit freigegebenem Projektauftrag, Anforderungen, Entwurf und Testplan aus den Läufen vom 18.11.2026.
- `logs/` enthält die Protokolle der echten Läufe. Nichts davon ist im Repository.
  - mit Claude: 11. bis 18.11.2026
  - mit `gpt-6-sol`: `gpt-6-sol-20261120/`, `lauf-20261121/` (alle Agenten und KI-Lab) und `check-20261121/` (Durchführung und Testplan nach der Datumskorrektur)
- `origin` zeigt auf `minglu-prime/KI-gestuetztes-Projektmanagement` (das Repository ist umgezogen; die alte Adresse leitet um).
- Im Worktree `project-structure-review-16429a` liegen unversioniert der Testbericht von Codex (`04-Prototyp/pm_agent/docs/test-report.md`, Chinesisch) und zwei Bildschirmfotos. Nicht committen ohne Übersetzung und Wort der Projektleitung.
- `.claude/` (nicht im Repository): `launch.json` für den Entwicklungsserver und der Skill `sibling-fix` für Fehlerbehebungen. `.claude/` steht zusätzlich in `.git/info/exclude`, weil das Wurzelverzeichnis keine `.gitignore` hat (eine eigene würde mit PR 12 kollidieren).
- Entfernte Branches außer `main`:
  - `feat/polish`: zusammengeführt, bleibt auf Wunsch
  - `feat/pm-experiment-lab`: PR 12
  - `test/planning-execution-control-flow`: Teammitglied
  - Die letzten beiden nicht anfassen. Alle anderen Branches dieser Arbeit sind gelöscht.
