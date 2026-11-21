# Agentenlauf 21.11.2026: kürzere Agententexte im Vergleich zum 20.11.2026

## Frage

Seit PR 69 nennen die Prompts für jeden Freitext der Agenten eine Länge (etwa ein Satz, 160 bis 240 Zeichen; die Zusammenfassung höchstens drei Sätze, 400 Zeichen). Jedes Einreichungswerkzeug schickt einen zu langen Text zurück, und der Agent kürzt ihn selbst.

Dieser Lauf prüft drei Fragen:

1. Halten die Agenten die Grenzen ein?
2. Kostet die Grenze zusätzliche Runden oder Token?
3. Bleiben die Ergebnisse brauchbar?

## Aufbau

- **Modell:** `gpt-6-sol` über den OpenAI-kompatiblen Endpunkt der Hochschule (Responses API, Reasoning `medium`), wie am 20.11.2026.
- **Eingaben:** dieselben wie am 20.11.2026, alle erfunden:
  - Projekt: Web-App zum Buchen von Lernräumen, Start 09.11.2026, Deadline 18.12.2026.
  - Team: Anna, Ben, Clara.
  - Zwei Änderungswünsche („Backend doppelt so lange“, „Clara 7.–11.12. abwesend“).
  - Durchführung, Kontrolle und Lessons arbeiten auf einer Kopie des übernommenen Beispielprojekts mit Stand 20.11.2026.
- **Ablauf:** 12 Läufe nacheinander, je einer pro Agent:
  - Projektauftrag, Anforderungen, Entwurf, Testplan
  - Planung ohne und mit Anforderungen
  - zwei Umplanungen
  - Durchführung, Kontrolle, Lessons
  - eine Frage im KI-Lab
- **Ablage:** Alle Dateien des Werkzeugs lagen in einem Temp-Ordner. `data/` war vor und nach dem Lauf gleich (SHA-256).
- **Skripte:** `run_agents.py` (Lauf) und `summarize.py` (Auswertung) liegen hier.

## Ergebnisse

Die Zahlen je Lauf stehen in [`ergebnisse.csv`](ergebnisse.csv), Spalte `lauf`: 20.11. oder 21.11. Die CSV enthält nur Zählungen und keinen Text des Modells.

Summe über die 11 Agentenläufe, ohne KI-Lab:

| | 20.11. (ohne Grenze) | 21.11. (mit Grenze) |
|---|---|---|
| Läufe mit Ergebnis | 11 von 11 | 11 von 11 |
| Runden | 21 | 23 |
| Ablehnungen durch Python | 2 | 2 |
| davon wegen Textlänge | – | **0** |
| Dauer | 346 s | 324 s |
| Eingabe-Token | 150 710 | 187 198 |
| Ausgabe-Token | 54 369 | 55 602 |
| Freitexte | 217 | 200 |
| Zeichen in Freitexten | 23 069 | **17 111 (−26 %)** |
| Freitexte über der Grenze | 13 | **0** |

Je Agent, Zeichen in Freitexten (längster Text in Klammern):

| Agent | 20.11. | 21.11. |
|---|---|---|
| Durchführung | 1 598 (562) | 1 169 (250) |
| Kontrolle | 3 582 (250) | 2 292 (152) |
| Lessons | 376 (221) | 250 (126) |
| Planung | 3 547 (153) | 2 767 (131) |
| Planung mit Anforderungen | 3 371 (165) | 3 362 (127) |
| Umplanung (Backend) | 5 054 (253) | 3 362 (127) |

## Befunde

1. **Die Grenzen werden eingehalten, ohne Umweg.** Kein Text lag über seiner Grenze, und kein Lauf wurde wegen Länge zurückgewiesen. Am 20.11. lagen 13 Texte darüber, darunter die Zusammenfassung der Durchführung mit 562 Zeichen. Die Texte sind insgesamt ein Viertel kürzer, die längsten etwa halb so lang.
2. **Keine Mehrkosten durch die Grenze, aber Streuung.**
   - Ausgabe-Token und Dauer sind fast gleich.
   - Die Eingabe-Token stiegen um 24 %. Das kommt aus mehr Runden der Planung (4 statt 2) und der Umplanung mit Abwesenheit (5 statt 4), nicht aus Ablehnungen wegen Länge.
   - Bei einem Lauf je Agent ist das Streuung des Modells, keine Wirkung der Änderung.
3. **Die Pläne bleiben gültig.**
   - Beide Planungen enden am 17.12.2026, einen Arbeitstag vor der Deadline, ohne Fehler und Warnungen.
   - Die Umplanung „Backend doppelt so lange“ verdoppelte die Stunden der Backend-Aufgaben. Das Ende rückt auf den 11.01.2027 (9 Warnungen).
   - Die Abwesenheit trug der Agent mit `set_absence` ein. Er verteilte aber keine Aufgabe um, und das Ende rückt auf den 24.12.2026 (3 Warnungen). Das war am 20.11. ähnlich (21.12.2026).
4. **Inhalt, gelesen in Stichproben:**
   - Begründungen, Feststellungen und Maßnahmen sind kurz und konkret, zum Beispiel: „React 4 und CSS 3 passen zum frühen Browserprototyp.“
   - Die Zusammenfassung der Durchführung übernimmt Zahlen und Daten roh: „Fortschritt bei 0.0“, „2026-11-20“. Das liegt am Prompt bzw. an den übergebenen Kennzahlen, nicht an der Längengrenze.
   - Die drei nächsten Schritte beginnen gleich („klärt bis 2026-11-23 den Verzugsgrund …“).
5. **KI-Lab:** Eine Frage im Pilotmodus wurde beantwortet (4 s). Das Lab hat eigene Prompts und war von der Änderung nicht betroffen; der Lauf zeigt nur, dass der Zugang funktioniert.

## Grenzen

- **Ein Lauf je Agent.** Unterschiede bei Runden, Dauer und Token sind nicht belastbar. Für Aussagen dazu braucht es mehrere Läufe je Agent (z. B. fünf).
- **Gleiche Grenzen in Messung und Werkzeug.** Die Zählung „über der Grenze“ nutzt dieselben Grenzen wie das Werkzeug (`tools.LIMITS`). Am 20.11. galten sie noch nicht; die Zahl zeigt nur, wie oft die alten Texte sie gerissen hätten.
- **Ohne Bewertung durch Fachleute.** Die Qualität der Inhalte ist nur stichprobenartig gelesen.
- **Kein datiertes Modell.** `gpt-6-sol` hat keine datierte Snapshot-ID; ein späterer Lauf kann ein anderes Modell treffen.

## Rohdaten

Die vollständigen Protokolle mit Prompts und Antworten bleiben lokal (`04-Prototyp/pm_agent/logs/lauf-20261121/` und `logs/gpt-6-sol-20261120/`). Protokolle kommen nach der Regel des Repositorys nicht in das öffentliche Repository.

## Wiederholen

Aus dem Wurzelverzeichnis (verbraucht Kontingent):

```
uv run --project 04-Prototyp/pm_agent --env-file 04-Prototyp/pm_agent/.env python 03-Experiment/agentenlauf-2026-11-21/run_agents.py
uv run --project 04-Prototyp/pm_agent python 03-Experiment/agentenlauf-2026-11-21/summarize.py ergebnisse.csv 21.11.=04-Prototyp/pm_agent/logs/lauf-JJJJMMTT
```
