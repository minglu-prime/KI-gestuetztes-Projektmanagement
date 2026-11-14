# PM-Agent

Website der Projektgruppe 4 zum Thema „KI im Projektmanagement“. Kern ist ein KI-Agent für die
Planungsphase von Softwareprojekten: Aufgaben zerlegen, Aufwand schätzen, nach Skills und
Verfügbarkeit zuweisen, Terminplan und Risiken ableiten. Die Projektleitung prüft und
entscheidet.

Stand: Planung mit Claude und deterministischer Prüfung; für Durchführung und Kontrolle steht
je ein Agent als Gerüst (ein Werkzeug, eine Prüfung), bisher nur offline getestet; das KI-Lab
(Vergleichsexperiment, `../ki_lab`) ist eingebettet.

## Oberfläche

```bash
cd 04-Prototyp/pm_agent
uv run --env-file .env streamlit run app.py
```

Die Oberfläche ist nur auf diesem Rechner erreichbar (`http://localhost:8501`), siehe
`.streamlit/config.toml`. Sonst könnte jeder im selben Netz Planungen auf Kosten des
API-Schlüssels starten. Deshalb im Ordner `04-Prototyp/pm_agent` starten.

Das Menü links:

| Seite | Inhalt |
|---|---|
| Startseite | Überblick und Stand des übernommenen Projekts |
| Agenten · Planung | Plan mit Claude erstellen, prüfen, anpassen, exportieren, als Projekt übernehmen |
| Agenten · Durchführung | Status und Ist-Stunden je Aufgabe erfassen; Claude schlägt Zusammenfassung und nächste Schritte vor; Statusbericht und Arbeitspaketbeschreibungen aus Vorlagen (`src/pm_agent/templates`) |
| Agenten · Kontrolle | Plan/Ist-Vergleich, Verzug, Kosten bei gesetztem Stundensatz; Claude bewertet den Stand und schlägt Gegenmaßnahmen vor; Zeit und Token aller Agentenläufe |
| KI-Lab | startet den Studienserver aus `../ki_lab` und zeigt ihn eingebettet |
| Über uns, Impressum | Projektkontext; Impressumsangaben trägt das Team noch ein |

Durchführung und Kontrolle rechnen mit dem übernommenen Plan (`data/projekt.json`) und dem
erfassten Fortschritt. Ein Logo erscheint oben rechts, sobald `assets/logo.svg` oder
`assets/logo.png` existiert.

Für KI-Runden im KI-Lab zusätzlich `OPENAI_API_KEY` und `PM_MODEL` in `.env` eintragen. Ohne
sie funktionieren die Runden ohne KI, KI-Runden melden einen Fehler.

### Seite Planung

Sechs Schritte als Reiter:

1. **Team**: Personen mit Skills (z. B. `Python 4, SQL 3`) und Wochenstunden; lokal speichern
   in `data/team.json`. Ohne Zustimmung des Teams startet keine Planung.
2. **Projekt**: Idee, Start, Deadline.
3. **Planung**: Claude plant, jede Runde erscheint sofort. Alternativ einen protokollierten Lauf
   aus `logs/` öffnen, ohne Claude erneut aufzurufen (z. B. für Vorführungen).
4. **Ergebnis**: Planende, Fehler, Warnungen, Gantt-Diagramm, Auslastung, Begründungen, Risiken.
5. **Anpassen**: Tabelle ändern und erneut prüfen; nur die deterministische Prüfung, kein LLM.
6. **Export**: Markdown oder CSV. Jeder Export wird mit Dauer und Änderungen in `logs/runs.csv`
   vermerkt, als Datengrundlage für den Vorher-nachher-Vergleich. Ein Plan ohne Fehler lässt
   sich hier als Projekt übernehmen.

## Agenten

Alle drei Agenten laufen in derselben Schleife (`run_agent` in `src/pm_agent/agent.py`): Claude
entwirft ein Ergebnis, ein Werkzeug prüft es deterministisch, Claude korrigiert, bis das
Einreichen-Werkzeug es annimmt. Liegt nach 10 Runden kein gültiges Ergebnis vor, hört Claude
ohne Ergebnis auf oder wird eine Antwort abgeschnitten oder abgelehnt, bricht der Agent mit
einer `AgentError` ab. Jeder Lauf wird in `logs/` protokolliert.

| Agent | Aufruf | Werkzeuge | Die Prüfung verlangt |
|---|---|---|---|
| Planung | `run_planning(project, team)` | `check_plan`, `submit_plan` | einen Plan ohne Fehler; Warnungen (Überlastung, Deadline, fehlende Skills) bleiben für die Projektleitung stehen |
| Durchführung | `run_status_summary(tracking, today)` in `followup.py` | `submit_status` | einen nächsten Schritt für jede Aufgabe im Verzug, keinen für fertige Aufgaben |
| Kontrolle | `run_control_report(tracking, today)` in `followup.py` | `submit_control` | eine Gegenmaßnahme für jede Aufgabe im Verzug; bei Verzug nicht die Bewertung „im Plan“ |

Die Agenten für Durchführung und Kontrolle bekommen die fertig berechneten Kennzahlen und
rechnen nicht selbst. Sie sind ein Gerüst: Weitere Werkzeuge (zum Beispiel eine
Umplanung zum Durchrechnen) kommen in `followup.py` neben das Einreichen-Werkzeug. Gegen die
echte API sind beide noch nicht gelaufen.

Zugang: `.env.example` nach `.env` kopieren und `ANTHROPIC_API_KEY` eintragen. Das Modell
lässt sich mit `PM_AGENT_MODEL` ändern (Standard `claude-opus-5-5`).

## Entwicklung

Voraussetzung: [uv](https://docs.astral.sh/uv/).

```bash
cd 04-Prototyp/pm_agent
uv sync
uv run ruff check .
uv run pytest
```

Der Test gegen die echte API kostet Geld und dauert einige Minuten. Ohne `ANTHROPIC_API_KEY`
wird er übersprungen. Mit dem Key aus `.env`:

```bash
uv run --env-file .env pytest tests/test_agent_live.py
```

## Datenschutz

Das Repository ist öffentlich. Teamdaten (`data/`), Protokolle (`logs/`) und `.env` bleiben
lokal und sind per `.gitignore` ausgeschlossen.

Der Agent schickt Projektidee und Teamdaten (Namen, Skills, Wochenstunden, Notizen) an die
Anthropic API. Teammitglieder müssen vorher zustimmen.

Das KI-Lab speichert Sitzungen in `../ki_lab/data/` (ebenfalls ausgeschlossen) und schickt in
KI-Runden Fallmaterial, Entwurf und Frage an OpenAI.
