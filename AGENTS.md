# Regeln für Änderungen

Stand des Projekts, Zusammenarbeit mit der Projektleitung, Zugang zum Modell und offene
Arbeit stehen in `CLAUDE.md` (gilt für jeden Coding-Agenten, nicht nur für Claude).

- **Projektphasen und Berechnungen.** Claude liefert strukturierte Vorschläge. Python prüft
  und berechnet. Die Projektleitung entscheidet. Änderungen an Terminen, Aufwand oder
  Anforderungsbezügen anhand eines Falls über Planung, Durchführung, Kontrolle und die
  betroffenen Exporte prüfen. Bei Neuplanung Kalender, stabile IDs, frühere Arbeit und
  wiederholte Übernahmen berücksichtigen.
- **Tabellen in Streamlit.** Bei einem bearbeitbaren Editor jeweils Bearbeiten → Seite
  wechseln → zurück → speichern prüfen. Auch einen inzwischen geänderten Datenstand
  prüfen. Nur bearbeitbare Werte wiederherstellen, abgeleitete Werte neu berechnen. Die
  bestehende Wiederherstellung der Ansicht als Ausgangspunkt verwenden.
- **Lokale Dateien.** Bei Änderungen an Speichern, Import oder Archivierung mit temporären
  Testdaten prüfen. Einen alten gültigen und einen beschädigten Stand berücksichtigen.
  Bei Schreib-, Sperr- oder Parallelitätsänderungen das konkrete Fehlerszenario unter
  Windows prüfen. Bei Fehlern eine Meldung zeigen und vorhandene Daten für die
  Wiederherstellung erhalten, soweit der Speichervorgang das erlaubt.
- **Ausgabe von Text.** Modell- und Nutzereingaben in UI, Markdown und CSV als Text
  behandeln. Je nach Ausgabeformat die vorhandenen Helfer verwenden und Formatgrenzen
  wie Zeilenumbrüche, Tabellenzeichen, Links oder Formelauswertung abdecken.
- **Gleiche Fehler an anderen Stellen.** Vor einer Reparatur nach demselben Muster in allen
  Seiten und Modulen suchen und alle Stellen beheben, am besten im gemeinsamen Helfer.
  Lässt sich das Muster im Quelltext erkennen, eine Regel in
  `tests/test_source_rules.py` ergänzen, damit eine neue Seite es nicht zurückbringt.
- **Eine Quelle je Rechengröße.** Arbeitstage, Puffer, Enden und Verzug nur über die
  vorhandenen Funktionen rechnen (`working_shift` und Verwandte), nicht neu auf einer Seite.
- **Oberfläche.** Vor dem PR prüfen: Kontrast mindestens 4,5 : 1, deutsche Zahlen- und
  Datumsformate, 375 px Breite ohne waagrechtes Scrollen, Startseite und READMEs nennen
  neue Seiten.
- **Größe von PRs.** Möglichst unter etwa 800 geänderten Zeilen. Die großen PRs (18, 25, 42)
  brauchten jeweils eigene Korrekturen nach dem Review.
- **Pull Requests.** Bei gestapelten PRs Basis, Blocker und Merge-Reihenfolge im PR nennen.
  Bei geänderter Basis den integrierten Stand prüfen und den geprüften Commit angeben.
  Reparaturen mit dem ursprünglichen PR und einem Regressionstest verknüpfen, sofern
  der Fehler automatisiert reproduzierbar ist.
- **Prüfnachweis.** Offline-Tests, manuelle Browserprüfung und einen echten Provider-Aufruf
  getrennt angeben. Beim Ändern einer Phase die betroffenen Statusangaben in beiden
  READMEs und im Lebenszyklusdokument prüfen. Für GitHub Pages bei Änderungen am Build
  oder Einstieg die erzeugte Startseite und betroffene Links prüfen.
