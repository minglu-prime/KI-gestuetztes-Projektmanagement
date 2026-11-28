# Lebenszyklus eines Softwareprojekts im PM-Agent

Dieses Dokument beschreibt, wie der PM-Agent ein Softwareprojekt von der Idee bis zur nächsten
Iteration begleitet. Umgesetzt sind alle zehn Phasen, die Ansichten Leitung und Team sowie der
optionale Effizienzvergleich (Stand 27.11.2026, nach PR 111).

## Ein Prinzip für jede Phase

Jede Phase besteht aus denselben drei Teilen. So muss man das System nur einmal verstehen:

| Teil | Wer | Was |
|---|---|---|
| Ergebnis | **AGENT** entwirft | ein festes Datenformat (pydantic), eingereicht über ein Werkzeug (`tools.Submission`) |
| Prüfung | **PYTHON** prüft | feste Regeln, vor allem: Lässt sich jedes Ergebnis auf das Ergebnis der Phase davor zurückführen? Was nicht passt, geht mit Begründung an den Agenten zurück. |
| Freigabe | **DU** entscheidest | die Projektleitung ändert das Ergebnis und gibt es frei. Ändert sich danach etwas davor, gilt die Freigabe nicht mehr („seit der Freigabe geändert“). |

Fakten trägt der Mensch ein: Termine, Team, Fortschritt, Testergebnisse, Störungen. Der Agent
schreibt Entwürfe und Bewertungen, rechnet aber nie selbst. Jede Zahl rechnet Python.

Die Freigaben sind **weich**: Eine Phase darf übersprungen werden. Der Projektpfad über jeder
Seite zeigt sie dann gestrichelt mit „nicht freigegeben“, und was auf ihr aufbauen würde,
arbeitet ohne sie (zum Beispiel plant die Planung ohne Anforderungen wie bisher).

## Ansichten und Oberfläche

- **Ansichten Leitung und Team (PR 110):** Über den Umschalter „Ansicht“ links im Menü wechseln
  Projektleitung und Teammitglieder ohne Anmeldung (die Ansicht ordnet Seiten, sie schützt keine
  Daten). In der Ansicht **Team** pflegt jedes Mitglied unter **Mein Bereich** seine eigenen
  Fähigkeiten, Wochenstunden, Abwesenheiten und den Stand seiner Aufgaben; **Projektstand** zeigt
  allen die Kennzahlen und Prognose des Projekts. Die Projektleitung sieht Team (Planung) und
  Fortschritt (Durchführung) nur lesend.
- **Startseite, Ergebniszeile und Agentenlauf (PR 107–109):** Prüfseiten beginnen mit einer
  Ergebniszeile (`ui.verdict`); die Startseite zeigt den Projektstand ohne rote Ergebniszeile in
  vier Kacheln (Aufgaben, Fortschritt, Im Verzug, Voraussichtliches Ende) und öffnet für
  Erstbesucher mit einer kurzen Eröffnungsanimation (ohne Bewegung bei `prefers-reduced-motion`).
  Während ein Agent arbeitet, zeigt `ui.Track` über dem Statuskasten jede Runde auf einer
  Laufbahn mit grünen und goldenen Punkten bis zur Zielfahne.
- **Effizienzvergleich (PR 111):** Auf den vier Hauptseiten (Planung, Durchführung, Kontrolle,
  Abschluss) lässt sich optional eine strukturierte Bewertung mit vs. ohne Agent erfassen
  (`ui.comparison_card`, lokal in `logs/agent_vergleich.csv`, ergänzt um den letzten gültigen
  Agentenlauf der Phase); die Kontrolle (Reiter „Agent und Bericht“) fasst alle vier Phasen
  zusammen und bietet einen CSV-Export.

## Die Phasen

