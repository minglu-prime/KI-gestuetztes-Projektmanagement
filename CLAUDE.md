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
  `workbench.TEAM_FILE` und `agent.LOG_DIR` auf einen Temp-Ordner setzen (wie die
  Fixture `local` in `tests/test_app.py`) und `data/` vorher und nachher vergleichen.
  Der Protokollordner hat nur diesen einen Namen: Agenten schreiben, Seiten lesen dort
  (Quellregel gegen `from … import LOG_DIR`). Seit PR 83 lesen alle Funktionen Pfade und
  Port beim Aufruf (Quellregel), nicht beim Import. In den Tests leitet die autouse-Fixture
  `no_real_data` in `tests/conftest.py` alle diese Pfade um, auch `workbench.DATA_DIR` und
  `RUNS_CSV`; `test_no_test_reaches_the_real_data_or_logs` wacht darüber (PR 105).
- **Vorführen ohne Kontingent.** Für Demo oder Video die Agentenfunktionen
  (`agent.run_planning`, `lifecycle.run_*`, `followup.run_*`, `closing.run_lessons`) durch
  feste Antworten ersetzen und die Pfade wie oben umleiten, in einer eigenen Startdatei
  neben `app.py`, die nicht ins Repository kommt. Bearbeitbare Tabellen sind ein Canvas:
  Playwright kann dort nicht zuverlässig tippen, Werte dann über die Paketfunktionen setzen.
- **404 in der Konsole.** Wird eine Unterseite direkt aufgerufen (etwa `/kontrolle`), fragt
  Streamlit 1.67 erst `/kontrolle/_stcore/health` und `/host-config` (404), dann `/_stcore/…`
  (200). Eine leere Streamlit-App mit zwei Seiten tut dasselbe (23.11.2026): kein Fehler der Site.
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
- **Zweite Meinung.** Die Gemini-CLI bricht auf diesem Konto mit `IneligibleTierError` ab.
  Ein Review durch GPT läuft über Codex mit dem Modell `gpt-5.6-sol`; das Standardmodell
  steht diesem ChatGPT-Konto nicht offen.
  - Gemini geht über die lokale Antigravity-CLI:
    `agy -p "<Prompt>" --model gemini-4-carbon-high --sandbox` (`agy models` nennt Gemini 4
    Carbon, Neon, Argon, Hydrogen).
  - Im Modus `-p` lässt sich keine Werkzeuganfrage freigeben, ein Shell-Befehl beendet den
    Lauf. Der Prompt sagt deshalb „nur read_file, keine Shell“, nennt die zu lesenden Dateien
    und schließt `.env`, `data/` und `logs/` aus.
  - Nicht `--mode plan` für eine Antwort: Das schreibt nur `implementation_plan.md` unter
    `~/.gemini/antigravity-cli/brain/` und wartet auf „Proceed“.
  - `agy agentapi` braucht Adresse und CSRF-Token des laufenden Sprachservers und liefert
    keine Antwort: hier nicht brauchbar.
- **Windows.** Python öffnet keine Pfade der Form `/d/...`, `D:/...` verwenden. Für Umlaute in
  der Konsole `PYTHONIOENCODING=utf-8` setzen.

## Stand am 25.11.2026

- **Seiten.**
  - Neun Schritte, vom Projektauftrag bis zum Abschluss.
  - Das Menü hat acht Einträge: Startseite; Vorbereiten; Planung, Durchführung, Kontrolle, Abschluss; KI-Lab; Info.
  - Die übrigen Seiten einer Gruppe sind im Menü verborgen (`st.Page(visibility="hidden")`) und erscheinen als Reiter oben auf der Seite (`ui.GROUPS`, `ui.group_tabs`); der Eintrag der Gruppe bleibt im Menü hervorgehoben (PR 86):
    - Vorbereiten: Projektauftrag, Anforderungen, Entwurf, Testplan
    - Kontrolle: Test
    - Info: Impressum
  - Betrieb und nächster Durchlauf sind Reiter im Abschluss.
  - Die Kontrolle hat sechs Reiter: Stand, Prognose, Plan und Ist, Kennzahlen, Demos, Agent und Bericht (`kontrolle_tab`). Beim Ankommen wählt sie Prognose, wenn das Ende das Problem ist, sonst Stand; danach gilt die Wahl der Projektleitung. Reiterleisten brechen bei 375 px in eine zweite Zeile um (PR 105).
