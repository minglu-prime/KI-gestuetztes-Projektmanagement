# KI-Lab: Prüfprotokoll vor dem Formalstart

Prüfung des lokalen Studienservers im Browser, zu Issue #9. Erste Prüfung am 15.11.2026 ohne
API-Key, Nachtrag am 21.11.2026 mit dem echten Anbieter (Abschnitt „Nachtrag 21.11.2026“). **Stand:
die Kriterien von #9 sind erfüllt**; was nur durch Unit-Tests belegt ist, steht im Nachtrag.

- Datum: 15.11.2026
- Code: `04-Prototyp/ki_lab` auf `main` (`dea3f54`; `lab.py`, `server.py` und `web/` zuletzt
  geändert mit `537b5b1`)
- Umgebung: Windows 11, Python 3.11, Chromium-Browser, Server auf `localhost`
- Datenbank: eine eigene Datei in einem temporären Ordner, nicht `data/lab.db`
- `OPENAI_API_KEY` und `PM_MODEL`: nicht gesetzt (`ai_configured: false`)
- Sitzungen: zwei Pilot-Sitzungen, Ablauf 1 (ohne KI Fall A, dann mit KI Fall B)

Wo unten „im Browser“ steht, wurde die Seite bedient. Wo „direkt“ steht, ging eine Anfrage mit
dem Token der Sitzung an die Schnittstelle, an der Seite vorbei.

## Ergebnis je Abnahmekriterium

| Kriterium aus Issue #9 | Ergebnis |
|---|---|
| Zustimmung/Übung → Plan sperren → Risiken → Abgabe → zweite Runde → Reflexion/Download im Browser durchlaufen | erfüllt; der Download-Knopf selbst wurde nicht gedrückt, geprüft ist die Antwort von `/api/export`, die er speichert |
| Refresh, Timeout, verspätete Antworten und Anfragekontext geprüft | Refresh, Timeout und Anfragekontext erfüllt; eine verspätete KI-Antwort ist nur durch den Unit-Test belegt |
| Manualmodus kann serverseitig kein KI-Modell aufrufen | erfüllt |
| Echter Provider-Erfolg mit gewähltem Snapshot sowie Fehlerpfad dokumentiert | erfüllt am 21.11.2026: Erfolg mit `gpt-6-sol`, Fehlerpfade „kein Key“, „falscher Key“ und „unbekanntes Modell“. Statt eines datierten Snapshots gilt seit 21.11.2026 die Studienregel aus `01-Projektplanung/entscheidungen.md` (E01) |
| Erstentwurf, Dialog, finaler Text, Modell und Zeitstempel vollständig | erfüllt am 21.11.2026: Erstentwurf, Frage und Antwort, angefragtes und gemeldetes Modell, Token und Zeitstempel im Protokoll und im Export |
| Raterpakete ohne Bedingungs-/Identitätszuordnung | erfüllt |

## Was geprüft wurde

### Ablauf im Browser

1. Start ohne Einwilligung: abgelehnt mit „Einwilligung vor Beginn erforderlich.“
2. Runde 1 (ohne KI): Entwurf geschrieben, Seite neu geladen. Der Entwurf (283 Zeichen) ist
   wieder da, die Uhr läuft weiter (24:32 → 24:29), das Feld für Risiken ist noch gesperrt.
3. Basisplan sperren: Die Seite fragt nach („Basisplan endgültig sperren und Änderungen öffnen?
   Die Zeit läuft weiter.“). Erst danach erscheinen Änderung und Referenzplan, das Planfeld ist
   gesperrt, das Ereignis `plan_locked` steht im Protokoll.
4. Abgabe: Die Seite fragt nach („Runde endgültig abgeben? Danach können Sie die Antworten nicht
   mehr ändern.“). Die Runde hat danach den Status `submitted` und einen finalen Text.
5. Pausenseite mit „Zweite Runde starten“ und „Bisherige Ergebnisse herunterladen“.
6. Runde 2 (mit KI) ebenso bis zur Abgabe, dann Reflexion: fünf Antworten gespeichert
   („Reflexion gespeichert.“), nach dem Neuladen wieder da.

