# KI-Lab

Lokaler Studienserver für den kontrollierten Vergleich: zwei Planungsfälle, einer ohne und einer
mit KI-Hilfe, je 25 Minuten, mit Protokoll und Auswertung. Der Code stammt aus Pull Request 12
(`feat/pm-experiment-lab`) und braucht nur die Python-Standardbibliothek (Python 3.11+).

## Starten

Über die Website: Seite **KI-Lab** in `../pm_agent` öffnen und „KI-Lab starten“ wählen.

Einzeln:

```bash
cd 04-Prototyp/ki_lab
python server.py
```

Dann `http://127.0.0.1:8874` öffnen. Der Server ist nur auf dem eigenen Rechner erreichbar.

- `--port`, `--db`: Port und Datenbankdatei.
- `--allow-frame http://localhost:8501`: diese lokale Seite darf das Lab einbetten. Ohne die
  Option ist Einbetten verboten. Erlaubt sind nur `http://localhost:<Port>` und
  `http://127.0.0.1:<Port>`.

Für KI-Runden `OPENAI_API_KEY` und `PM_MODEL` setzen (ersatzweise gilt `PM_AGENT_MODEL`). Ein
anderer OpenAI-kompatibler Dienst steht in `OPENAI_BASE_URL`, das Reasoning (Standard `medium`) in
`PM_LAB_REASONING_EFFORT`. Ohne Schlüssel und Modell funktionieren die Runden ohne KI;
KI-Runden melden einen protokollierten Fehler, es gibt keine Demo-Antworten. Der Freeze für die
formale Studie verlangt Key und Modell und hält den Modellnamen fest; ein datierter Snapshot ist
nicht nötig (Studienregel vom 21.11.2026, `01-Projektplanung/entscheidungen.md`). Jeder Aufruf
speichert das Modell, das geantwortet hat; die Auswertung nennt sie (`models_returned`).

Die formalen Fälle (Issue #6) gehören nicht ins öffentliche Repository. Das Lab liest sie aus
einer privaten Datei im selben Format wie `cases.json` (Fälle A und B, Übung, Version):
`PM_LAB_MATERIALS=private/formal.json` oder `--materials` bei `server.py` und `manage.py`. Ohne
Angabe gelten die öffentlichen Demofälle. `private/` ist per `.gitignore` ausgeschlossen. Fehlt die
Datei oder fehlt ihr ein Feld, startet das Lab nicht und nennt den Grund. Der Freeze hält Version,
Prüfsumme und Quelle (`öffentlich`/`privat`) fest, nicht den Pfad.

Studienleitung (Einladungen, Export, Auswertung): `python manage.py --help`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Was darüber hinaus im Browser geprüft ist und was vor dem Formalstart noch fehlt, steht in
[VERIFIKATION.md](VERIFIKATION.md).

## Daten

Sitzungen und Antworten liegen in `data/lab.db`, Exporte in `private/`. Beides ist per
`.gitignore` ausgeschlossen und gehört nicht ins öffentliche Repository.