- **Ergebnis zuerst.**
  - Jede Seite mit einer Prüfung beginnt mit einer Ergebniszeile (`ui.verdict`): rot „Achtung“, golden „Zu entscheiden“, grün „In Ordnung“.
  - Helfer: `check_verdict`, `phase_verdict`, `forecast_verdict`.
  - `forecast_verdict` nennt neben der Prognose auch Mehraufwand: Fertige Aufgaben mehr als `ui.COST_TOLERANCE` (10 %, Vorschlag) über Plan geben „Zu entscheiden“. Der CPI zählt Begonnenes als 0 und ist früh zu niedrig, deshalb nicht er (PR 82).
  - Der Abschluss zählt Lücken im Betriebshandbuch als Warnungen der Ergebniszeile; den neuen Durchlauf blockieren sie nicht (PR 82, 84).
  - In der Planung heißt Schritt 6 „Übernehmen“ (dort liegt „Plan als Projekt übernehmen“).
  - Test: Ein fehlgeschlagener Fall mit nur behobenem Fehler bleibt ein Fehler (PR 84). „behoben“ speichert den Tag (`Defect.fixed_on`, PR 86); die Meldung sagt danach „Testfall wiederholen“ (Ergebnis vor der Behebung) oder „neuen Fehler erfassen oder Fehler wieder öffnen“ (danach), am selben Tag beides (PR 87). Ältere Fehler ohne Tag: „Testfall wiederholen“.
  - Fehler und Störungen lassen sich wieder öffnen und über „Eintrag“ ändern; das Formular zeigt den Eintrag, Status und Daten bleiben (PR 86, 87). Eine Quellregel verbietet `Defect(`/`Incident(` mit `id=` (PR 88).
  - Eine Quellregel verlangt sie überall, wo `messages(` steht.
  - Die Runden eines Laufs stehen nur noch im Statuskasten (nach Erfolg zugeklappt).
  - Markdown-Vorschauen unter Downloads sind entfernt (Quellregel).
  - Jede Tatsache einmal (PR 105):
    - Sagt die Ergebniszeile den einzigen Befund ganz, wiederholt die Liste darunter ihn nicht (`ui.said_in_full`, `messages(said=…)`; Quellregel `test_the_findings_below_a_verdict_leave_out_what_it_says_in_full`).
    - „Jetzt dran“ fehlt auf der Seite, zu der es führt; neben der Prognose (Startseite, Durchführung) nennt es nur die Handlung (`next_step(forecast_shown=True)`).
    - Abschluss: neben der Abnahmetabelle je Art eine Zeile mit höchstens fünf IDs (`check_closing(grouped=True)`). Kontrolle: Aufgaben im Verzug einmal, als Tabelle mit „Hält auf“.
    - Hinweise ohne Handlungsbedarf sind Bildunterschriften, keine farbigen Kästen.
  - Prioritäten sind in jeder Tabelle farbig: Muss rot, Soll gelb, Kann grün (`ui.style_priority`, im Editor ein Punkt über `ui.priority_column`; Quellregel, PR 105).
- **Bedienung** (PR 99, 101):
  - Jedes Speichern antwortet mit einer Meldung, die von selbst verschwindet (`ui.notify`, gezeigt von `ui.show_notice`). Quellregeln: `test_every_save_that_reruns_the_page_says_so`, `test_every_callback_that_saves_says_so`, `test_notices_go_through_one_helper`.
  - Eine freigegebene Phase blendet ihre Freigabe aus, statt sie auszugrauen (Quellregel `test_an_approved_phase_hides_its_approval_instead_of_greying_it_out`).
  - Erledigte Maßnahmen der Kontrolle lassen sich wieder öffnen.
  - Testfälle ohne Ergebnis: die ersten 5, dann „und N weitere“.
  - Planung, Schritt 2 übernimmt Idee und Daten aus dem Projektauftrag. Nach der Übernahme zeigt „Jetzt dran“ den nächsten Schritt, ohne erneut zu fragen.
  - Test springt nach dem Speichern zum nächsten offenen Fall (`ui.next_open`); ein fehlgeschlagener Fall ist zum Erfassen eines Fehlers vorgewählt.
  - Abschluss wählt „abgenommen“ nur vor, wenn die Nachweise „abnehmbar“ sagen; ändern sie sich, fällt die Vorwahl weg. Nach dem Speichern geht es zur nächsten offenen Anforderung.
  - Die Startseite hat einen Hauptknopf.
