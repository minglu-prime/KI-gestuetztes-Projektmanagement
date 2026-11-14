# Messplan und Datenwörterbuch

## Vorab festgelegte Zielgrößen

| Größe | Definition | Interpretation / Grenze |
|---|---|---|
| Rundenzeit | `ended_at − started_at` in Sekunden | beide Aufgaben gemeinsam, einschließlich KI-Warten, Lesen, Prüfen |
| Planqualität | dependencies + resources + milestones (0–50) | Fachrubrik, keine Sprachstilnote |
| Risikoqualität | risk_identification + prioritization + measures (0–50) | Evidenz, Priorität und umsetzbare Maßnahmen |
| Gesamtqualität | Plan + Risiko (0–100), Mittel zweier unabhängiger Rater | erst bei vollständigen Bewertungen beider Rater |
| Schwere Fehler | begründete Zahl verschiedener harter Verstöße | getrennt von Gesamtpunkten; nicht jede Auslassung schwer |
| Zeitlimit | `timed_out` bei 1500 Sekunden | unvollständig/zensoriert, nicht als erfolgreiche Abgabe behandeln |
| KI-Störung | Fehler, Unterbrechung, unbestätigte/späte Antwort | technische Abweichung, kein erfundener Ersatz |
| Zusammenarbeit | erster KI-Entwurf, Dialog, finaler Text, Reflexion | Textänderung allein beweist keinen Denkprozess |

## Datensatz

| Feld / Pfad | Bedeutung |
|---|---|
| participant / pilot | Pseudonym, Trennung Pilot/Formal |
| group | Sequenz 1–4, keine Leistungsgruppe |
| experience.pm / ai | kategorische Selbstauskunft, keine Kompetenzprüfung |
| config / materials / prompt | Konfiguration, Hashwerte und Material-Snapshot zur Reproduzierbarkeit |
| consent_at | protokollierter Zeitpunkt der Einwilligung; ersetzt nicht konkrete Information |
| rounds[].case_id / condition / stage | Fall, M/K und aktuelle Aufgabenphase |
| rounds[].rating_id | zufällige Bewertungskennung ohne öffentlich berechenbare Teilnehmerzuordnung |
| started_at / plan_locked_at / ended_at | UTC-Unixzeit in Sekunden; lokaler Termin separat dokumentieren |
| draft / revisions / final | Zwischenstände, Speichervorgänge und unveränderliches Endergebnis |
| first_ai_draft / ai_calls | erster rechtzeitig verfügbarer KI-Text, Fragen, Input, Antworten, Status und Metadaten |
| reflection / events | qualitative Rückmeldung und technische Prozessereignisse |

Kontaktliste, Rekrutierungsnachrichten und Einladungslinks gehören nicht in dieses Datenpaket und nicht ins öffentliche Repository.

## Fehlende Daten und Ausnahmen

Keine automatische Imputation. `null` heißt nicht erhoben/bewertet. Zeitpaare nur aus zwei `submitted` Runden; Qualitätsvergleich darf rechtzeitig gespeicherte Timeout-Teilstände enthalten, bleibt gekennzeichnet. Abbrüche und technische Störungen mit Grund, Zeitpunkt und Bedingung berichten; Originaldaten nicht überschreiben.

Vor Formalstart Ausschlussregeln festlegen: fehlende Einwilligung, vorherige Kenntnis formaler Aufgaben oder erheblicher Regelbruch. Nicht ausschließen, weil jemand schlecht, langsam oder KI-kritisch arbeitet. Reine Studentendaten nicht als Berufsexpertenbefund bezeichnen.

Zwei Rater geben unabhängig ab. Automatisierte Analyse verwendet deren Mittelwerte; nachträglicher Konsens separat dokumentieren. Datensätze ohne zwei vollständige Bewertungen liefern keine Qualitätsdifferenz. Auswertung/Exporte siehe [Betrieb](../04-prototype/operations.md).