| # | Phase | Ergebnis | Prüfung durch Python | Stand |
|---|---|---|---|---|
| 1 | Projektauftrag | Ziel, Nutzen, Umfang und Nicht-Umfang, Beteiligte als Rollen, Erfolgskriterien K1 …, Rahmenbedingungen | eindeutige IDs der Erfolgskriterien | umgesetzt |
| 2 | Anforderungen (PRD) | Anforderungen R1 … mit User Story, Priorität Muss/Soll/Kann, Akzeptanzkriterien R1.1 …, zugehörigen Erfolgskriterien | jedes Erfolgskriterium abgedeckt; nur bekannte genannt; mindestens eine Muss-Anforderung | umgesetzt |
| 3 | Entwurf | Komponenten, Schnittstellen (Anbieter, Nutzer, Eingabe, Ausgabe, Fehler), Abläufe als Schritte | jeder Beteiligte eines Ablaufs ist eine bekannte Komponente; jede Schnittstelle kommt in einem Ablauf vor; jede Muss-Anforderung hat einen Ablauf. Das Sequenzdiagramm zeichnet Python aus den Schritten, nicht der Agent. | umgesetzt (Design: [entwurf-design.md](entwurf-design.md)) |
| 4 | Planung | Team aus „Mein Bereich“ (nur lesend); Aufgaben mit Aufwand, Zuweisung, Abhängigkeiten und den Anforderungen, denen sie dienen; je Projektwoche ein vorführbares Ergebnis; optionaler Effizienzvergleich | unbekannte Anforderung = Fehler; Anforderung ohne Aufgabe = Warnung; dazu Termine, Auslastung, Puffer; `set_absence` weist Pläne zurück, die durch die Abwesenheit nach der Deadline enden (sofern dem Team die Stunden reichen); jede Projektwoche mit Arbeit hat eine Demo, deren Aufgaben bis Freitag fertig sind (Warnungen) | umgesetzt |
| 5 | Durchführung | Status, Fertigdatum, Ist-Stunden, Rest je Aufgabe (trägt jedes Teammitglied in „Mein Bereich“ ein, für die Leitung nur lesend); Statusbericht und Arbeitspaketbeschreibungen; optionaler Effizienzvergleich | jede Aufgabe im Verzug hat einen nächsten Schritt; liegt die Prognose nach der Deadline, nennt die Zusammenfassung ihr Datum | umgesetzt |
| 6 | Kontrolle und Wochenrückblick | Sechs Reiter (Stand, Prognose, Plan und Ist, Kennzahlen, Demos, Agent und Bericht): Plan/Ist, Prognose, Earned Value, Stand je Anforderung, Wochenrückblick (Demo gezeigt?, Ursache, abhakbare Maßnahmen), Übersicht und CSV-Export des Effizienzvergleichs | jede Aufgabe im Verzug hat eine Gegenmaßnahme; jede ausgefallene Demo eine Maßnahme | umgesetzt ([woche-design.md](woche-design.md)) |
| 7 | Test (Integrationstest und Fehlersuche) | Testfälle aus Akzeptanzkriterien und Schnittstellen, Ergebnisse, Fehler mit vermuteter Ursache und Behebungsdatum (`fixed_on`) | jedes Akzeptanzkriterium hat einen Testfall; jede Schnittstelle einen Integrationstest; jeder fehlgeschlagene Test einen offenen Fehlereintrag (nach Behebung: Testfall wiederholen bzw. neuen Fehler erfassen) | umgesetzt ([test-design.md](test-design.md)) |
| 8 | Abschluss | Abnahme je Anforderung (abgenommen oder zurückgestellt mit Grund), Abschlussbericht mit tatsächlichem Ende und verspäteten Aufgaben ([abschlussdatum-design.md](abschlussdatum-design.md)), Lessons Learned | kein offener schwerer Fehler; jede Muss-Anforderung abgenommen oder begründet | umgesetzt ([abschluss-design.md](abschluss-design.md)) |
| 9 | Betrieb | Betriebshandbuch (Bereitstellung, Überwachung, Rücknahme), Störungen | jede Komponente hat Verantwortliche und Überwachung | umgesetzt ([abschluss-design.md](abschluss-design.md)) |
| 10 | Iteration | nächster Backlog: zurückgestellte Anforderungen, offene Fehler, offene Maßnahmen der Rückblicke, Folgen von Störungen | jeder Eintrag nennt seine Herkunft | umgesetzt ([abschluss-design.md](abschluss-design.md)) |