- **Bewegung** (PR 102):
  - Eine Kurve und fünf Dauern in `:root` von `assets/style.css`: `--ease` `cubic-bezier(0.22, 1, 0.36, 1)`, `--press` 70 ms, `--hover` 140 ms, `--state` 200 ms, `--enter` 260 ms, `--page` 320 ms.
  - Ein Seitenwechsel blendet von 4 px unterhalb ein; ein neuer Lauf nach einem Klick bewegt nichts erneut.
  - Gedrückt schrumpft ein Knopf auf 0,98; unter dem Zeiger hebt er sich um 1 px, eine Karte um 2 px.
  - Das Diagramm der Startseite läuft einmal ab. Zahlen haben gleich breite Ziffern.
  - Mit „Bewegung reduzieren“ bleiben nur Überblendungen.
  - Quellregeln: `test_motion_uses_one_set_of_durations`, `test_motion_moves_nothing_that_reflows_the_page`, `test_reduced_motion_stops_everything_that_travels`.
  - Gemessen in Chrome headless bei 1440 px und 375 px: Median 7 ms je Bild auf langen Seiten, 13 Seiten ohne waagrechtes Scrollen.
- **Modell.**
  - Die Agenten rufen die OpenAI Responses API auf (eigene Schleife in `agent._run`, Werkzeuge als `tools.Tool`, Reasoning `medium`).
  - Findet ein Agent in 10 Runden kein annehmbares Ergebnis, nennt die Meldung den letzten Ablehnungsgrund („Zuletzt abgelehnt: …“, PR 98).
  - Die Oberfläche sagt „der Agent“, Kommentare und Docstrings „the agent“ (je eine Quellregel).
  - Freitexte der Agenten haben Längengrenzen: `tools.LIMITS`, etwa ein Satz, die Zusammenfassung 400 Zeichen. Jedes Einreichungswerkzeug schickt zu Langes zurück (`tools.too_long`); die Modelle nehmen längere Texte weiter an.
  - Eingaben der Agenten vor und nach dem Plan schreiben Daten und Zahlen deutsch (`tracking.as_shown`, `key_figures`; Quellregel). Der Planungsagent behält ISO-Daten für `set_absence`.
  - Liegt die Prognose hinter der Deadline, muss die Zusammenfassung der Durchführung ihr Enddatum nennen (`followup.check_summary`, PR 86).
  - Nach `set_absence` weist `submit_plan` einen Plan zurück, den die Abwesenheit hinter die Deadline schiebt (`PlanningTools._late_by_absence`, Entscheidung der Projektleitung 23.11.2026); ist er auch ohne sie zu spät oder fehlen dem ganzen Team bis zur Deadline die Stunden (`planning.missing_hours`, Entscheidung D1 vom 25.11.2026), bleibt es eine Warnung. Diese nennt dann die Stunden und das früheste mögliche Ende. Kein Puffer und fehlende Skills bleiben Warnungen. `replanning.md` verlangt die Umverteilung (PR 86).
  - `suggested_wishes` schlägt vor, eine kritische Aufgabe vor eine unkritische derselben Person zu ziehen, wenn das den Plan verkürzt, und nennt die Aufgabe, die dabei tatsächlich nach hinten rückt (PR 86, 88).
