# Durchführungsprotokoll (Vorlage zu Issue #10)

> **Vorlage, von der Gruppe zu bestätigen.** Für die formale Erhebung **nach** der M2-Freigabe: bestätigtes Protokoll, Rubrik, private Fälle, getestete KI, Datenregeln (siehe [`pilot-checkliste.md`](pilot-checkliste.md)). Je Termin ein ausgefülltes Exemplar. Die ausgefüllten Bögen enthalten Kennungen und Uhrzeiten und bleiben **privat** (nicht im Repository). Öffentlich ist nur die Zusammenfassung am Ende.

## Vor dem ersten Termin (einmal)

- [ ] M2-Freigabe in `01-Projektplanung/entscheidungen.md` eingetragen.
- [ ] Freeze in der formalen Datenbank gesetzt (`manage.py freeze`). Ausgabe gesichert: Fallversion, Prüfsummen, Quelle `privat`, Modell, Zeitlimit.
- [ ] Einladungen erzeugt (`manage.py enroll --count … --seed …`). Seed und Kennungsbereich notiert; die Einladungsliste liegt privat.
- [ ] Datensicherung der Datenbank nach jedem Termin geplant (Ort: […], nicht im Repository).

## Je Termin

| Feld | Eintrag |
|---|---|
| Datum, Beginn, Ende | |
| Kennung | P… |
| Ablauf (Gruppe 1–4, aus der Einladung) | |
| Leitung (Rolle) | |
| Ort / Rechner / Browser | |
| Einwilligung erteilt (Uhrzeit), freiwillige Zitat-Einwilligung ja/nein | |
| Übung durchgeführt | ja / nein |
| Runde 1: Start, Abgabe oder Zeitablauf | |
| Pause (Minuten), kein Austausch über Inhalte | |
| Runde 2: Start, Abgabe oder Zeitablauf | |
| Reflexion gespeichert | ja / nein |
| Anzahl KI-Fragen in der KI-Runde; Fehlermeldungen des Dienstes | |

### Ablauf, gleich für alle

1. Begrüßung, Teilnahmeinformation aushändigen oder zeigen, Fragen beantworten.
2. Einwilligung im Lab. Erfahrung auswählen.
3. Übungsfall (nicht gewertet): Oberfläche, Speichern, Sperren des Basisplans, KI-Feld zeigen. **Keine Hinweise zu Inhalten der Fälle.**
4. Runde 1 nach Einladung. Die Leitung greift nur bei technischen Problemen ein.
5. Kurze Pause; kein Gespräch über die Fälle.
6. Runde 2.
7. Reflexion. Hinweis auf Kontakt und Löschfrist.

Erlaubt: normaler Taschenrechner, [Notizpapier: laut Beschluss V3]. Nicht erlaubt: externe Recherche, andere KI-Werkzeuge, ein zweiter Browser-Tab.

### Abweichungen und technische Fehler

Jede Abweichung sofort mit Uhrzeit eintragen. Keine stille Wiederholung einer Runde.

| Uhrzeit | Was ist passiert? | Betroffene Runde | Was wurde getan? | Folge für die Auswertung |
|---|---|---|---|---|
| | | | | |

Beispiele:
- Seite neu geladen (die Zeit läuft weiter, der Entwurf bleibt)
- KI-Dienst antwortet nicht
- Person bricht ab
- Hilfe zum Inhalt gegeben (vermeiden; wenn doch, genau notieren)
- Neustart mit neuer Kennung (nur laut Beschluss V5; alte Kennung als ausgeschlossen mit Grund)

## Nach jedem Termin

- [ ] Sitzung im Lab vollständig (beide Runden `submitted` oder `timed_out`, Reflexion).
- [ ] Datenbank gesichert.
- [ ] Bogen vollständig, privat abgelegt.

## Öffentliche Zusammenfassung (nur aggregiert)

Für das Issue #10 und den Bericht, ohne Kennungen und Uhrzeiten:

| Stand (Datum) | Termine | vollständige Paare | Zeitabläufe | Abbrüche | technische Fehler | Abweichungen vom Protokoll |
|---|---:|---:|---:|---:|---:|---:|
| … | … | … | … | … | … | … |

Die Zahlen für vollständige Paare, Zeitabläufe und fehlgeschlagene KI-Aufrufe liefert `manage.py analyze`; Abweichungen kommen aus den Bögen.