## Ablauf

```mermaid
flowchart LR
  A[1 Projektauftrag] --> B[2 Anforderungen]
  B --> C[3 Entwurf]
  C --> D[4 Planung]
  D --> E[5 Durchführung]
  E --> F[6 Kontrolle und Wochenrückblick]
  F -->|Verzug: Rest umplanen| D
  F --> G[7 Test]
  G -->|Fehler| E
  G --> H[8 Abschluss]
  H --> I[9 Betrieb]
  I --> J[10 Iteration]
  J -->|nächster Backlog| B
```

Jede Woche endet mit einem vorführbaren Ergebnis und einem Rückblick (Phase 6): Was wurde
gezeigt, was nicht, warum, und was ändern wir? Die Maßnahmen landen in der nächsten Iteration.

## So läuft eine Phase ab

Am Beispiel der Anforderungen. Jede andere Phase läuft gleich, nur mit anderem Ergebnis und
anderer Prüfung.

```mermaid
sequenceDiagram
  actor Du as DU (Projektleitung)
  participant Seite as Seite Anforderungen
  participant Agent as AGENT
  participant Python as PYTHON
  participant Datei as data/vorhaben.json
  Du->>Seite: „Anforderungen mit dem Agenten entwerfen“
  Seite->>Agent: Idee, Termine, Projektauftrag
  loop bis die Prüfung annimmt (höchstens 10 Runden)
    Agent->>Python: submit_anforderungen(Entwurf)
    Python-->>Agent: abgelehnt: „K2 deckt keine Anforderung ab“
  end
  Python-->>Seite: angenommen
  Seite->>Datei: Entwurf speichern
  Du->>Seite: Tabelle ändern, „Änderungen speichern und prüfen“
  Seite->>Python: check_requirements
  Python-->>Seite: Fehler und Warnungen
  Du->>Seite: „Anforderungen freigeben“
  Seite->>Datei: Freigabe mit Prüfsumme von Auftrag und Anforderungen
```

## Wo was im Code steht

| Was | Wo |
|---|---|
| Datenformate | `src/pm_agent/models.py` (`Charter`, `Requirement`, `Design`, `Task.requirement_ids`) |
| Speichern, Freigabe, Prüfung, Dokumente der Phasen 1 bis 3 | `src/pm_agent/lifecycle.py`, Vorlagen in `src/pm_agent/templates/` |
| Agentenschleife mit einem Einreichen-Werkzeug | `agent.run_submission` |
| Rückverfolgung im Plan | `planning.check_plan(..., requirements=, covered=)` |
| Stand je Anforderung | `tracking.requirement_progress` |
| Sequenzdiagramme (SVG und Mermaid) | `src/pm_agent/diagram.py` |
| Testfälle, Prüfung der Abdeckung | `lifecycle.check_cases`, `views/testplan.py` |
| Ergebnisse und Fehler | `tracking.record_result`, `record_defect`, `reopen`, `views/testlauf.py` |
| Abnahme, Lessons Learned, Abschlussbericht, Betrieb, nächster Backlog | `src/pm_agent/closing.py`, `views/abschluss.py` (Betrieb und nächster Durchlauf als Reiter) |
| Effizienzvergleich (mit vs. ohne Agent) | `src/pm_agent/comparison.py`, `ui.comparison_card` auf Planung, Durchführung, Kontrolle, Abschluss; Übersicht und CSV-Export auf `views/kontrolle.py` (`logs/agent_vergleich.csv`) |
| Ansicht Team (eigene Daten und Projektstand) | `app.py` (`TEAM`), `views/mein_bereich.py`, `views/projektstand.py`, `ui.forecast_chart` |
| Startseite, Ergebniszeile und Agentenlauf | `views/startseite.py`, `ui.verdict`, `ui.overrun_text`, `ui.Track`, `assets/style.css` |
| Vorbereitungs- und Hauptseiten | `views/auftrag.py`, `views/anforderungen.py`, `views/entwurf.py`, `views/planung.py`, `views/durchfuehrung.py`, `views/kontrolle.py`; Projektpfad in `ui.journey` |