- **Echte Läufe am 21.11.2026** (Endpunkt der Hochschule, `gpt-6-sol`):
  - Alle elf Agenten und das KI-Lab je einmal ohne Fehler, Auswertung in `03-Experiment/agentenlauf-2026-11-21/`.
  - Mit den Grenzen lag kein Freitext darüber, und keiner ging wegen Länge zurück; die Texte sind 26 % kürzer als am 20.11.
  - Danach Durchführung und Testplan nach der Datumskorrektur: keine ISO-Daten oder Dezimalpunkte mehr.
  - `data/` blieb jeweils unberührt.
- **Echter Lauf am 23.11.2026** (`03-Experiment/agentenlauf-2026-11-23/`): Umplanung bei Abwesenheit und Durchführung je dreimal, Eingaben vom 21.11.
  - Die Zusammenfassung nennt das Enddatum der Prognose in 3 von 3 Läufen, ohne Ablehnung.
  - Die Umplanung verteilt in 2 von 3 Läufen um (zwei Aufgaben von Clara an Anna und Ben). Das Ende liegt dann genau auf der Deadline, ohne Puffer, und Anna und Ben fehlen verlangte Fähigkeiten. Ein Lauf verteilt nichts um (Ende 24.12.2026).
  - `data/` blieb unberührt.
