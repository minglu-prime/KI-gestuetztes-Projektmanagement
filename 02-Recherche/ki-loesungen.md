# KI-Lösungen, empirische Studien und Modellwahl

Zu Issue #3 · Stand: 21.11.2026 · Status: **Entwurf, von der Gruppe zu bestätigen**

Frage: Welche KI-Funktionen unterstützen die beiden Lab-Aufgaben, und was ist unabhängig
gemessen statt nur beworben? Quellen-IDs (L…) verweisen auf `literaturregister.md`; dort steht
auch, ob Volltext oder nur Abstract/Seite gelesen wurde.

## 1. KI-Funktionen je Aufgabe

| Funktion | Aufgabe | Beworben (Hersteller) | Unabhängig gemessen |
|---|---|---|---|
| Aufgabenliste / Strukturplan vorschlagen | 1 | Copilot erzeugt bis zu 100 Aufgaben mit Dauer, Aufwand und Start [L19] | Qualitativer Vergleich eines GPT-4-Plans mit dem Plan einer erfahrenen PM: ergänzen sich [L02] |
| Abhängigkeiten und Ressourcen einhalten | 1, 2 | Copilot erzeugt **keine** Abhängigkeiten und keine Zuständigen [L19, L20] | Benchmark: bei reinen Vorgängerbeziehungen nahe am Höchstwert, bei zusammenwirkenden Randbedingungen deutlich schwächer und je Modell sehr verschieden [L05] |
| Risiken identifizieren und Maßnahmen vorschlagen | 2 | Copilot schlägt Risiken und Maßnahmen vor; braucht erfasste Ist-Daten [L19] | In verblindeter Bewertung höher bewertet als Fachleute, aber weniger praxisnah und spezifisch [L03]; Auslassungen und Fehleinschätzungen von Wahrscheinlichkeit und Auswirkung untersucht [L04, nur Abstract] |
| Änderungsantrag bewerten (Wirkung auf Termin, Budget) | 2 | in den gelesenen Herstellerquellen nicht beschrieben | **keine Studie gefunden** |
| Statusbericht schreiben | – | Copilot erzeugt Berichte aus Projektdaten [L19] | nicht gesucht (nicht Teil des Labs) |

Lücke: Für die Bewertung einer Änderung gegen einen bestehenden Basisplan (Kern von Aufgabe 2)
fand die Startsuche keine empirische Studie. Das Experiment der Gruppe kann hier eigene Daten
liefern.

## 2. Empirische Studien

| ID | Methode | Stichprobe | Aufgabe | Modell | Ergebnis | Grenzen |
|---|---|---|---|---|---|---|
| L02 | qualitativer Vergleich, PMBOK-Wissensgebiete | 1 Plan von einer PM (PMP, 10 Jahre Erfahrung) vs. 1 Plan von GPT-4 | Projektplan für eine App | GPT-4 (ChatGPT) | Stärken und Schwächen auf beiden Seiten; KI-Plan bei Risiken strukturierter; Plan als Startpunkt, Mensch verfeinert | ein Fall, Autoren bewerten selbst, Prompts iterativ durch die Autoren (Abschn. 3, 6) |
| L03 | Mixed Methods, verblindete Peer-Bewertung (Skala 1–10) | 16 Fachleute, 19 Gutachtende; 1 KI-Antwort | Risikoidentifikation, -analyse, -steuerung, finnischer Bau | GPT-4 (April 2023) | KI Ø 8,6 vs. Menschen Ø 5,7; keine Person über dem KI-Schnitt; Maßnahmen der KI weniger praxisnah und spezifisch | kleine Stichprobe, ein Land, eine Antwort, simulierter Fall (Abschn. 5.3) |
| L04 | Mixed Methods, Interviews, Fallstudie | nicht auf der Seite genannt | Risikoanalyse, Straßenprojekt Irland | ChatGPT-4 (laut Abstract) | positives Nutzererleben; erfahrene Fachleute vermissen Kontext; Qualität der Projektbeschreibung wichtiger als Prompt-Geschick | nur Abstract gelesen |
| L05 | Benchmark mit Prüfer (CP-SAT), Einzelprompt | je 2 000 Instanzen pro Datensatz; 9 Modelle | ressourcenbeschränkte Terminplanung (RCPSP), nur Machbarkeit | u. a. GPT-5, o3, Gemini 2.5 Pro, Grok 4 | reine Vorgängerbeziehungen: Spitzenmodelle WAUC 0,97; mit Ausfallzeiten, Zeitfenstern, Ausschlüssen: GPT-5 0,92, Gemini 2.5 Pro 0,29, Grok 4 0,18; realer Fall (Rechenzentrumsumzug): bestes Modell 0,66 | Preprint, nicht begutachtet; keine Optimierung; kein Mensch im Ablauf |
| L06 | präregistriertes Feldexperiment, 3 Gruppen | 758 Beratende | 18 Beratungsaufgaben „innerhalb“ und 1 Aufgabe „außerhalb“ der KI-Fähigkeit | GPT-4 | innerhalb: 12,2 % mehr Aufgaben, 25,1 % schneller, über 40 % höhere Qualität; außerhalb: 19 Prozentpunkte seltener richtig (84,5 % vs. 60–70 %) | eine Firma, Stand 2023, Arbeitspapier |
| L07 | präregistriertes Online-Experiment | 444 Berufstätige mit Hochschulabschluss | berufsnahe Schreibaufgaben | ChatGPT | Zeit −10 min (37 %, Kontrolle 27 min); Bewertung +0,45 SD | kurze, kontextarme Aufgaben; Arbeitspapier |
| L13 | systematischer Review (PRISMA) | Zahl im Abstract nicht genannt | generative KI im IT-Projektmanagement | überwiegend GPT | Feld in explorativer Phase; meist Prompt Engineering | nur Abstract gelesen |

