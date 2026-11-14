# Studienprotokoll v1.0 — Pilotfassung

## Forschungsfrage und Geltungsbereich

Bei welchen Projektmanagement-Aufgaben verbessert KI die Effizienz und Ergebnisqualität, und wie verändern sich dabei menschliche Aufgaben und Verantwortlichkeiten?

Untersucht wird die **KI-Assistenz als Gesamtintervention** (gewähltes Modell, festgelegter Systemprompt und Interface), nicht KI allgemein. Zwei Aufgaben: Basisplanung sowie Risiko-/Änderungsanalyse. Hypothesen vorab: kürzere Bearbeitungszeit; gleichbleibende oder höhere Qualität; Verschiebung von Erstellung zu Prüfung. Gegenläufige Resultate sind gleichwertige Ergebnisse. Kein Nachweis, dass ganze PM-Berufe entfallen.

## Design

Explorativer Within-Person-Vergleich mit zwei parallelen Fällen. Vier Sequenzen: manuell A → KI B; KI B → manuell A; manuell B → KI A; KI A → manuell B. Beide Aufgaben teilen sich ein Zeitlimit von 25 Minuten pro Runde. Materialien und Editor sind gleich; nur KI-Verfügbarkeit unterscheidet sich. Aufgabe 2 nutzt einen gegebenen Ausgangsplan, um Fehler aus Aufgabe 1 nicht weiterzutragen.

Ziel 12 externe Teilnehmende. Ab 8 formal als kleine explorative Studie ausführbar, ohne Anspruch auf hinreichende statistische Power. Bei weniger als 8 bis Ende Woche 2: ausdrücklich explorative Fallserie mit Einzelfallberichten. Teammitglieder nur im Pilot. Volljährige, deutschsprachige Teilnehmende mit ausreichendem Verständnis der Instruktionen; PM-Fachkenntnis nicht erforderlich. PM- und KI-Erfahrung kategorisch erfassen, Studierende und Praktiker im Bericht auseinanderhalten.

Die CLI erstellt blockrandomisierte Sequenzen in Viererblöcken mit dokumentiertem Seed. Vorwissen wird vor der Runde erfasst. **Die Software stratifiziert nicht automatisch nach Erfahrung.** Wenn Vorabdaten für Erfahrungsschichten vorhanden sind, getrennte Enrollment-Blöcke mit unterschiedlichen Seeds und nicht überlappenden P-IDs verwenden; Zuteilung innerhalb jeder Schicht nach Rekrutierungsreihenfolge. Keine nachträglichen Gruppenwechsel aufgrund erwarteter Leistungen. Bei 12 Personen können kleine Schichten unausgeglichen sein; im Bericht offenlegen.

## Standardisierte Durchführung (~70 Minuten)

| Abschnitt | Dauer | Vorgehen |
|---|---:|---|
| Information/Einwilligung | 5 min | Zweck, Daten, Abbruch und Datenschutzkontakt erklären; Erfahrung erfassen |
| Übung/Interface-Einführung | 5 min | Separater Workshop-Fall; Editor, Speicherung und KI-Eingabefeld erklären; keine A/B-Lösungen |
| Runde 1 | 25 min | Beide Aufgaben, keine Hilfe zu Inhalten |
| Pause | 3 min | Keine Ergebnisdiskussion, kein Austausch |
| Runde 2 | 25 min | Anderer Fall und andere Bedingung |
| Reflexion | 7 min | Gleiche Fragen für alle; ggf. kurze Vertiefung |

Immer dieselben Instruktionen lesen: keine externe Recherche, keine zusätzlichen KI-Tools, normale Rechenhilfe erlaubt. Ein Tab, ein Studienrechner pro Sitzung. Nur Bedienhilfe, keine fachlichen Hinweise. Teilnehmende können jederzeit abbrechen; Schließen stoppt den Timer nicht. Nach Deadline zählt nur der rechtzeitig am Server gespeicherte Stand. Abwesenheit oder technische Störung als Abweichung dokumentieren, keine informelle Zeitverlängerung.

## Vorversuch und Freeze

