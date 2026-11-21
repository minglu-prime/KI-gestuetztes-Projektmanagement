# Versuchsdesign (Entwurf zu Issue #5)

> **Entwurf, von der Gruppe zu bestätigen.** Was das KI-Lab schon umsetzt, steht als Tatsache da, mit der Stelle im Code. Alles, was die Gruppe noch entscheiden muss, ist mit **Entscheidung der Gruppe** markiert. Beschlüsse kommen nach `01-Projektplanung/entscheidungen.md`.

## Frage

Wie verändert KI-Assistenz Zeit, Qualität und menschliche Entscheidungen bei zwei Projektmanagement-Aufgaben?

- **Aufgabe 1:** einen Basisplan erstellen.
- **Aufgabe 2:** Risiken und eine Änderung analysieren.

Untersucht wird die KI-Assistenz als Ganzes: Modell, Systemprompt (`04-Prototyp/ki_lab/prompt.txt`) und Oberfläche. Es geht nicht um „KI allgemein“.

## Vergleich innerhalb jeder Person

Jede Person bearbeitet zwei Runden:
- einmal ohne KI (manuell) und einmal mit KI;
- jedes Mal einen anderen Fall (A oder B).

So vergleicht jede Person sich selbst; das Team wird nicht in Leistungsgruppen geteilt.

**Vier Abläufe** (`lab.SEQUENCES`):

| Gruppe | Runde 1 | Runde 2 |
|---|---|---|
| 1 | Fall A, manuell | Fall B, mit KI |
| 2 | Fall B, mit KI | Fall A, manuell |
| 3 | Fall B, manuell | Fall A, mit KI |
| 4 | Fall A, mit KI | Fall B, manuell |

**Zuteilung:**
- `manage.py enroll` mischt die vier Gruppen in Viererblöcken mit festem Seed (Standard `20261030`). Seed und Zuteilung stehen in der Einladungsliste.
- Die Software schichtet nicht nach Erfahrung.
- **Entscheidung der Gruppe:** Sollen Personen mit viel und wenig PM-Erfahrung getrennt zugeteilt werden? Wenn ja: je Schicht ein eigener Block mit eigenem Seed und eigenem Kennungsbereich (`--start`).

## Gleiche Bedingungen