Die Browser-Konsole zeigte keine Skriptfehler, nur die absichtlich ausgelösten Ablehnungen.

### Was der Server ablehnt (direkt)

| Anfrage | Antwort |
|---|---|
| KI-Frage in der Runde ohne KI | 403 „KI ist in der manuellen Bedingung nicht erlaubt.“ |
| Anfrage ohne Token | 401 |
| Anfrage ohne `_context` | 400 |
| Anfrage mit `_context` einer früheren Stufe | 409 |
| Risiken speichern, bevor der Plan gesperrt ist | 409 |
| Plan ändern oder erneut sperren nach dem Sperren | 409 |
| Schreiben nach der Abgabe | 409 |
| Reflexion, bevor beide Runden beendet sind | 409 |
| Speichern oder KI-Frage nach Ablauf der Zeit | 409 „Keine aktive Runde. Beendete Runden sind schreibgeschützt.“ |

Die Ablehnung der KI-Frage in der Runde ohne KI steht im Code vor jedem Aufruf des Anbieters
(`Lab.ask` in `lab.py`).

### KI-Runde ohne Key

Frage im Browser gestellt. Die Seite zeigt „KI nicht konfiguriert. Studienleitung muss API-Key und
Modell setzen.“ und keine Antwort. Im Protokoll steht der Aufruf mit Status `error`, der Frage,
der vollständigen Eingabe an das Modell (Prompt, Fallmaterial, aktueller Entwurf), Beginn und Ende,
`answer: null`. `first_ai_draft` bleibt `null`.

### Ablauf der Zeit

Dafür lief der Server mit 45 Sekunden je Runde statt 25 Minuten. Die Zahl wurde beim Start im
Speicher gesetzt (`lab.LIMIT`); am Code im Repository ist nichts geändert.

- Text, der fünf Sekunden vor Ablauf getippt wurde, steht im finalen Stand (die Seite speichert
  0,7 Sekunden nach der letzten Eingabe).
- Bei 00:00 wechselt die Seite von selbst zur Pause: „Die Zeit ist abgelaufen. Der letzte
  rechtzeitig gespeicherte Stand wurde als unvollständiges Ergebnis …“
- Die Runde hat den Status `timed_out`, die Dauer ist genau das Limit, das Ereignis heißt
  `deadline`, der finale Text ist der letzte gespeicherte Entwurf.
- Auch eine Runde ganz ohne Eingabe läuft so ab. Die Abschlussseite zeigt für beide Runden
  „Zeitlimit · unvollständig“.

### Export

Eigene Aufzeichnung (`/api/export`): Kennung, Gruppe, Pilot-Kennzeichen, Einwilligungszeit,
Erfahrung, Konfiguration (Prüfsummen von Material und Prompt, Limit, Protokollversion), je Runde
Fall, Bedingung, Status, Beginn, Sperrzeitpunkt, Ende, Entwurf, finaler Text, Zwischenstände mit
Zeit und alle KI-Aufrufe; dazu Ereignisse und Reflexion. Das Token der Sitzung steht nicht darin.

Studienleitung (`manage.py export`):

- `R1/answers.json` und `R2/answers.json` enthalten je Antwort nur `rating_id`, `case_id`, Plan
  und Risiken. Kennung, Gruppe, Bedingung und der Fehlertext der KI kommen darin nicht vor.
- Die Reihenfolge folgt der zufälligen `rating_id`. Welche zwei Antworten zu einer Person
  gehören, ist daran nicht zu sehen.
- Die Zuordnung steht nur in `private/key.json`.
- Ohne `--include-pilots` sind Pilot-Sitzungen ausgeschlossen (0 Ergebnisse).

### Automatische Tests

`python -m unittest discover -s tests`: 27 Tests bestanden. `node --check web/app.js`: ohne Befund.
Nur durch diese Tests belegt, nicht im Browser gesehen:

- eine KI-Antwort, die nach dem Ende der Runde eintrifft (`late`, bleibt im Protokoll, wird nicht
  in die nächste Runde übernommen),
- ein erfolgreicher KI-Aufruf mit Erstentwurf und Modellangaben (mit einem Testsender, nicht mit
  dem Anbieter),
