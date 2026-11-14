# Zusammenarbeit im Projektteam

## Ein Arbeitspaket = ein Issue

Die Vorlage nach Aufgabe wählen: Recherche, Experiment oder Arbeitspaket. Jedes Issue enthält Fragestellung/Ziel, vorgesehenen Lead, konkrete Datei/Abgabe, Abnahmekriterien und Meilenstein. Lead-Namen sind Vorschläge, bis die Person zusagt; GitHub-Assignees erst bei verifiziertem Benutzerkonto setzen.

Bereiche: `area:project`, `area:research`, `area:experiment`, `area:prototype`, `area:results`. Offene Entscheidungen zusätzlich mit `needs:decision` kennzeichnen. M1 = Design, M2 = Pilot/Freigabe, M3 = Erhebung, M4 = Auswertung/Abgabe. Es gibt noch keine bestätigten Kalenderfristen.

## Beiträge

- Kurze Branches, z. B. `research/pm-baseline`, `experiment/pilot-review`, `prototype/export-fix`.
- Im Pull Request Problem, Ergebnis, Quellen/Validierung und verbleibende Entscheidungen nennen.
- Eine andere Person prüft. Recherche wird auf Aussage und Methodik geprüft, nicht nur auf Rechtschreibung.
- Kleine Änderungen klein halten. Weder bestehende Arbeit überschreiben noch den ganzen Prototyp ohne Bedarf umbauen.
- Nach Review zusammenführen, Issue schließen und relevante Entscheidung verlinken. Änderungen nach Studien-Freeze erfordern eine neue Protokollversion; keine stillen Anpassungen während der Erhebung.

## Quellen und KI-Nutzung

Quelle immer am konkreten Befund verlinken. Wissenschaftliche Studie, Berufs-/Praxisbericht und Produktwerbung unterscheiden. Fremde PDFs und Kursmaterialien nicht pauschal neu hochladen; Link/DOI und eigene Zusammenfassung genügen in der Regel. Volltexte nur mit geklärter Erlaubnis.

KI darf beim Suchen/Strukturieren helfen. Verwendete Literatur, Zahlen und Zitate müssen am Original geprüft werden. Modellantworten sind keine wissenschaftlichen Quellen. Bei wesentlicher KI-Unterstützung in der Methodik beschreiben, wofür sie genutzt und wie sie geprüft wurde.

## Daten

Keine PII, Schlüssel, Einladungslinks oder Ergebnisdateien in Issues/PRs. `data/` und `private/` sind ignoriert, trotzdem vor `git add` prüfen. Öffentliche Pilotfälle nicht unverändert als geheime formale Testaufgaben verwenden. Teilnahme-/Kontaktlisten außerhalb des Repositorys speichern.

## Definition of Done

- Ergebnis liegt am vereinbarten Ort und ist vom Einstieg aus verlinkt.
- Quellen bzw. Prüfnachweise sind nachvollziehbar; Annahmen und offene Punkte sind markiert.
- Abnahmekriterien des Issues sind erfüllt.
- Bei Code: passende Tests und vorhandene Gesamttests bestanden. Bei Dokumenten: Links prüfen.
- Kein „fertig“ für fehlenden Live-Pilot, ausstehende Rekrutierung oder nicht erhobene Ergebnisse.
