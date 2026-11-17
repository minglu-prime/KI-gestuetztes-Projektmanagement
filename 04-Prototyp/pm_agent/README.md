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
| Startseite | Überblick, Stand des übernommenen Projekts und Prognose seines Endes |
| Vorbereiten · Projektauftrag | Idee und Termine eintragen; Claude entwirft Ziel, Nutzen, Umfang, Beteiligte (als Rollen), Erfolgskriterien und Rahmenbedingungen; Python prüft; die Projektleitung ändert und gibt frei; als Markdown herunterladen |
| Vorbereiten · Anforderungen | Claude entwirft User Stories mit Priorität (Muss, Soll, Kann) und Akzeptanzkriterien aus dem Projektauftrag; Python prüft, dass jedes Erfolgskriterium eine Anforderung hat; Bearbeiten in einer Tabelle, Freigabe, Markdown |
| Vorbereiten · Entwurf | Claude entwirft Bausteine (Rollen, Komponenten, Fremdsysteme), Schnittstellen mit typisierten Feldern und Fehlercodes und die Abläufe zwischen ihnen; Python prüft jeden Schritt gegen seine Schnittstelle und dass jede Muss-Anforderung einen Ablauf hat, und zeichnet daraus die Sequenzdiagramme; vier Tabellen, Freigabe, Markdown mit Mermaid-Diagrammen |
| Vorbereiten · Testplan | Claude entwirft Testfälle aus den Akzeptanzkriterien (feste IDs R1.1 …) und den Schnittstellen; Python prüft, dass jedes Kriterium einer Muss-Anforderung einen Testfall hat, und meldet Schnittstellen und Fehlercodes ohne Test; Freigabe, Markdown |
| Agenten · Planung | Plan mit Claude erstellen, prüfen, anpassen, exportieren, als Projekt übernehmen; je Projektwoche eine Demo, die Python gegen den Zeitplan prüft |
| Agenten · Durchführung | Wer in den nächsten fünf Arbeitstagen womit beginnt (aus der Prognose); Status, Ist-Stunden und geschätzten Rest je Aufgabe erfassen, mit dem voraussichtlichen Ende je Aufgabe; Claude schlägt Zusammenfassung und nächste Schritte vor; Statusbericht und Arbeitspaketbeschreibungen aus Vorlagen (`src/pm_agent/templates`) |
| Agenten · Test | Ergebnisse je Testfall eintragen; jeder fehlgeschlagene Fall braucht einen Fehler (Schwere, Ursache, Aufgabe); ein Fehler öffnet seine Aufgabe auf Knopfdruck wieder |
| Agenten · Kontrolle | Wochen-Demos mit Rückblick (gezeigt?, was ging schief, Ursache, Maßnahme; offene Maßnahmen zum Abhaken); Plan/Ist-Vergleich, Verzug, Prognose des Endes (restliche Arbeit ab heute, mit den Aufgaben, die auf verspätete warten) und von dort der Weg zurück in die Planung: „Rest mit Claude umplanen“ lädt die unfertigen Aufgaben als Plan ab heute; Earned Value nach der 0/100-Methode (Planwert, Fertigstellungswert, Ist-Stunden, SPI, CPI); Kosten bei gesetztem Stundensatz; Claude bewertet den Stand und schlägt Gegenmaßnahmen vor, und wo eine Maßnahme Aufgaben umverteilt, rechnet Python ihre Wirkung auf die Prognose nach; Zeit und Token aller Agentenläufe; alles zusammen als Kontrollbericht aus einer Vorlage |
| KI-Lab | startet den Studienserver aus `../ki_lab` und zeigt ihn eingebettet |
| Über uns, Impressum | Projektkontext; Impressumsangaben trägt das Team noch ein |