- die Abläufe 2 bis 4,
- formale Sitzungen (`freeze`, `enroll`) und die Prüfung auf ein geändertes Modell.

## Beobachtung

Die Startseite und die Pausenseite nennen „25 Minuten“ als festen Text; sie lesen das Limit nicht
vom Server. Solange das Limit im Code 25 Minuten bleibt, stimmt beides überein.

## Nachtrag 21.11.2026: echter Anbieter

- Code: Branch `feat/lab-model-rule` auf `main` `346c9cb` (Freeze ohne datierten Snapshot,
  `models_returned` in der Auswertung).
- Anbieter: OpenAI-kompatibler Endpunkt der Hochschule (`OPENAI_BASE_URL`), Modell `gpt-6-sol`,
  Reasoning `medium`. Key und Adresse stehen nur in der lokalen `.env`.
- Datenbanken: eigene Dateien in einem temporären Ordner, nicht `data/lab.db`. Nur Pilot- und
  Testsitzungen, keine Teilnehmenden.

### KI-Runde im Browser

Pilot-Sitzung, Ablauf 1. Runde 1 (ohne KI) wurde direkt über die Schnittstelle abgegeben, Runde 2
(mit KI) im Browser bedient: Basisplan getippt, Frage „Prüfe meinen Plan auf Abhängigkeiten und
Ressourcenkonflikte.“ gestellt.

- Die Antwort (1 304 Zeichen) erscheint auf der Seite.
- Protokoll: Status `completed`, angefragtes und gemeldetes Modell `gpt-6-sol`, `first_ai_draft`
  gefüllt, Beginn und Ende gesetzt.
- `/api/export` enthält Frage, Antwort und Modell.

Zusätzlich direkt (ohne Browser): Status `completed` nach 4,4 s, 962 Eingabe- und 276
Ausgabe-Token, die Eingabe an das Modell aus Prompt, Fallmaterial und aktuellem Entwurf (3
Nachrichten).

### Fehlerpfade des Anbieters

| Fall | Meldung | Protokoll |
|---|---|---|
| Kein Key (15.11.2026) | „KI nicht konfiguriert …“ | `error`, keine Antwort |
| Falscher Key | „KI-Anbieter meldet HTTP 401. Keine Antwort erzeugt.“ | `error`, `answer: null` |
| Unbekanntes Modell | „KI-Anbieter meldet HTTP 404. Keine Antwort erzeugt.“ | `error`, `answer: null`, `first_ai_draft: null` |

Keine Ersatzantwort in einem der Fälle.

### Formale Kette

Mit Key und `gpt-6-sol` in einer Testdatenbank: `manage.py freeze` (nimmt das Modell ohne Datum an
und hält es in der Konfiguration fest), `enroll --count 4`, `export` (R1, R2, `private/`),
`analyze` (4 formale Teilnehmende, 0 Paare, `models_returned: []`). Keine Sitzung wurde
bearbeitet; die Kette zeigt nur, dass jeder Schritt mit der neuen Regel läuft.

### Automatische Tests

`python -m unittest discover -s tests`: 39 Tests bestanden. Neu: Freeze mit einem Modellnamen ohne
Datum; ein geändertes Modell sperrt weiterhin formale Sitzungen; Freeze ohne Key oder Modell wird
abgelehnt; `models_returned` und `model_varies` in der Auswertung.

### Nur durch Unit-Tests belegt

- Eine KI-Antwort, die erst nach Ablauf der Runde eintrifft (`late`): Im Browser lässt sie sich
  nur mit einem künstlich verzögerten Anbieter auslösen.
- Eine Zeitüberschreitung des Anbieters (60 s): Der Code meldet sie als
  „KI-Verbindung fehlgeschlagen …“ (`call_model`); der echte Endpunkt antwortete in jedem Versuch.

### Nicht geprüft

- Der Download-Knopf selbst; geprüft ist `/api/export`, das er speichert.

Die Inhalte dieser Läufe gingen an den Anbieter; es waren nur das Fallmaterial der Pilotfassung und
Testtexte.
