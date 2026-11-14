# Öffentliche Bewertungsrubrik — Pilotentwurf

Stand: Pilot-1. Materialien stammen aus `cases.json`; Bewertende erhalten die jeweiligen Fallmaterialien, nicht die Bedingungen oder Teilnehmerkennungen. Beide Rater bewerten unabhängig. Vor Formalstart an mindestens zwei Pilotantworten kalibrieren.

## Rubrik (100 Punkte)

Ganze Punkte verwenden. Zwischenwerte bei teils erfüllten Ankern mit kurzer Begründung zulässig. Sprachstil, Textlänge und vermeintliche KI-Herkunft nicht bewerten. Fehlende Inhalte erhalten nur im betroffenen Kriterium keine Punkte; dieselbe Ursache nicht mehrfach als separaten schweren Fehler zählen.

| JSON-Feld | Punkte | Bewertungsanker |
|---|---:|---|
| dependencies | 20 | 9 Pakete mit korrekten Dauern: 8; alle Vorgänger und kein Start am Vorgänger-Endtag: 8; konsistente inklusive Tagesrechnung: 4 |
| resources | 15 | Verantwortliche vollständig: 5; keine Überlastung: 5; Integration belegt Elektronik und Software: 5 |
| milestones | 15 | Drei prüfbare Meilensteine mit Daten: 6; Pflichtprüfung/Freigabe enthalten: 5; Zieltermin und realistische Reserve erkennbar: 4 |
| risk_identification | 20 | Lieferverzug: 4; Integrationsressource nicht verfügbar: 4; fehlender Kalibriernachweis: 4; QA-Lücke T13: 4; unbelegte Termin-Garantie: 4 |
| prioritization | 15 | Belegte Auswirkung auf Termin/Qualität: 5; begründete Priorisierung: 5; Fakten/Annahmen getrennt und Verantwortliche benannt: 5 |
| measures | 15 | Machbarer neuer Plan: 7; Expressoption fachlich/kostenbezogen begründet: 4; Umgang mit unbelegter Garantie/Eskalation: 4 |

`severe_errors`: Anzahl unterschiedlicher schwerer Fehler, z. B. Pflichtprüfung ausgelassen, Ressource an gesperrten Tagen eingeplant, unbelegte Freigabe als Tatsache, falsches Ergebnis durch verletzte Vorgänger. Ein vages oder fehlendes Detail ist nicht automatisch ein schwerer Fehler. In `notes` jeden Fehler mit Textstelle belegen.


Die konkreten Referenzantworten bleiben außerhalb dieses öffentlichen Repositorys. Die Rubrik bezieht sich auf die Pilotfälle; formale Varianten vor Freeze fachlich prüfen und separat kalibrieren.