Über jeder Seite einer Phase steht der Projektpfad Auftrag → Anforderungen → Entwurf →
Planen → Ausführen → Prüfen: Was erledigt ist, trägt ein Häkchen, die aktuelle Seite ist umrandet. Eine
Phase vor dem Plan, die nicht freigegeben ist (ein Entwurf, seit der Freigabe geändert, oder
übersprungen, obwohl schon ein Projekt läuft), ist gestrichelt und sagt „nicht freigegeben“.
Übersprungen werden darf sie: Die Planung arbeitet dann wie ohne Anforderungen bzw. ohne Entwurf. Mit einem übernommenen Projekt folgt eine
Zeile „Jetzt dran“ mit einem Knopf zur passenden Seite. Jeder Abschnitt nennt, wer dort
handelt: CLAUDE schlägt vor, PYTHON rechnet und prüft, DU trägst ein und entscheidest.

Durchführung und Kontrolle rechnen mit dem übernommenen Plan (`data/projekt.json`) und dem
erfassten Fortschritt. Ein Logo erscheint oben rechts, sobald `assets/logo.svg` oder
`assets/logo.png` existiert.

Farben und Schrift stehen in `.streamlit/config.toml`. Hervorhebung, Karten, Schaltflächen und
Übergänge (Seitenwechsel, Reiter, Hover) stehen in `assets/style.css`; `app.py` lädt die Datei
bei jedem Lauf. Wer im System weniger Bewegung eingestellt hat, bekommt keine Animationen.

Für KI-Runden im KI-Lab zusätzlich `OPENAI_API_KEY` und `PM_MODEL` in `.env` eintragen. Ohne
sie funktionieren die Runden ohne KI, KI-Runden melden einen Fehler.

### Seite Planung

Sechs Schritte als Reiter:

1. **Team**: Personen mit Skills (z. B. `Python 4, SQL 3`), Wochenstunden und Abwesenheiten
   (z. B. `01.12.2026–05.12.2026, 23.12.2026`: an diesen Tagen wird für die Person keine
   Arbeit eingeplant); lokal speichern
   in `data/team.json`. Ohne Zustimmung des Teams startet keine Planung.
2. **Projekt**: Idee, Start, Deadline und, wenn es welche gibt, freie Tage für alle
   (Feiertage, eine Pause), an denen niemand eingeplant wird.
3. **Planung**: Claude plant, jede Runde erscheint sofort. Alternativ einen protokollierten Lauf
   aus `logs/` öffnen, ohne Claude erneut aufzurufen (z. B. für Vorführungen).
4. **Ergebnis**: Planende, Fehler, Warnungen, Gantt-Diagramm, Auslastung, Begründungen, Risiken.
   „Aufgabe im Detail“ erklärt eine Aufgabe: warum diese Person, welche Skills sie dafür hat,
   was vorher fertig sein muss und was darauf wartet, wie viele Arbeitstage Puffer sie hat
   und wer im Team sie sonst übernehmen könnte.
5. **Anpassen**: zwei Wege. Mit Claude: einen Wunsch oder eine Annahme eintippen oder einen
   der Vorschläge anklicken, die Python aus der Prüfung ableitet („Clara
   übernimmt die Tests“, „Was, wenn das Backend doppelt so lange dauert?“); Claude ändert
   den Plan, Python prüft ihn und zeigt die Unterschiede zum bisherigen Plan, erst
   „Übernehmen“ macht ihn gültig. Von Hand: Tabelle ändern und erneut prüfen, ohne LLM.
6. **Export**: Markdown oder CSV. Jeder Export wird mit Dauer und Änderungen in `logs/runs.csv`
   vermerkt, als Datengrundlage für den Vorher-nachher-Vergleich. Die Datei wird nur
   fortgeschrieben, nie umgeschrieben: Passt sie nicht mehr (andere Spalten, von Hand oder
   in einem Tabellenprogramm verändert), wird sie unter `logs/runs-bis-<Zeit>.csv`
   beiseitegelegt, und eine neue beginnt. Ein Plan ohne Fehler lässt sich hier als Projekt
   übernehmen. Hat das bisher übernommene Projekt schon Fortschritt, wählt die Projektleitung:
   verwerfen, oder als frühere Arbeit behalten. Behalten passt zum Rest des Projekts, den die
   Seite Kontrolle mit „Rest mit Claude umplanen“ lädt: Fertige Aufgaben und die gebuchten
   Stunden begonnener Aufgaben bleiben in allen Kennzahlen und Berichten; eine begonnene
   Aufgabe geht im neuen Plan „in Arbeit“ weiter, ihr gebuchter Teil zählt als fertig, sobald
   sie fertig ist. Steht eine fertige Aufgabe wieder im Plan, lehnt das Übernehmen ab: Sie
   würde doppelt zählen.

