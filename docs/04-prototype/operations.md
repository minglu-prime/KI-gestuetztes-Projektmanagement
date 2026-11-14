# Betrieb, Daten und Auswertung

## Architektur und Start

Python 3.11+, keine pip-Abhängigkeiten. `python server.py` startet http://127.0.0.1:8874. Bei belegtem Port anderen Wert mit `--port` wählen und für Einladungen denselben Wert verwenden. Windows-Portsharing ist absichtlich ausgeschlossen. Nur Loopback, kein öffentliches Hosting und keine Fernzugriffseinrichtung.

Alle Daten liegen standardmäßig in `data/lab.db`. Zum Backup Server beenden und den gesamten Datenordner kopieren (SQLite kann WAL-Dateien verwenden). Daten und Einladungen nicht committen. Serverneustart setzt keine Runde zurück. Zeitlimit läuft auch bei geschlossenem Browser weiter. Das System nutzt Server-Wanduhr; Rechneruhr während einer Erhebung nicht ändern.

## API und Zustandsfluss

- `POST /api/pilot`: Pilot-Sitzung erzeugen, Gruppe 1–4. `pilot:false` aus dem Browser wird nicht übernommen.
- `GET /api/session`: eigene Sitzung, Fallmaterial nur während aktiver Runde.
- `POST /api/start`: Einwilligung/Erfahrung in erster Runde; nächster Start erst nach Abschluss der ersten Runde. Wiederholter Start einer aktiven Runde ändert deren Startzeit nicht.
- `POST /api/save`: Textfelder `plan`, `risks`, je maximal 50.000 Zeichen; Revisionen werden gespeichert.
- `POST /api/submit`: beide Felder nicht leer; Ergebnis anschließend unveränderlich.
- `POST /api/ai`: nur aktive KI-Runde, Frage bis 4.000 Zeichen; keine clientseitig wählbaren Modelle oder Fälle.
- `POST /api/reflect`: Reflexion nach beiden Runden.
- `GET /api/export`: nur eigene Sitzung; Massendaten und Bewertungsantworten ausschließlich über lokale CLI.

Sitzungsschlüssel ist ein zufälliger Bearer-Token im URL-Fragment/Tab-Speicher. Er ist die Zugriffsberechtigung; Einladungen nicht weitergeben. Server liefert nur explizit freigegebene Webdateien, nicht den Projektordner. Cross-Origin-Mutationen und unerwartete Hosts sind gesperrt. Dies ist ein betreuter Forschungsprototyp, keine gehärtete Mehrbenutzerplattform.

## Modell konfigurieren und Freeze

In derselben Shell wie im README den API-Key und `PM_MODEL` setzen. Der Key wird nicht in Sitzungen gespeichert; Modell, Systemprompt, Material-Snapshot, Hashwerte, API-Einstellungen, Input, Modellantwort und Zeitpunkte werden dokumentiert. Das gewählte Modell muss deutsche Aufgaben im Live-Pilot tatsächlich beantworten. Kein automatischer Modellwechsel bei Fehlern.

Erst nach fachlicher und organisatorischer Freigabe:

```powershell
python manage.py freeze --attestation "Teamfreigabe am DATUM: Live-Pilot, Materialprüfung, Rubrik, Datenregeln und Rekrutierungsweg geprüft."
python manage.py enroll --count 12 --seed 20261030
```

Der Beispieltext muss durch eine wahrheitsgemäße Freigabe ersetzt werden. Freeze prüft Key-Präsenz und datierte Modell-ID, **nicht** die tatsächliche fachliche Freigabe oder Erreichbarkeit des Providers. Er sperrt nachfolgende Material-/Prompt-/Modelländerungen für formale Starts. Für Änderungen neue Datenbank mit `--db data/study-v2.db` verwenden. CLI-Option `--db` steht vor dem Unterbefehl, beim Server nach dem Programmnamen.

Enrollment speichert Einladungen in `data/invitations-001.json`; nur die Studienleitung erhält diese Datei. Anonyme IDs P001–P012, blockrandomisierte Sequenzen. Keine E-Mails werden versendet. Für einen zweiten Block `--start 13` wählen. Kontaktliste separat halten. Bei Erfahrungsschichten Zuteilung wie im Protokoll durchführen und dokumentieren.

## Exportieren und bewerten

```powershell
python manage.py export --out data/export-01
```

