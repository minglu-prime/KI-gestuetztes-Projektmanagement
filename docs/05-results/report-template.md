# Berichtsvorlage — noch keine empirischen Ergebnisse

## 1. Ausgangslage und Frage

Welche PM-Aufgaben verändern sich durch KI? Begründung aus Recherche und Lehrprojekt. Aufgaben, Fallkontext und gewählte Implementierung nennen. Quellenmatrix beilegen, Herstellerangaben klar kennzeichnen.

## 2. Methode

Protokollversion/Freeze-Hash, Modell-Snapshot, Promptversion, Zeitraum, Rekrutierung und Zusammensetzung berichten. Tatsächliche N, Ein-/Ausschlüsse, Pilot/Formaltrennung und Sequenzverteilung nennen. Keine Poweranalyse behaupten, die nicht durchgeführt wurde. Zwei Rater, Rubrik, Verblindungsgrenzen und Umgang mit Zeitlimits beschreiben.

## 3. Ergebnisse (nach Erhebung ausfüllen)

| Größe | Ergebnis | Datenquelle |
|---|---|---|
| Formale Teilnehmende / vollständige Paare | noch nicht erhoben | analysis.participants / complete_pairs |
| Median Zeitdifferenz KI−manuell | noch nicht erhoben | median_time_delta |
| Planqualität / Risikoqualität je Bedingung | noch nicht bewertet | quality_pairs |
| Schwere Fehler und Timeout-Fälle | noch nicht erhoben | Bewertungen / timeouts |
| Technische KI-Ausfälle | noch nicht erhoben | ai_failed_or_unfinished_calls |
| Raterabweichungen | noch nicht bewertet | rater_disagreements |

Diagramme erst mit realen Daten: verbundene Punkte pro Person für Zeit und Qualität; separate Aufgabenwerte; Timeout-Markierungen. Für Fall-/Reihenfolgeeffekte `observations` nach Fall, Position und Sequenz tabellieren. Keine bereinigten Mittelwerte ohne Nenner und Ausschlussgründe.

## 4. Mensch-KI-Zusammenarbeit

Ausgewählte anonymisierte Erstentwurf/Endfassung-Paare zeigen: übernommen, korrigiert, verworfen, ergänzt. Ein KI-Erfolg und ein Fehlerfall, sofern tatsächlich beobachtet. Reflexionen anhand der Kategorien Erstellung, Prüfung, Koordination, Entscheidung codieren. Gegenbeispiele erhalten. Änderung des Texts allein beweist keine erfolgreiche inhaltliche Prüfung.

| Tätigkeit | Baseline | Mögliche KI-Rolle (Hypothese) | Menschliche Verantwortung | Empirischer Beleg |
|---|---|---|---|---|
| Planentwurf | Selbst erstellen | Vorschlag strukturieren | Ressourcen/Abhängigkeiten prüfen | offen |
| Risikoidentifikation | Quellen selbst prüfen | Hinweise bündeln | Relevanz und Evidenz bewerten | offen |
| Änderungen | Varianten begründen | Alternativen formulieren | Termine/Budget entscheiden und eskalieren | offen |
| Kommunikation | Bericht schreiben | Formulierungshilfe | Stakeholderbedürfnisse, Zusagen und Freigaben | außerhalb direkter Taskmessung |

## 5. Organisation und Fähigkeiten

Vorläufiges Zielbild, anhand von Ergebnissen und optionalen Praxisinterviews zu prüfen: KI erstellt/prüft Vorschläge, Fachverantwortliche validieren, PM koordiniert, Sponsor entscheidet über relevante Abweichungen. Benötigte Fähigkeiten könnten Aufgabenbeschreibung, Quellen-/Plausibilitätsprüfung, Toolkenntnisse, Datenbewusstsein und Eskalationskompetenz sein. Als Hypothesen kennzeichnen, solange keine passende Evidenz vorliegt.

## 6. Grenzen und Fazit

Kleine Gelegenheitsstichprobe, Erfahrungsmix, synthetische/ähnliche Fälle, Lerntransfer, ein Modell/Prompt, begrenzte Bearbeitungszeit, mögliche Entblindung und technische Ausfälle. Keine Arbeitsplatzabbauprognose aus zwei Aufgaben ableiten. Ergebnis differenziert formulieren: in dieser Aufgabe, mit dieser Konfiguration und dieser Stichprobe, unter diesen Bedingungen.

## Optionales Praxisinterview (15 Minuten)

1. Wie läuft Planung/Änderungssteuerung heute konkret ab?
2. Wo entstehen Routineaufwand und wo fachliche Unsicherheit?
3. Welche der beobachteten KI-Vorschläge wären nutzbar? Welche nicht?
4. Wer müsste welche Prüfung und Freigabe übernehmen?
5. Welche Daten, Schulungen oder Regeln fehlen für einen Pilotbetrieb?

Interviewaussagen dienen Kontext/Interpretation, nicht als Ersatz für experimentelle Messdaten. Teilnahme und Zitierbarkeit vorher abstimmen. Keine Kontaktaufnahme oder Nachricht wurde durch dieses Paket ausgeführt.
