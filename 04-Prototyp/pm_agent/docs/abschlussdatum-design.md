# Design-Vorschlag: Tatsächliche Enddaten

Stand 17.11.2026. **Nur Vorschlag, noch kein Code.** Schließt die Lücke, die
`docs/abschluss-design.md` und PR 47 unter „Bewusst offen“ nennen.

## Wozu

Der Abschlussbericht nennt Zeitraum und geplantes Ende, aber kein tatsächliches Ende. Der
Fortschritt kennt je Aufgabe nur den Status, nicht den Tag, an dem sie fertig wurde. Damit
fehlt im Rückblick die wichtigste Frage zur Termintreue: Wann war das Projekt wirklich fertig,
und welche Aufgaben wurden später fertig als geplant?

## Ziele

- Je Aufgabe ein **Fertigdatum**, sobald sie den Status `fertig` hat.
- Abschlussbericht: **tatsächliches Ende** (letztes Fertigdatum, wenn alle Aufgaben fertig
  sind) neben dem geplanten Ende, dazu die Abweichung in Arbeitstagen und die Aufgaben, die
  nach ihrem geplanten Ende fertig wurden.
- Durchführung: Die Spalte „Prognose Ende“ zeigt bei fertigen Aufgaben das Fertigdatum statt
  nur „fertig“.

## Nicht-Ziele

- Kein Zeitstempel je Statuswechsel, keine Historie der Stände. Nur der letzte Fertigtag.
- Keine Änderung an Prognose und Earned Value: beide rechnen weiter mit Stunden, nicht mit
  Daten.
- Kein Startdatum je Aufgabe (wäre die nächste Frage, ist aber für den Bericht nicht nötig).

## Daten

- `Progress.finished_on: date | None = None`. Mit Default, damit alte `projekt.json` lesbar
  bleiben.
- `Earlier.finished_on: date | None = None`: Beim erneuten Übernehmen bleibt das Datum
  fertiger Aufgaben in der Historie erhalten.
- Regel in `tracking.apply_rows`:
  - Status wechselt auf `fertig` und es gibt noch kein Datum: `finished_on = heute`.
  - Status ist nicht `fertig`: `finished_on = None`.
  - Steht in der Tabelle ein Datum, gilt das (Korrektur, wenn jemand erst später nachträgt).
    Prüfung: nicht in der Zukunft, nicht vor dem Projektstart; sonst `InputError` mit Zeile.
- `tracking.reopen` (Fehler öffnet die Aufgabe wieder) löscht `finished_on`.

## Oberfläche

- Durchführung, Fortschrittstabelle: neue Spalte **„Fertig am“**, bearbeitbar, leer bei
  offenen Aufgaben. „Prognose Ende“ zeigt bei fertigen Aufgaben das Fertigdatum.
- Abschluss, Bericht (`templates/abschluss.md`):
  - `**Tatsächliches Ende:** 05.02.2027 (3 Arbeitstage nach Plan)` oder, solange etwas offen
    ist, `noch offen (X von Y Aufgaben fertig)`.
  - Tabelle „Später fertig als geplant“: Aufgabe, geplantes Ende, fertig am, Verzug in
    Arbeitstagen. Leer: „Alle Aufgaben rechtzeitig fertig.“
  - Aufgaben ohne Datum (aus der Zeit vor dieser Änderung): `Fertigdatum unbekannt`; sie
    zählen nicht zum tatsächlichen Ende, der Bericht sagt das in einem Satz.

## Prüfung

- Keine neuen Fehler im Abschluss. Warnung: „N fertige Aufgaben ohne Fertigdatum, das
  tatsächliche Ende ist eine Untergrenze.“

## Ansätze

1. **Fertigdatum im Fortschritt (vorgeschlagen).** Ein Feld, gesetzt beim Speichern,
   korrigierbar. Klein, alte Dateien bleiben gültig.
2. **Ereignisprotokoll je Statuswechsel.** Genauer (auch Startdatum, Wiederöffnen), aber
   ein neues Datenmodell und mehr Oberfläche für eine Zahl im Bericht.
3. **Datum der letzten Speicherung als Ende.** Kein neues Feld, aber falsch, sobald jemand
   nach dem Ende noch Notizen ändert.

## Offene Fragen an dich

1. Soll das Fertigdatum in der Tabelle **bearbeitbar** sein (Vorschlag: ja, zum Nachtragen),
   oder nur automatisch gesetzt?
2. Verzug in **Arbeitstagen** (Vorschlag, wie der Plan rechnet: ohne Wochenenden und freie
   Tage) oder in Kalendertagen?

## Tests (beim Bau, jeweils zuerst rot)

- Alte `projekt.json` ohne Feld lädt; `finished_on` ist `None`.
- `fertig` setzt heute; erneutes Speichern ändert das Datum nicht; zurück auf `in Arbeit`
  löscht es; `reopen` löscht es.
- Datum in der Zukunft oder vor Projektstart: `InputError` mit Zeilennummer.
- Erneutes Übernehmen: Datum landet in `Earlier.finished_on`.
- Bericht: tatsächliches Ende, Abweichung, Tabelle „Später fertig“, Fall „noch offen“, Fall
  „Fertigdatum unbekannt“.
- AppTest: Spalte „Fertig am“ in der Durchführung.
