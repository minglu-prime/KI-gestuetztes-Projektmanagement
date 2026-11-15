# KI-Lab: Prüfprotokoll vor dem Formalstart

Prüfung des lokalen Studienservers im Browser, zu Issue #9. **Stand: unvollständig.** Der Ablauf
ohne KI, die Fehlerpfade und der Export sind geprüft. Ein erfolgreicher Aufruf des echten
KI-Anbieters ist **nicht** geprüft, weil für diese Prüfung kein API-Key benutzt wurde. Vor dem
Formalstart fehlt deshalb noch der Abschnitt „Offen“ am Ende.

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
| Echter Provider-Erfolg mit gewähltem Snapshot sowie Fehlerpfad dokumentiert | **Erfolg offen**; Fehlerpfad „kein Key“ erfüllt |
| Erstentwurf, Dialog, finaler Text, Modell und Zeitstempel vollständig | teilweise: finaler Text, Zwischenstände, Zeitstempel und Ereignisse vollständig; Erstentwurf der KI und Modell sind leer, weil kein Aufruf gelang |
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

## Offen

Vor dem Formalstart, mit `OPENAI_API_KEY` und dem gewählten Modell in `PM_MODEL`:

- [ ] Eine KI-Runde im Browser mit einer echten Antwort: Antwort erscheint, `first_ai_draft` ist
      gefüllt, im Protokoll stehen das angefragte und das vom Anbieter gemeldete Modell.
- [ ] Fehlerpfade des Anbieters: falscher Key, unbekanntes Modell, Zeitüberschreitung. Jeweils
      Meldung auf der Seite und Eintrag im Protokoll, keine Ersatzantwort.
- [ ] Eine KI-Antwort, die erst nach Ablauf der Runde eintrifft, im Browser.
- [ ] Der Download-Knopf: Die gespeicherte Datei entspricht `/api/export`.
- [ ] Eine formale Sitzung von `freeze` über `enroll` bis `export` und `analyze`.

Die Inhalte dieser Läufe gehen an den Anbieter. Deshalb nur mit Fallmaterial und Texten, die dafür
gedacht sind.
