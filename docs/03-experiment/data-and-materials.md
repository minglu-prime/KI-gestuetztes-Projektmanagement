# Daten und Materialien: öffentlich vs. geschützt

| Öffentlich in diesem Repository | Geschützter Studienarbeitsbereich |
|---|---|
| Forschungsfrage, Methode, Rubrikstruktur, Such-/Evidenzvorlagen | Namen, Kontakte, Termine pro Person und Einladungslinks |
| Synthetische Demo-/Pilotfälle, Prompt und Code | neue formale Fallvarianten und Referenzantworten vor Erhebung |
| Arbeitsvorschläge für Team/Roadmap | Einwilligungsunterlagen, Rohdaten, Entwürfe, KI-Dialoge |
| Nach Freigabe ausreichend aggregierte Ergebnisse | Schlüsseldatei für Rater-IDs, private Bewertungen und Sicherungen |

Ein Ordner namens „private“ in einem öffentlichen Git-Commit ist weiterhin öffentlich. `.gitignore` verhindert versehentliches Hinzufügen, bietet aber keine Verschlüsselung. Git-Historie behält veröffentlichte Dateien. Deshalb Daten vor Commit prüfen; keine formalen Geheimaufgaben erst veröffentlichen und anschließend nur löschen.

## Öffentliche Pilotfälle

`cases.json` und ihre Antworten sind Lehr-/Demomaterial. Teilnehmende könnten sie auf GitHub sehen. Das ist bei der Pilotvorführung vertretbar, für eine kontrollierte formale Erhebung aber eine mögliche Kontamination. Der bestehende Demonstrator liest aktuell die lokale `cases.json`; eine separate private Materialquelle für den Formalbetrieb ist noch ein Arbeitspaket. Bloßes Umbenennen der gleichen Fälle reicht nicht.

Vor Formalstart: neue Varianten fachlich prüfen, außerhalb der Git-Historie lagern, Zugriff im Studienbetrieb umsetzen und Freeze/Export auf die tatsächlich eingesetzte Version prüfen. Personen mit Kenntnis der endgültigen Fälle nicht ungekennzeichnet als naive Teilnehmende zählen.

## Verantwortung und Aufbewahrung

Studienleitung legt Kontakt, zulässige Nutzung, Empfänger, Speicherort, Backup und Löschdatum fest. Kontakte getrennt von Pseudonymen und Ergebnissen halten. Rater bekommen nur ihr Paket, nicht die private Zuordnung oder KI-Logs. Reflexionen/Freitext vor einer Veröffentlichung auf Identifizierbarkeit prüfen. Keine echte Unternehmensinformation an KI übermitteln.

Bereits im Repository vorhandene Kursdatei wird nicht automatisch als zur beliebigen Weiterveröffentlichung freigegeben betrachtet; weitere Uploads nur mit geklärter Berechtigung. Aus der beigefügten Kontaktliste werden keine Telefonnummern oder E-Mail-Adressen übernommen.
