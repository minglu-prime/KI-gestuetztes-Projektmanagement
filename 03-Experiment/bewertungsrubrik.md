# Bewertungsrubrik (Entwurf zu Issue #7)

> **Entwurf, von der Gruppe zu bestätigen.** Die Kriterien und Höchstpunkte sind die der Auswertung (`analysis.CAPS`); die Ankerbeschreibungen sind ein Vorschlag und werden in der Kalibrierung geschärft ([`pilot-checkliste.md`](pilot-checkliste.md)). Fachliche Referenzlösungen der formalen Fälle bleiben privat (#6).

Jede abgegebene Runde wird von zwei Ratern unabhängig bewertet. Die Rater sehen nur `rating_id`, Fall, Plan und Risiken, nicht ob mit KI gearbeitet wurde und nicht wer es war.

## Aufgabe 1: Basisplan (0–50)

| Kriterium | Höchstpunkte | Voll | Teilweise | Keine |
|---|---:|---|---|---|
| Abhängigkeiten | 20 | Alle Pakete mit Start und Ende; jeder Vorgänger endet am Vortag oder früher | Einzelne Verstöße oder fehlende Pakete | Reihenfolge nicht erkennbar |
| Ressourcen | 15 | Keine Ressource hat zwei Pakete gleichzeitig; Integration hat Elektronik und Software gleichzeitig | Ein Konflikt, oder die Doppelressource fehlt | Mehrere Konflikte, Ressourcen fehlen |
| Meilensteine | 15 | Drei sinnvolle Meilensteine mit Tag; der Zieltermin ist geprüft und Abweichungen sind genannt | Weniger als drei oder ohne Tag | Keine Meilensteine |

## Aufgabe 2: Risiken und Änderung (0–50)

| Kriterium | Höchstpunkte | Voll | Teilweise | Keine |
|---|---:|---|---|---|
| Risiken erkennen | 20 | Mindestens drei Risiken, jedes mit Beleg aus der Änderung oder den Regeln | Risiken ohne Beleg oder nur allgemein | Keine fallbezogenen Risiken |
| Priorisieren | 15 | Rangfolge mit Begründung nach Auswirkung auf Termin, Kosten, Qualität | Rangfolge ohne Begründung | Keine Priorisierung |
| Maßnahmen | 15 | Je Risiko eine Maßnahme mit verantwortlicher Rolle; aktualisierte Termine auf Basis des gelieferten Ausgangsplans; begründete Entscheidung zur Expressoption; Eskalation, wo der Zieltermin oder das Budget betroffen ist | Maßnahmen ohne Verantwortliche oder ohne aktualisierte Termine | Keine Maßnahmen |

Punkte innerhalb eines Kriteriums sind ganze Zahlen von 0 bis zum Höchstwert. **Entscheidung der Gruppe:** feste Zwischenstufen (z. B. 0 / ½ / voll) oder freie Punkte?

## Schwere Fehler (Anzahl je Antwort)

Ein schwerer Fehler macht den Plan in der Praxis unbrauchbar oder führt zu einer falschen Entscheidung. Er wird zusätzlich zu den Punkten gezählt (`severe_errors`):

1. Test oder Freigabe entfällt (harte Bedingung des Falls).
2. Eine Ressource ist an einem Tag für zwei Pakete eingeplant, oder ein Paket startet vor dem Ende seines Vorgängers, **und** das ändert den Endtermin.
3. Mehr Geld als Kostenbasis plus freigegebene Reserve, ohne eine Sponsorentscheidung zu verlangen.
4. Erfundene Fakten, Freigaben oder Ressourcen (etwa eine Vertretung, Überstunden), die der Fall ausschließt.
5. Eine Terminverschiebung über den Zieltermin hinaus ohne Eskalation.

## Kalibrierung und Abweichungen

1. Vor der formalen Bewertung: Beide Rater bewerten dieselben mindestens zwei Pilotantworten.
2. Abweichung je Antwort vergleichen (`rater_disagreements`: absolute Differenz der Gesamtpunkte).
3. Besprechen, Anker schärfen, Ergebnis der Kalibrierung datiert notieren.
4. In der formalen Bewertung: Beide Bewertungen bleiben im Original gespeichert. **Entscheidung der Gruppe:** Ab welcher Differenz eine gemeinsame Nachbewertung, und welche Zahl dann in die Auswertung geht (Mittelwert der Originale oder Konsens)? Die Auswertung rechnet heute mit dem Mittelwert beider Originalbewertungen.
5. Die Zuordnung zu Bedingung und Person (`private/key.json`) wird erst nach Abschluss beider Bewertungen geöffnet.

Eine Antwort, die wegen Zeitablauf unvollständig ist (`timed_out`), wird ebenso bewertet; fehlende Teile ergeben keine Punkte. Im Bericht steht sie gesondert.
