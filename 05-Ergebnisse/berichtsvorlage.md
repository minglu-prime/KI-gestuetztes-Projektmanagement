# Berichtsvorlage (Entwurf zu Issue #11)

> **Entwurf, von der Gruppe zu bestätigen.** Gliederung und Tabellen für den Ergebnisbericht. Die Tabellen entsprechen den Feldern, die `manage.py analyze` ausgibt (`analysis.summarize`), damit nichts von Hand gerechnet wird. Noch gibt es keine empirischen Ergebnisse; die Platzhalter `…` bleiben bis zur Auswertung leer.

## Regeln vor dem Schreiben

- Zuerst bewerten beide Rater blind und unabhängig. Erst danach wird die Zuordnung (`private/key.json`) geöffnet und mit `analyze --ratings` zusammengeführt.
- Deskriptiv berichten: Median, Spannweite, Einzelpaare. Keine Signifikanz, keine Kausalaussage über KI allgemein.
- Null- und Gegenbefunde stehen gleichrangig neben erwarteten Befunden.
- Keine Rohdaten, keine Kennungen und keine wörtlichen Zitate aus Reflexionen ohne Freigabe der Person. Zitate nur anonym und gekürzt.
- Pilotsitzungen sind ausgeschlossen; sie werden nur im Methodenteil erwähnt.

## 1. Frage und Ergebnis in drei Sätzen

…

## 2. Methode

- Design: Vergleich innerhalb der Person, vier Abläufe (siehe `03-Experiment/versuchsdesign.md`), Fälle A und B, 25 Minuten je Runde.
- Teilnehmende: Anzahl (`participants`), Erfahrung (Kategorien), Abläufe je Gruppe.
- KI: Endpunkt der Hochschule, angefragtes Modell, gemeldete Modelle (`models_returned`), ob es mehr als eines war (`model_varies`), Reasoning, Systemprompt (Prüfsumme aus dem Freeze).
- Bewertung: Rubrik (`03-Experiment/bewertungsrubrik.md`), Ergebnis der Kalibrierung.
- Abweichungen vom Protokoll mit Datum.

## 3. Vollständigkeit und Ausfälle

| Größe | Wert |
|---|---|
| Formale Teilnehmende (`participants`) | … |
| Vollständige Paare (`complete_pairs`) | … |
| Unvollständige Teilnahmen (`incomplete_participants`) | … |
| Runden mit Zeitablauf (`timeouts`) | … |
| Fehlgeschlagene oder unfertige KI-Aufrufe (`ai_failed_or_unfinished_calls`) | … |

## 4. Zeit

Nur vollständige Paare (`pairs`):

| Teilnehmende | Gruppe | manuell (s) | mit KI (s) | KI − manuell (s) |
|---|---|---:|---:|---:|
| … | … | … | … | … |

Median der Differenz (`median_time_delta`): … s. Eine kürzere Zeit ist nur zusammen mit der Qualität zu lesen.

## 5. Qualität

Paare mit zwei vollständigen Bewertungen je Runde (`quality_pairs`), Mittel der beiden Rater:

| Teilnehmende | Plan manuell | Plan KI | Risiko manuell | Risiko KI | Fehler manuell | Fehler KI | mit Zeitablauf |
|---|---:|---:|---:|---:|---:|---:|---|
| … | … | … | … | … | … | … | … |

Abweichung zwischen den Ratern (`rater_disagreements`): …

## 6. Was die Personen beobachtet haben

Anonymisierte, verdichtete Auswertung der fünf Reflexionsfragen: wofür Zeit gebraucht wurde, welche KI-Aussagen geprüft oder verworfen wurden, welche Entscheidungen bei Menschen bleiben, Belastung, Abweichungen. Erstentwurf der KI (`first_ai_draft`) und Endfassung vergleichen, wo es die Freigabe erlaubt.

## 7. Einordnung

- Chancen und Risiken mit Bezug auf `02-Recherche` (Literaturregister-IDs).
- Was sich an der PM-Rolle ändert: nur aus den Daten dieser Studie ableiten und als Hypothese kennzeichnen, wo die Daten nicht reichen.

## 8. Grenzen

- Kleine Stichprobe (Ziel 12, mindestens 8), deskriptiv.
- Synthetische Fälle; Gleichwertigkeit nur in Piloten geprüft.
- Ein Modell an einem Endpunkt; kein datierter Snapshot (Entscheidung E01): Ein Modellwechsel hinter demselben Namen ist nicht auszuschließen.
- 25 Minuten Zeitlimit; keine Übertragbarkeit auf lange Projekte ohne weitere Belege.

## 9. Anhang

- Version der Fälle und Prüfsummen (Freeze).
- Rubrik und Kalibrierungsprotokoll.
- Liste der Protokollabweichungen.