Standardmäßig nur formale Sitzungen. `--include-pilots` ausschließlich für Test/Training, nicht für formale Analyse verwenden.

- `private/raw.json`: Rohdaten, Versionen, Eingaben, Antworten, Reflexion und Audit.
- `private/key.json`: Zuordnung der Bewertungs-IDs zu Person/Bedingung/Status.
- `R1/answers.json`, `R1/ratings.json`: unabhängiges Paket für Rater 1.
- `R2/answers.json`, `R2/ratings.json`: unabhängiges Paket für Rater 2.

Nur den jeweiligen Rater-Ordner und die Rubrik weitergeben. Keine Rohlogs, Bedingungen oder Kontaktliste. Die Texte können ihren Ursprung verraten; daher keine vollständige Verblindung behaupten. Teilnehmende sollen ihre Bedingung nicht in den Antworttext schreiben. Vor Übergabe auf versehentlich eingetragene personenbezogene Daten prüfen, notwendige redaktionelle Bereinigungen separat dokumentieren.

Bewertende füllen alle sechs Rubrikwerte plus `severe_errors` und Begründungen aus. Originaldateien getrennt aufbewahren. Für Analyse beide Listen in eine JSON-Liste `data/ratings-combined.json` zusammenführen:

```powershell
$r1 = Get-Content data/export-01/R1/ratings.json -Raw | ConvertFrom-Json
$r2 = Get-Content data/export-01/R2/ratings.json -Raw | ConvertFrom-Json
ConvertTo-Json -InputObject (@($r1) + @($r2)) -Depth 10 | Set-Content -Encoding utf8NoBOM data/ratings-combined.json
python manage.py analyze --ratings data/ratings-combined.json --out data/analysis-01.json
```

Ohne Bewertungen: `python manage.py analyze --out data/time-analysis.json`. Fehlende Qualitätswerte bleiben fehlend. Doppelte oder unvollständige Bewertungen werden abgewiesen. Je zwei unabhängige Rater ergeben einen Mittelwert; Originalwerte bleiben in den eingereichten Dateien. Konsensänderungen separat berichten.

`pairs` enthält vollständige Zeitpaare, `quality_pairs` Aufgabe- und Gesamtwerte inklusive Timeout-Markierung, `observations` Fall/Position/Gruppe zur Prüfung von Reihenfolgeeffekten. Negative Zeitdifferenz AI−manuell bedeutet schneller; positive Qualitätsdifferenz bedeutet höhere Punkte. Keine automatische Signifikanzbehauptung. Pilotdaten werden aus Analyse stets ausgeschlossen.

## Störungen und Grenzen

KI-Fehler werden mit Status, Frage und Zeit protokolliert; nie mit erfundener Antwort ersetzt. Nach 60 Sekunden Netzwerk-Timeout; unbestätigte Anfragen nach Neustart können nach 90 Sekunden erneut versucht werden und bleiben als unterbrochen sichtbar. Maximal 12 Aufrufe pro Runde. Bei Antwort nach Abgabe/Deadline nur Audit, keine Änderung des Endergebnisses. Anbieterfehler nicht durch anderes Modell umgehen.

Bei Netzwerkproblemen verbleibt der lokale Entwurf im Tab-Speicher; nach Refresh kann er erneut gespeichert werden, sofern die Deadline nicht abgelaufen ist. Formale Leistung basiert nur auf rechtzeitig serverseitig gesicherten Daten. Autosave alle 700 ms nach Eingabepause; extrem schnelle Eingaben kurz vor Deadline können lokal bleiben. Bei längerer Störung abbrechen und im Protokoll als Abweichung zählen; nicht stillschweigend wiederholen. Ein Tab pro Sitzung; paralleles Bearbeiten derselben Einladung wird nicht unterstützt.

Keine Ergebnisse vorab anzeigen oder erfundene Studienzahlen einfügen. Der Demonstrator kann keine externe KI-Nutzung erkennen; Regelbefolgung wird durch betreute Durchführung und Nachbefragung kontrolliert.


**Sequenz innerhalb jeder Runde:** Zuerst Basisplan verbindlich abschließen (`POST /api/plan`); danach wird er schreibgeschützt und erst dann erscheinen Ausgangsplan/Änderungen für Aufgabe 2. Dasselbe 25-Minuten-Limit läuft weiter. Auch die KI erhält vorher keine Änderungsmaterialien. Dadurch wird die Referenzlösung für Aufgabe 1 nicht vorab offengelegt.