## Agenten

Alle Agenten laufen in derselben Schleife (`run_agent` in `src/pm_agent/agent.py`): Claude
entwirft ein Ergebnis, ein Werkzeug prüft es deterministisch, Claude korrigiert, bis das
Einreichen-Werkzeug es annimmt. Liegt nach 10 Runden kein gültiges Ergebnis vor, hört Claude
ohne Ergebnis auf oder wird eine Antwort abgeschnitten oder abgelehnt, bricht der Agent mit
einer `AgentError` ab. Jeder Lauf wird in `logs/` protokolliert.

| Agent | Aufruf | Werkzeuge | Die Prüfung verlangt |
|---|---|---|---|
| Planung | `run_planning(project, team)`; für Änderungen `run_replanning(project, team, plan, wish)` | `check_plan`, `submit_plan` | einen Plan ohne Fehler; Warnungen (Überlastung, Deadline, kein Puffer, fehlende Skills) bleiben für die Projektleitung stehen |
| Durchführung | `run_status_summary(tracking, today)` in `followup.py` | `submit_status` | einen nächsten Schritt für jede Aufgabe im Verzug, keinen für fertige Aufgaben |
| Kontrolle | `run_control_report(tracking, today)` in `followup.py` | `submit_control` | eine Gegenmaßnahme für jede Aufgabe im Verzug; bei Verzug nicht die Bewertung „im Plan“ |
| Projektauftrag | `run_charter(project)` in `lifecycle.py` | `submit_auftrag` | eindeutige IDs der Erfolgskriterien |
| Anforderungen | `run_requirements(project, charter)` in `lifecycle.py` | `submit_anforderungen` | jedes Erfolgskriterium abgedeckt, nur bekannte genannt, eindeutige IDs, mindestens eine Muss-Anforderung |
| Entwurf | `run_design(project, charter, requirements)` in `lifecycle.py` | `submit_entwurf` | bekannte Bausteine und Schnittstellen, jeder Schritt passt zum Vertrag, jede Schnittstelle in einem Ablauf, jede Muss-Anforderung mit Ablauf, eindeutige IDs |

Sind Anforderungen freigegeben, ordnet der Planungs-Agent jede Aufgabe ihnen zu
(`requirement_ids`). `check_plan` meldet dann eine unbekannte Anforderung als Fehler und eine
Anforderung ohne Aufgabe oder Aufgaben ohne Anforderung als Warnung. Wie das ganze
Vorgehen von der Idee bis zur nächsten Iteration gedacht ist, beschreibt
[docs/lebenszyklus.md](docs/lebenszyklus.md). Ist ein Entwurf freigegeben, bekommt der
Planungs-Agent dessen Bausteine und Schnittstellen als Grundlage; geprüft wird dagegen nicht.
Die Sequenzdiagramme zeichnet `src/pm_agent/diagram.py`, nie Claude.

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

Das Repository ist öffentlich. Teamdaten (`data/`, auch Projektauftrag, Anforderungen und Entwurf in
`data/vorhaben.json`), Protokolle (`logs/`) und `.env` bleiben lokal und sind per `.gitignore`
ausgeschlossen. Für Projektauftrag, Anforderungen und Entwurf gehen nur Idee, Termine und die
Texte von Auftrag und Anforderungen an die API, keine Angaben zum Team; Beteiligte stehen dort als Rollen.

Der Agent schickt Projektidee und Teamdaten (Namen, Skills, Wochenstunden, Notizen) an die
Anthropic API. Teammitglieder müssen vorher zustimmen.

Das KI-Lab speichert Sitzungen in `../ki_lab/data/` (ebenfalls ausgeschlossen) und schickt in
KI-Runden Fallmaterial, Entwurf und Frage an OpenAI.