- **Material:** Beide Fälle haben dasselbe Format: 9 Arbeitspakete, Tage T1–T20, sechs Ressourcen, ein Budget, ein Zieltermin, eine Änderung für Aufgabe 2 (`cases.json`). Die Fälle sind synthetisch und noch nicht auf gleiche Schwierigkeit geprüft (`notice` in `cases.json`); das prüfen die Piloten (#7).
- **Zeit:** 25 Minuten je Runde für beide Aufgaben zusammen (`lab.LIMIT`). Die Zeit läuft ab dem Start; nach Ablauf zählt der letzte gespeicherte Stand als unvollständiges Ergebnis (`timed_out`).
- **Reihenfolge in einer Runde:**
  1. Basisplan schreiben und sperren (`finish_plan`).
  2. Erst danach erscheinen Änderung und Ausgangsplan (`visible_case`).
  3. Aufgabe 2 baut auf dem gelieferten Ausgangsplan auf, nicht auf dem eigenen Entwurf. So trägt sich ein Fehler aus Aufgabe 1 nicht weiter.
- **KI:**
  - Nur in der KI-Runde; in der manuellen Runde lehnt der Server jede KI-Frage ab (`Lab.ask`, 403).
  - Höchstens 12 Fragen je Runde.
  - Die KI sieht Fallmaterial, Entwurf und Frage.
- **Hilfsmittel:**
  - Keine externe Recherche; ein normaler Taschenrechner ist erlaubt (Text der Einwilligung).
  - **Entscheidung der Gruppe:** Papier für Notizen erlaubt?
- **Ablauf, etwa 70 Minuten:**
  1. Einwilligung und Erfahrung (Kategorien `keine/wenig/viel` und `nie/selten/oft`)
  2. Übungsfall
  3. Runde 1
  4. kurze Pause
  5. Runde 2
  6. Reflexion mit fünf Fragen (`Lab.reflect`)

## Störgrößen und wie das Design sie behandelt

| Störgröße | Behandlung |
|---|---|
| Unterschiedliche Fähigkeiten der Personen | Vergleich innerhalb der Person |
| Reihenfolge (Lernen, Ermüdung) | Vier Abläufe, ausgeglichen in Viererblöcken |
| Fall A leichter als Fall B | Jeder Fall kommt gleich oft mit und ohne KI vor; Piloten prüfen die Gleichwertigkeit |
| Vorwissen über die Fälle | Teammitglieder nur im Pilot; die formalen Fälle bleiben privat (#6) |
| Austausch zwischen Teilnehmenden | **Entscheidung der Gruppe:** Termine einzeln oder getrennt halten; Bitte um Stillschweigen |
| Modellwechsel beim Anbieter | Gemeldetes Modell je Aufruf, `models_returned` in der Auswertung (Entscheidung E01) |

## Messgrößen

Festgelegt **vor** der Erhebung:

1. **Zeit:** Sekunden vom Start bis zur Abgabe je Runde. Verglichen wird nur bei vollständigen Paaren (beide Runden abgegeben): Differenz KI minus manuell, Median über die Paare (`summarize`: `pairs`, `median_time_delta`).
2. **Qualität des Basisplans:** 0–50 Punkte (Abhängigkeiten 20, Ressourcen 15, Meilensteine 15).
3. **Qualität der Risiko- und Änderungsanalyse:** 0–50 Punkte (Risiken erkennen 20, Priorisieren 15, Maßnahmen 15).
4. **Schwere Fehler:** Anzahl je Antwort, Definition in [`bewertungsrubrik.md`](bewertungsrubrik.md).
5. **Ausfälle:**
   - Zeitüberschreitungen (`timeouts`)
   - fehlgeschlagene KI-Aufrufe (`ai_failed_or_unfinished_calls`)
   - unvollständige Teilnahmen (`incomplete_participants`)
   Alle drei werden getrennt berichtet, nicht still entfernt.
6. **Reflexion:** fünf offene Antworten zu Zeit, Prüfung von KI-Aussagen, Entscheidungen bei Menschen, Belastung und Abweichungen.

Bewertet wird blind: Die Rater sehen nur `rating_id`, Fall, Plan und Risiken (`export_bundle`). Bedingung und Person stehen nur im privaten Schlüssel.

## Stichprobe und was sie trägt

- **Ziel:** 12 externe, erwachsene, deutschsprachige Teilnehmende; PM-Wissen ist nicht nötig.
- Ab 8 vollständigen Paaren eine kleine explorative Studie. Mit 8 oder 12 Personen lässt sich **keine** statistische Aussagekraft behaupten. Die Auswertung ist deskriptiv (Median, Spannweite, Einzelpaare) und nennt keine Signifikanz.
- Unter 8 Personen bis Ende Woche 2: **Entscheidung der Gruppe**, ob ausdrücklich als explorative Fallserie mit Einzelfallberichten weitergemacht wird (#8).
- Teammitglieder nehmen nur an Piloten teil, nicht an der formalen Erhebung.

## Abbruch- und Ausschlussregeln

- **Abbruch durch die Person:** jederzeit. Die Daten bleiben, bis Löschung verlangt wird; die Person zählt als unvollständig.
- **Technischer Fehler:** Er wird mit Uhrzeit im Protokoll der Durchführung notiert. Keine stille Wiederholung derselben Runde.
- **Entscheidung der Gruppe:** Darf eine Person nach einem technischen Abbruch mit neuer Kennung neu beginnen? Wenn ja, wird die alte Kennung als ausgeschlossen mit Grund berichtet.
- Keine nachträgliche Änderung der Zuteilung wegen erwarteter Leistung.

## Offen vor dem Start (M1/M2)

- Bestätigung der Punkte „Entscheidung der Gruppe“ oben (#1, #5).
- Private formale Fallvarianten mit Referenzlösungen (#6).
- Piloten und Raterkalibrierung (#7), siehe [`pilot-checkliste.md`](pilot-checkliste.md).
- **Einwilligungstext:** Er nennt „OpenAI“ als Empfänger. Die Daten gehen aber an den Dienst in `OPENAI_BASE_URL` (Endpunkt der Hochschule), und der Text muss das genau benennen. Kontakt und Löschfrist ergänzen (#8).