Lesart für das Projekt:

- Die zwei PM-Studien mit Volltext (L02, L03) zeigen **Qualität eines Entwurfs**, nicht die
  Leistung eines Menschen **mit** KI. Das Lab misst genau diese zweite Größe (Runde mit KI gegen
  Runde ohne KI).
- Keine der Studien prüft Pläne automatisch gegen Abhängigkeiten und Ressourcen. L05 tut das,
  aber ohne Menschen. Die Kriterien B2, B3 und R5 in `baseline.md` decken diese Lücke ab.

## 3. Werkzeuge auf einem Maßstab

Maßstab (aus den Abnahmekriterien von Issue #3): Zugang für die Gruppe, Funktion für Aufgabe
1 und 2, deutsche Qualität, Latenz, Kostenrahmen, Protokollierbarkeit im Lab, unabhängige
Evidenz. Werte: **ja** / **nein** / **offen** (nicht geprüft), jeweils mit Beleg.

| Kriterium | Endpunkt der Hochschule mit `gpt-6-sol` im KI-Lab | Microsoft Copilot for project (Dynamics 365) |
|---|---|---|
| Zugang für die Gruppe | **ja**: Schlüssel vorhanden, lokal in `.env` (nicht im Repository) | **offen**: braucht einen Dynamics-365-Mandanten; in der Gruppe nicht bekannt [L19] |
| Funktion Aufgabe 1 | **ja**: freie Antwort auf den Fall, `prompt.txt` | **teilweise**: Aufgabenliste ohne Abhängigkeiten und Zuständige [L20] |
| Funktion Aufgabe 2 | **ja**: freie Antwort; Ausgangsplan im Fall | **nein** für den Lab-Fall: Risiken erst mit erfassten Ist-Daten [L19] |
| Deutsche Qualität | **offen**: Agentenläufe auf Deutsch am 20. und 21.11.2026 liefen ohne Fehler (`03-Experiment/agentenlauf-2026-11-21`); Qualität der Texte nicht bewertet | **offen**: „für verschiedene Sprachen geprüft“, Liste nicht auf der Seite [L20] |
| Latenz | **offen**: eine Lab-Frage am 21.11.2026 in 4 s (`ergebnisse.csv`, Zeile `ki_lab`); ein Lauf ist kein Maß | **offen** |
| Kostenrahmen | **offen**: Kontingent der Hochschule; Obergrenze für die Studie nicht festgelegt | **offen**: Lizenz nicht auf den gelesenen Seiten |
| Protokollierbarkeit im Lab | **ja**: `lab.py` speichert je Aufruf Eingabe, Antwort, zurückgemeldeten Modellnamen (`model_returned`), Token und Zeit | **nein**: außerhalb des Labs |
| Unabhängige Evidenz | **nein**: keine Studie zu diesem Modell | **nein**: Nutzerstudien erwähnt, ohne Zahlen [L20] |

Atlassian „AI Work Breakdown“ war gesucht, die Seite aber nicht lesbar; nicht bewertet.

## 4. Modellwahl

**Entscheidung:** Das KI-Lab nutzt den OpenAI-kompatiblen Endpunkt der Hochschule mit dem
Modell `gpt-6-sol` (Responses API).

Begründung:

- Einziger Kandidat mit Zugang, beiden Aufgaben und vollständigem Protokoll (Tabelle oben).
- Gleiche Bedingungen für alle Teilnehmenden: ein Modell, ein Prompt, Reasoning `medium`.

**Snapshot:** Am 21.11.2026 hat die Projektleitung entschieden, dass die formale Studie keinen
datierten Modell-Snapshot verlangt. Stattdessen wird je Aufruf der vom Dienst zurückgemeldete
Modellname festgehalten (`model_returned` in `lab.py`). Begründung und Wortlaut:
[`../01-Projektplanung/entscheidungen.md`](../01-Projektplanung/entscheidungen.md).

Folgen für die Auswertung:

- Weicht `model_returned` innerhalb der Studie ab, gelten die betroffenen Runden als eigene
  Gruppe und werden getrennt berichtet.
- `freeze` in `lab.py` verlangt derzeit noch eine datierte ID. Die Anpassung gehört zu Issue #9
  und wird dort umgesetzt, nicht hier.

## Offen

- Deutsche Qualität und Latenz mit mehreren Probeläufen auf beiden Fällen messen (Kontingent:
  nur auf Wort der Projektleitung).
- Kostenobergrenze für die Studie festlegen.
- Volltexte von L04 und L13 lesen; Datenbanksuche nach Studien zur Änderungsbewertung.