- **KI-Lab.**
  - Liest `OPENAI_BASE_URL`, das Modell aus `PM_MODEL` oder ersatzweise `PM_AGENT_MODEL`, Reasoning `PM_LAB_REASONING_EFFORT`.
  - Der Freeze verlangt Key und Modellnamen, kein Datum (Entscheidung E01). Die Auswertung nennt die antwortenden Modelle (`models_returned`, `model_varies`).
  - Issue #9 ist geschlossen, Nachweis in `04-Prototyp/ki_lab/VERIFIKATION.md`.
  - Formale Fälle aus einer privaten Datei (#6): `PM_LAB_MATERIALS` oder `--materials`, gleiches Format wie `cases.json`, Prüfung beim Laden; der Freeze hält Version, Prüfsumme und Quelle (`öffentlich`/`privat`) fest. Die Fälle selbst schreibt die Gruppe.
  - In KI-Runden zeigt das Lab „X / 12 genutzt“, die freien Anfragen und die Wartezeit in Sekunden (PR 86); die Grenze 12 steht im Server (`lab.py`).
  - Einwilligungen nennen den Dienst, an den die Daten gehen: `ui.ai_service` (Host aus `OPENAI_BASE_URL`) auf den Seiten, der eingefrorene Endpunkt im Lab; eine Quellregel verbietet „an (die) OpenAI (API)“.
- **Prüfen.**
  - `04-Prototyp/pm_agent/docs/pruefplan.md`: Prüfplan für einen Testlauf durch einen Coding-Agenten (statisch, Unit, Integration, Smoke im Browser, Datenvergleich). Codex lief ihn am 22.11.2026 auf `701337c`: alles grün, eine Lücke (keine Kette über alle Phasen). Am 25.11.2026 auf `902ba58`: Schritte 1–7 grün, Schritt 8 (Datenvergleich) rot, weil die Testsuite `data/team.json` schrieb; behoben in PR 105.
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

## Projekt in Zahlen (25.11.2026, `main` nach PR 105)

- **Repository:** 389 Commits auf `main` (287 ohne Merges) seit dem 28.10.2026, 93 gemergte PRs, **0 Releases, 0 Tags**.
- **Fachcode:** rund 10 600 Zeilen Python (ohne Leerzeilen, Kommentare und Tests).
  - `pm_agent` rund 9 980 (Paket und Seiten)
  - `ki_lab` 658
  - dazu 9 Prompts, 8 Vorlagen, CSS
- **Tests:** 752, alle ohne Netz (707 `pm_agent`, 45 `ki_lab`); dazu ein Live-Test, der sich ohne Schlüssel überspringt, und drei Browser-Tests (`tests/test_browsers.py`), die ohne `PM_BROWSERS` überspringen.
- **CI:**
  - `pm-agent.yml`: Lint, Tests; Job `browsers`: jede Seite in Chromium, Firefox und WebKit bei 1440 px und 375 px, auf einem leeren Temp-Ordner über `smoke_app.py`.
  - `static.yml`: README als Pages, in zwei Jobs `build` und `deploy` (PR 100). In einem Job fand `deploy-pages` das Artefakt zu früh („Found 0 artifact(s)“), vier Veröffentlichungen in Folge scheiterten beim ersten Versuch; seitdem gelingt der erste.
- **Betrieb:** läuft lokal als Streamlit-Seite. Das Menü in 8 Einträgen ist in Chrome geprüft (1440 px und 375 px), am 22.11. auch in Edge (Codex, 13 Seiten bei 375 px ohne waagrechtes Scrollen); Firefox und WebKit seit dem 23.11. im CI-Job `browsers`. Kein öffentlicher Betrieb.
- **Issues:** 11 (#1–#11, Meilensteine M1–M4).
  - #9 geschlossen.
  - #2–#5, #7 und #11 haben Entwürfe und einen Kommentar dazu.
  - #1, #6, #8 und #10 liegen bei der Gruppe.
  - Keines ist zugewiesen.

## Offen, nach Wirkung geordnet

1. **Die Forschungsarbeit liegt bei der Gruppe.**
   - Ausgangspunkt ist `01-Projektplanung/agenda-entscheidungen.md`: alle offenen Entscheidungen in der Reihenfolge, in der sie voneinander abhängen.
   - Entwürfe prüfen und beschließen (#2–#5, #7, #11); die fünf schweren Fehler in `02-Recherche/baseline.md` (Abschnitt 5) und `03-Experiment/bewertungsrubrik.md` sind abgeglichen, der optionale Interviewleitfaden (#4) und die Einzelkriterien-Auswertung O5 in `analysis.py` ergänzt.
   - Dann folgen, in dieser Reihenfolge:
     - Rollen und Termine (#1)
     - private formale Fälle (#6)
     - Piloten und Rater (#7)
     - Teilnehmende (#8)
     - Erhebung (#10)
     - Bericht (#11)
   - Daten zur Frage des Projekts gibt es noch nicht.
2. **Teilnahmeinformation fertig machen (#8).** Die Einwilligungen nennen seit PR 77 den richtigen Dienst, und das Lab fragt die freiwillige Einwilligung zu anonymen Zitaten (`quote_consent`) vor dem Start mit ab. In `03-Experiment/teilnahmeinformation.md` fehlen noch Kontakt, Löschdatum und Name des Dienstes (Agenda M2).
3. **Mehrere Läufe je Agent.** Ein Lauf je Agent und Tag reicht nicht für Aussagen über Runden, Token oder Dauer. Am 23.11. liefen zwei Agenten je dreimal; die übrigen einmal. `03-Experiment/agentenlauf-2026-11-21/run_agents.py` wiederholt den ganzen Lauf (kostet Kontingent, nur auf Wort der Projektleitung).
4. **Agenten fachlich.**
   - Umplanung bei Abwesenheit: Am 23.11. verteilte sie in 1 von 3 Läufen nichts um. Seitdem weist `submit_plan` einen solchen Plan zurück; ein echter Lauf damit steht aus (kostet Kontingent, nur auf Wort der Projektleitung). Fehlen dem ganzen Team die Stunden, nimmt `submit_plan` den späten Plan an (D1). Hängt die Verspätung nur an Abhängigkeiten, obwohl die Stunden reichen, kann der Lauf weiter ohne Plan enden; die Meldung nennt dann den Grund (PR 98).
5. **Einen Stand festhalten.** Es gibt kein Release. Ein `v0.1` mit „was geht, mit welchem Modell geprüft“ (öffentlich: nur auf Wort der Projektleitung).
6. **Issues pflegen.** Zuständige eintragen; die Meilenstein-Issues in Aufgaben für einen Tag zerlegen.
7. **Code und Oberfläche, nicht dringend.**
   - `views/planung.py` (rund 1 200 Zeilen) teilen, wenn dort wieder gearbeitet wird.
   - Kein dunkles Design: Das Thema steht auf `base = "light"`, auch bei dunkler Systemeinstellung.
   - Was verschwindet, verschwindet ohne Bewegung: Streamlit gibt CSS dafür keinen Anlass.
   - Aufklappbereiche bewegen sich mit Streamlits eigener Kurve (500 ms), nicht mit `--ease`.
   - Die Dauern der Bewegung sind nicht mit der Gruppe abgestimmt.
   - Die Screenshots in der README zeigen noch die Kontrolle vor PR 105, ohne Reiter.
8. **Betrieb im Netz.** Plan in `04-Prototyp/pm_agent/docs/betrieb-cloud.md`, Weg A (Streamlit-Container, Supabase). Vorher klären, Antwort steht aus:
   - Darf der KI:connect-Schlüssel auf einem Server für die Gruppe genutzt werden, und ist die API von außerhalb des Hochschulnetzes erreichbar? Ansprechpartner: KI:connect-Verantwortliche der HSBI, sonst `kiconnect@cls.rwth-aachen.de`.
   - Laut Hilfeseite von KI:connect gelten API-Schlüssel einen Monat, und die Hochschule legt Monatsbudget und parallele Anfragen je Gruppe fest. Ein Server braucht also einen Schlüsselwechsel je Monat.
   - Bis dahin: nur auf dem eigenen Rechner, ohne Anmeldung nicht für andere öffnen.

## Lokaler Stand dieses Rechners

- `data/` enthält ein erfundenes Beispielprojekt (Team Anna, Ben, Clara) mit freigegebenem Projektauftrag, Anforderungen, Entwurf und Testplan aus den Läufen vom 18.11.2026.
  - Bis PR 105 schrieben Tests das Testteam nach `data/team.json` der Worktrees (`quizzical-keller` am 24.11., `project-structure-review` am 25.11.). Beide sind am 25.11. aus dem Hauptordner wiederhergestellt.
- `logs/` enthält die Protokolle der echten Läufe. Nichts davon ist im Repository.
  - mit Claude: 11. bis 18.11.2026
  - mit `gpt-6-sol`: `gpt-6-sol-20261120/`, `lauf-20261121/` (alle Agenten und KI-Lab) `check-20261121/` (Durchführung und Testplan nach der Datumskorrektur) und `lauf-20261123/` (Umplanung bei Abwesenheit und Durchführung je dreimal)
- `origin` zeigt auf `minglu-prime/KI-gestuetztes-Projektmanagement` (das Repository ist umgezogen; die alte Adresse leitet um).
- Im Worktree `project-structure-review-16429a` liegen unversioniert der Testbericht von Codex (`04-Prototyp/pm_agent/docs/test-report.md`, Chinesisch) und zwei Bildschirmfotos. Nicht committen ohne Übersetzung und Wort der Projektleitung.
- Der Hauptordner steht auf dem lokalen Branch `docs/move-status-out-of-claude-md` (Stand PR 85) mit unversionierten Änderungen vom 23.11.: den Stand aus `CLAUDE.md` nach `docs/stand.md` verschieben. Nicht von dieser Arbeit, nicht anfassen; gegenüber `main` veraltet.
- `.claude/` (nicht im Repository): `launch.json` für den Entwicklungsserver und der Skill `sibling-fix` für Fehlerbehebungen. `.claude/` steht zusätzlich in `.git/info/exclude`, weil das Wurzelverzeichnis keine `.gitignore` hat (eine eigene würde mit PR 12 kollidieren).
- Entfernte Branches außer `main`:
  - `feat/polish`: zusammengeführt, bleibt auf Wunsch
  - `feat/pm-experiment-lab`: PR 12, nicht anfassen
  - Alle anderen Branches dieser Arbeit sind gelöscht, zuletzt am 24./25.11. `fix/absence-deadline`, `fix/rounds-out-reason`, `ci/pages-two-jobs`, `fix/ux-answer-every-save`, `fix/ux-system-decides`, `feat/ui-motion`, `feat/absence-capacity` und `feat/ui-calmer-pages`. Der Worktree `quizzical-keller-85d615` (UX-Prüfung und Bewegung) steht ohne Branch auf `5066640`. Die Branches des Teammitglieds (`test/planning-execution-control-flow`, PR 86, PR 88) sind am 23.11. nicht mehr auf `origin`; gelöscht hat sie nicht diese Arbeit.