2–3 nicht formal gezählte Personen prüfen Verständlichkeit, Bedienbarkeit, Dauer, Ambiguitäten und Vergleichbarkeit. Mindestens ein echter KI-Aufruf mit der ausgewählten Snapshot-ID; Latenz und Logvollständigkeit prüfen. Pilotdaten nicht zur Behauptung statistischer Fallgleichheit verwenden. A/B-Fälle sind strukturell ähnlich und können Lernen übertragen; Reihenfolgeausgleich reduziert, beseitigt das Problem aber nicht.

Nach Änderungen erneut die betroffenen Szenarien testen. Prüfliste: verständliche Materialien; fachlich überprüfte Referenzpläne; Rubrik an zwei Beispielantworten kalibriert; zwei unabhängige Bewertende; Daten-/Löschregeln konkret; Modell und Budget bestätigt; Rekrutierung realistisch. Dann `manage.py freeze` mit schriftlicher Freigabe. Änderungen nach Freeze führen zu neuer Studie/neuer Datenbank; nicht mitten im Datensatz austauschen.

## Messung und Analyse

Zeit von Fallöffnung bis Abgabe, einschließlich KI-Warten und Prüfen. Deadlinefälle sind rechtszensiert/unvollständig; nicht als schnelle Erfolge behandeln. Primärer deskriptiver Zeitvergleich nur vollständiger Paare; Anzahl und Bedingungen der Ausfälle separat. Qualitätsauswertung auch für gesicherte Teilstände, mit Timeout-Kennzeichnung. Keine stillschweigende Ergänzung fehlender Daten mit 0.

Rubrik 100 Punkte (50 Plan/50 Risiko). Zwei unabhängige Bewertungen, Bedingungen und Personen ausgeblendet; Stil kann KI verraten. Primärer Qualitätswert ist der Mittelwert beider unabhängigen Bewertungen. Abweichungen berichten; eine nachgelagerte Konsensdiskussion separat dokumentieren, Originalbewertungen nie ersetzen. Schwere Fehler separat zählen.

Je Person AI−manuell ausgeben; Median und Einzelfälle zeigen. Qualität getrennt nach beiden Aufgaben, Fehler und technische Ausfälle berichten. Gruppen-/Fall-/Positionsunterschiede anhand der exportierten Beobachtungstabelle prüfen; geringe Fallzahlen ausdrücklich nennen. Keine automatisierten Signifikanzbehauptungen oder Generalisierung auf Industrie-PM. Vorwissen, Übungseffekt, Promptkompetenz, Modellsnapshot und synthetische Fälle begrenzen Übertragbarkeit.

## Einwilligung und Datenverantwortung

Dies ist eine Vorlage zur organisatorischen Abstimmung, keine bestätigte Hochschulfreigabe. Vor Rekrutierung legt die Studienleitung Ansprechpartner, Zweck, Empfängerkreis, Speicherort und Löschdatum fest und klärt gegebenenfalls notwendige Hochschulvorgaben. Keine Kontaktdaten aus der Teamliste in den Quellcode übernehmen.

Erfasst: P-ID, Erfahrungskategorien, Zeitpunkte, Entwurfsstände, KI-Fragen/-Antworten, technische Fehler, Ergebnisse, Reflexion. In der KI-Bedingung gehen Fallmaterial, aktueller Entwurf und Fragen an OpenAI. `store:false` ist gesetzt, ersetzt aber keine Prüfung der Anbieterbedingungen. Keine Namen, Kunden- oder Unternehmensdaten eingeben. Kontakt-/Einladungszuordnung separat und zugriffsbeschränkt verwahren.

Abbruch wird akzeptiert, technische Teilstände bleiben zunächst gespeichert. Löschwunsch anhand der P-ID durch Studienleitung bearbeiten und in allen Arbeitskopien/Exporten berücksichtigen. Einwilligung im UI ersetzt nicht die vorherige konkrete Information. Öffentlich geteilt werden nur freigegebene aggregierte Befunde oder ausreichend bereinigte Beispiele, niemals ungeprüfte Rohdaten.


**Sequenz innerhalb jeder Runde:** Zuerst Basisplan verbindlich abschließen (`POST /api/plan`); danach wird er schreibgeschützt und erst dann erscheinen Ausgangsplan/Änderungen für Aufgabe 2. Dasselbe 25-Minuten-Limit läuft weiter. Auch die KI erhält vorher keine Änderungsmaterialien. Dadurch wird die Referenzlösung für Aufgabe 1 nicht vorab offengelegt.
