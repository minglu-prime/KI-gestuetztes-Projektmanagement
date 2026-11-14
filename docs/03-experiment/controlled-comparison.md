# So richten wir den kontrollierten Vergleich ein

## 1. Was wird verglichen?

**Kontrollbedingung M:** Mensch arbeitet ohne generative KI. **Interventionsbedingung K:** Mensch arbeitet mit unserem KI-Assistenten, prüft Vorschläge und entscheidet selbst. Beide erhalten identische Materialstruktur, Editor, Instruktionen und Zeit. Die Intervention umfasst Modell, Prompt und Assistenzworkflow gemeinsam; ein Erfolg ist kein Nachweis für jedes KI-Produkt.

Es gibt zwei Aufgabentypen: (1) Basisplan mit Zuständigkeiten und Meilensteinen, (2) Risiken/Änderungen mit begründetem neuem Plan. Pro Runde stehen insgesamt 25 Minuten zur Verfügung. Erst Basisplan verbindlich sperren, dann den vorgegebenen Ausgangsplan und Änderungsmaterial für Aufgabe 2 öffnen. Dadurch verrät Aufgabe 2 nicht vorher die Lösung von Aufgabe 1.

## 2. Warum kein Team „mit KI“ gegen ein anderes „ohne KI“?

Bei einer kleinen Stichprobe könnten unterschiedliche Erfahrung und Arbeitsgeschwindigkeit die Gruppen dominieren. Deshalb schlagen wir einen **Within-Person-Vergleich** vor: jede Person bearbeitet beide Bedingungen. Andere Fälle verhindern, dass dieselbe konkrete Lösung einfach wiederholt wird; Reihenfolgeausgleich begrenzt Übungs-/Ermüdungseffekte. Lerntransfer zwischen ähnlichen Fällen bleibt eine Einschränkung.

Eine reine Gruppenteilung wäre eine Alternative, wenn Wiederholung die zweite Aufgabe unbrauchbar macht. Dann müssten ausreichend viele Personen zufällig aufgeteilt und Vorwissen berücksichtigt werden. Diese Alternative ist in unserem Demonstrator nicht implementiert und erfordert eine neue Designentscheidung; nicht beide Designs vermischen.

## 3. Vier Sequenzen

| Sequenz | Runde 1 | Runde 2 | Ziel bei 12 Personen |
|---|---|---|---:|
| S1 | M + Fall A | K + Fall B | 3 |
| S2 | K + Fall B | M + Fall A | 3 |
| S3 | M + Fall B | K + Fall A | 3 |
| S4 | K + Fall A | M + Fall B | 3 |

Die Zahlen sind Zuteilungsziele, keine bereits rekrutierten Personen. Bei 8 Personen zwei pro Sequenz anstreben; dies ist keine statistisch begründete Power-Schwelle.

1. Julian rekrutiert, Mia vergibt anonyme Kennungen und erfasst PM-/KI-Erfahrung. Teammitglieder dienen nur dem Vorversuch.
2. Mit `manage.py enroll` werden Sequenzen in zufälligen Viererblöcken zugeteilt; Seed dokumentieren. Kennungen nach Ankunft verwenden, nicht nach erwarteter Leistungsfähigkeit.
3. Falls vorab ausreichend Personen pro Erfahrungsschicht vorliegen, separate Blöcke mit unterschiedlichen Seeds und ID-Bereichen durchführen. Die Software schichtet nicht selbst.
4. Unausgewogene Erfahrung, fehlende Personen und Abweichungen dokumentieren. Keine ergebnisgetriebene Umverteilung.

## 4. Was bleibt konstant?

| Konstante | Umsetzung |
|---|---|
| Fallkomplexität | Zwei Varianten mit vergleichbaren Paketen, Abhängigkeiten, Ressourcenengpässen und Textumfang; im Pilot prüfen |
| Werkzeug | Gleicher Editor, Materialdarstellung und Export; AI nur in K verfügbar |
| Informationszugang | Kein Web, keine weiteren KI-Tools; gleicher normaler Taschenrechner erlaubt |
| Zeit | Server startet bei Aufgabenöffnung, kein Reset durch Refresh; KI-Warten und Kontrolle zählen mit |
| KI-Konfiguration | Ein getesteter Modell-Snapshot, fester Systemprompt, gleiche Limits; Teilnehmerfragen werden protokolliert |
| Anleitung | Gleiche Übung und Bedienhinweise, keine fachliche Hilfestellung während der Runde |
| Bewertung | Dieselbe vorab festgelegte Rubrik, zwei unabhängige Rater, Bedingungslabels ausgeblendet |

Der Server verhindert eigene KI-Aufrufe im manuellen Modus. Andere Websites/Tools kann er nicht erkennen; dafür betreut durchführen und Regelabweichungen abfragen.

## 5. Was würde das Ergebnis verfälschen?

- Gleichen Fall zuerst selbst und danach mit KI lösen: Vorkenntnis wird mit KI-Effekt verwechselt.
- Verschiedene Vorlagen/Materialien zwischen M/K: misst auch Interface-/Informationsunterschiede.
- Nur Generierungszeit messen: unterschlägt Lesen, Prüfen und Korrigieren.
- Sprachlich schöne Texte als richtig bewerten: Abhängigkeiten, Ressourcen und Fakten müssen fachlich stimmen.
- Nach ersten Ergebnissen Rubrik, Fälle oder Ausschlüsse ändern: kann Ergebnisse systematisch verzerren.
- Timeout oder fehlende Bewertung als erfolgreiche Nullzeit/Nullpunkte behandeln: getrennt berichten.
- Öffentlich gelesene Demofälle als geheime formale Tests einsetzen: vorherige Kenntnis kontrollieren, neue private Varianten verwenden.

## 6. Auswertung

Zeitdifferenz pro vollständigem Paar = Zeit K − Zeit M; negative Werte bedeuten in diesem Paar schneller. Qualität K − M getrennt für Plan/Risiko/gesamt. Timeouts und Anbieterfehler nach Bedingung separat zeigen. Reihenfolge, Fall und Vorwissen beschreiben; kleine Stichprobe begrenzt Interpretationen. Der [Messplan](measurement.md) und das [Protokoll](protocol.md) legen Details fest.
