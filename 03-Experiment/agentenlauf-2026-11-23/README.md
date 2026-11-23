# Agentenlauf 23.11.2026: Umplanung bei Abwesenheit und Enddatum in der Durchführung

## Frage

PR 86 hat zwei Agenten geändert:

- `prompts/replanning.md` verlangt nach `set_absence` eine Umverteilung, wenn sonst Deadline oder Puffer reißen.
- `followup.check_summary` schickt eine Zusammenfassung der Durchführung zurück, die bei einer Prognose nach der Deadline das Enddatum nicht nennt; der Prompt `durchfuehrung.md` verlangt das Datum.

Am 21.11.2026 trug die Umplanung Claras Abwesenheit ein, verteilte aber keine Aufgabe um: Das Ende lag am 24.12.2026, nach der Deadline am 18.12.2026. Die Zusammenfassung sagte nur „nach der Deadline“.

Dieser Lauf prüft zwei Fragen:

1. Verteilt der Agent jetzt um, sodass der Plan wieder in die Zeit passt?
2. Nennt die Zusammenfassung jetzt das Enddatum der Prognose?

## Aufbau

- **Modell:** `gpt-6-sol` über den OpenAI-kompatiblen Endpunkt der Hochschule (Responses API, Reasoning `medium`), wie am 20. und 21.11.2026.
- **Eingaben:** die vom 21.11.2026, alle erfunden. Sie werden aus den lokalen Protokollen dieses Laufs gelesen:
  - Plan mit Anforderungen (der Planungslauf ohne Wunsch) und Entwurf
  - Team Anna, Ben, Clara
  - Wunsch „Clara ist vom 7.12. bis 11.12. auf einer Exkursion.“
  - Durchführung auf einer Kopie des übernommenen Beispielprojekts, Stand 20.11.2026. Prognose an diesem Tag: Ende 29.12.2026.
- **Ablauf:** jeder der zwei Agenten dreimal, abwechselnd, also 6 Läufe.
- **Ablage:** Alle Dateien des Werkzeugs lagen in einem Temp-Ordner. `data/` war vor und nach dem Lauf gleich (SHA-256).
- **Skripte:**
  - `run_agents.py`: der Lauf
  - `auswertung.py`: die Zählungen zu den zwei Fragen
  - `../agentenlauf-2026-11-21/summarize.py`: Runden, Token und Dauer

## Ergebnisse

Die Zeilen je Lauf stehen in [`auswertung.csv`](auswertung.csv) (Fragen 1 und 2) und [`ergebnisse.csv`](ergebnisse.csv) (Runden, Token, Dauer). Beide CSV enthalten nur Zählungen und keinen Text des Modells.

### 1. Umplanung bei Abwesenheit

| Lauf | Runden | Aufgaben umverteilt | Planende | Puffer zur Deadline | Warnungen der Prüfung |
|---|---|---|---|---|---|
| 21.11. | 5 | 0 | 24.12.2026 | 4 Arbeitstage zu spät | 3 |
| 23.11. Nr. 1 | 4 | 0 | 24.12.2026 | 4 Arbeitstage zu spät | 3 |
| 23.11. Nr. 2 | 6 | 2 | 18.12.2026 | 0 Arbeitstage | 4 |
| 23.11. Nr. 3 | 4 | 2 | 18.12.2026 | 0 Arbeitstage | 4 |

Dauer 65 bis 112 s, 52 000 bis 96 000 Eingabe-Token je Lauf. Keine Ablehnung durch Python.

### 2. Enddatum in der Zusammenfassung

| Lauf | Runden | Datum 29.12.2026 genannt | zurückgeschickt wegen Datum |
|---|---|---|---|
| 21.11. | 1 | nein | – (Regel gab es noch nicht) |
| 23.11. Nr. 1–3 | je 1 | ja, 3 von 3 | 0 |

Dauer 9 bis 10 s, je 5 968 Eingabe-Token.

## Befunde

1. **Das Enddatum steht jetzt in der Zusammenfassung.** In allen drei Läufen nennt die Zusammenfassung das Datum der Prognose. Die neue Prüfung musste nie eingreifen: Der Prompt allein reichte. Die Prüfung bleibt als Absicherung.
2. **Die Umverteilung klappt nur in 2 von 3 Läufen, und dann knapp und auf Kosten der Fähigkeiten.**
   - Lauf 1 verhielt sich wie am 21.11.: Abwesenheit eingetragen, nichts umverteilt, Ende vier Arbeitstage nach der Deadline. Python nahm den Plan an, weil ein Ende nach der Deadline nur eine Warnung ist.
   - Die Läufe 2 und 3 gaben je zwei von Claras Aufgaben an Anna und Ben. Der Plan endet genau am Tag der Deadline, ohne Puffer.
   - Dabei bekamen Anna und Ben Aufgaben, für die ihnen eine verlangte Fähigkeit fehlt (Testing, UX). Der Prompt verlangt „passende Skills“. Python meldet das als Warnung und nimmt den Plan trotzdem an.
3. **Drei Läufe sind wenige.** Die Anteile (2 von 3, 3 von 3) zeigen eine Richtung, keine Rate.

## Folgerung

- Durchführung: erledigt.
- Umplanung: Der Prompt allein reicht nicht. Seit diesem Lauf umgesetzt (Entscheidung der Projektleitung, 23.11.2026): Nach `set_absence` weist `submit_plan` einen Plan zurück, den die Abwesenheit hinter die Deadline schiebt. Der Agent bekommt den Grund und korrigiert, wie bei anderen Ablehnungen. Ein Ende genau an der Deadline und fehlende Fähigkeiten bleiben Warnungen, ebenso ein Plan, der auch ohne die Abwesenheit zu spät ist. Ein echter Lauf mit dieser Regel steht aus.

## Grenzen

- Erfundenes Beispielprojekt, ein Modell, ein Tag.
- Die Durchführung am 21.11. lief auf dem damaligen Stand des Beispielprojekts. Der Vergleich nimmt an, dass er sich seitdem nicht geändert hat.

## Wiederholen

Aus dem Wurzelverzeichnis; der Lauf kostet Kontingent (nur auf Wort der Projektleitung):

```bash
uv run --project 04-Prototyp/pm_agent --env-file 04-Prototyp/pm_agent/.env python 03-Experiment/agentenlauf-2026-11-23/run_agents.py
uv run --project 04-Prototyp/pm_agent python 03-Experiment/agentenlauf-2026-11-23/auswertung.py auswertung.csv BASE=04-Prototyp/pm_agent/logs/lauf-20261121 23.11.=04-Prototyp/pm_agent/logs/lauf-JJJJMMTT
uv run --project 04-Prototyp/pm_agent python 03-Experiment/agentenlauf-2026-11-21/summarize.py ergebnisse.csv 23.11.=04-Prototyp/pm_agent/logs/lauf-JJJJMMTT
```

Die Eingaben kommen aus den Protokollen vom 21.11.2026 in `04-Prototyp/pm_agent/logs/lauf-20261121/`, die nicht im Repository liegen.
