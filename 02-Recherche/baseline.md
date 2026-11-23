# Baseline: Planung und Änderungssteuerung ohne generative KI

Zu Issue #2 · Stand: 21.11.2026 · Status: **Entwurf, von der Gruppe zu bestätigen**

Frage: Wie laufen Planung, Abhängigkeiten und Ressourcen, Risikoanalyse und
Änderungsentscheidung ohne generative KI ab? Quellen-IDs (L…) verweisen auf
`literaturregister.md`.

Kennzeichnung: **[Quelle]** = in der genannten Quelle belegt. **[Eigene Operationalisierung]**
= Festlegung dieser Arbeit für das KI-Lab, keine allgemeine PM-Praxis.

## Grenzen dieser Baseline

- Grundlage sind ein offenes Lehrbuch (L15), ein Behördenhandbuch (L16) und die Originalquelle
  der Netzplantechnik (L01). Die Normen ISO 21502 und ISO 31000 waren nicht abrufbar und sind
  **nicht** geprüft. Der Abgleich mit ihnen steht aus.
- Die Rollen unten sind die, die die Quellen nennen, ergänzt um die Rollen der Lab-Fälle. Wie
  Unternehmen die Rollen tatsächlich verteilen, ist nicht untersucht.

## 1. Terminplanung mit Abhängigkeiten

| | |
|---|---|
| **Inputs** | Umfang und Arbeitspakete (Ergebnis der Strukturplanung) [L16 5.5.6–5.5.7]; Dauern, Kalender, Vorgänger [L16 5.5.8–5.5.9] |
| **Tätigkeiten** | Aktivitäten logisch verknüpfen (Abhängigkeiten zuweisen, Vorlauf/Verzug und feste Termine sparsam verwenden) [L16 5.5.8]; Dauern schätzen und Kalender festlegen [L16 5.5.9]; kritischen Pfad bestimmen [L16 5.5.10]; Puffer festlegen und zuordnen [L16 5.5.11] |
| **Outputs** | Netzplan (meist Vorgangsknoten, AON) mit Start, Ende und kritischem Pfad [L15 Kap. 10]; Terminplan als Basis |
| **Rollen** | Projektleitung erstellt den Plan; erfahrene Teammitglieder (Expertenurteil) helfen, Vorgänge zu definieren; Stakeholder und Linienvorgesetzte („functional managers“) geben den Terminplan frei [L15 Kap. 10] |

Der kritische Pfad ist die Folge von Vorgängen, die die kürzeste Projektdauer bestimmt
[L15 Kap. 10]. Kelley und Walker beschrieben das Verfahren 1959 als Grundlage für
„management by exception“: Die Leitung handelt erst, wenn der Ablauf vom Plan abweicht
[L01, Einleitung].

## 2. Ressourcen

| | |
|---|---|
| **Inputs** | Terminplan, Ressourcenbedarf je Vorgang, verfügbare Kapazität [L16 5.5.12] |
| **Tätigkeiten** | Ressourcen oder Kosten den Vorgängen zuordnen („resource loading“) [L16 5.5.12]; Überlastungen erkennen; Ressourcen abgleichen („resource leveling“): Vorgänge verschieben, ohne Netzlogik oder Randbedingungen zu verletzen [L16 5.5.12; L15 Kap. 11] |
| **Outputs** | ressourcenbelasteter Terminplan ohne Doppelbelegung [L16, Abb. 5-33] |
| **Rollen** | Projektleitung; in größeren Projekten verantworten Linienvorgesetzte („functional managers“) Teile davon [L15 Kap. 11] |

## 3. Risikoanalyse

| | |
|---|---|
| **Inputs** | Projektplan, Erfahrungen, Checklisten bekannter Risiken [L15 Kap. 16] |
| **Tätigkeiten** | Risiken identifizieren (Brainstorming, Checklisten); Wahrscheinlichkeit und Auswirkung auf Skalen einschätzen; Maßnahmen wählen: vermeiden, mindern, übertragen, akzeptieren [L15 Kap. 16] |
| **Outputs** | Risikoliste mit Bewertung und Maßnahmen; Skalen im Risikomanagementplan [L15 Kap. 16] |
| **Rollen** | Projektleitung mit dem Team; je Risiko eine verantwortliche Person [Eigene Operationalisierung, entspricht der Lab-Vorgabe „Verantwortlicher“ je Risiko] |

## 4. Änderungsentscheidung

| | |
|---|---|
| **Inputs** | Abweichung aus Leistungs- und Qualitätsdaten; aktueller Basisplan [L15 Kap. 17] |
| **Tätigkeiten** | Änderungsantrag dokumentieren; Wirkung auf Zeit, Kosten, Umfang und Qualität bewerten; Antrag einem Änderungsgremium vorlegen; nach Genehmigung umsetzen und Plan anpassen [L15 Kap. 17]. Schon 1959 Ziel: Pläne bei geänderten Bedingungen neu rechnen [L01] |
| **Outputs** | entschiedener Änderungsantrag; aktualisierter Plan [L15 Kap. 17] |
| **Rollen** | Antragsteller, Projektleitung (Bewertung), Änderungsgremium (Change Control Board) entscheidet; nicht jedes Verfahren hat ein Gremium [L15 Kap. 17]. Im Lab-Fall: Sponsor entscheidet über Termin- und Budgetabweichungen (`cases.json`, Regel „Sponsorentscheidung“) |

## 5. Messbare Schritte für die beiden Lab-Aufgaben

**[Eigene Operationalisierung]** Die Schritte übersetzen die Abschnitte 1–4 in prüfbare
Kriterien für die Fälle in `04-Prototyp/ki_lab/cases.json` (Fall A und B, je 25 Minuten,
`lab.py`, `LIMIT`). Die Punkte sind die Höchstwerte aus `analysis.py`, `CAPS`. Wie die Punkte
innerhalb eines Kriteriums vergeben werden, legt der Bewertungsleitfaden fest (nicht Teil
dieses Dokuments).

Dieses Dokument enthält bewusst **keine Musterlösung**. Das Repository ist öffentlich;
Teilnehmende könnten sie vor dem Versuch lesen.

### Aufgabe 1: Basisplan

| Schritt (prüfbar) | Herkunft | Merkmal in `CAPS` |
|---|---|---|
| B1 Jedes Paket hat Start und Ende; Dauer = Ende − Start + 1 stimmt mit der Vorgabe | Abschn. 1; Fallregel | `dependencies` (20) |
| B2 Jeder Vorgänger endet spätestens am Vortag des Nachfolgers | Abschn. 1 | `dependencies` |
| B3 Keine Ressource hat zwei Pakete am selben Tag; Integration hat Elektronik und Software zugleich | Abschn. 2; Fallregel | `resources` (15) |
| B4 Jedes Paket hat eine verantwortliche Ressource | Abschn. 2; Lieferumfang | `resources` |
| B5 Drei Meilensteine mit Termin, an Paketenden gebunden | Lieferumfang | `milestones` (15) |
| B6 Übergabe mit Test und Freigabe; Ende gegen Ziel T17 geprüft | Abschn. 1; harte Fallbedingung | `milestones` |
| B7 Annahmen als Annahmen gekennzeichnet | `prompt.txt`; Lieferumfang | – (Notiz der Bewertenden) |

### Aufgabe 2: Risiko- und Änderungsanalyse

Grundlage ist der vorgegebene Ausgangsplan, nicht die eigene Antwort auf Aufgabe 1
(`cases.json`, `reference_plan`).

| Schritt (prüfbar) | Herkunft | Merkmal in `CAPS` |
|---|---|---|
| R1 Mindestens drei Risiken, je mit Beleg aus dem Änderungstext | Abschn. 3; Lieferumfang | `risk_identification` (20) |
| R2 Auswirkung je Risiko auf Termin oder Budget benannt | Abschn. 3 | `risk_identification` |
| R3 Reihenfolge der Risiken begründet (Wahrscheinlichkeit und Auswirkung oder Lage auf dem kritischen Pfad) | Abschn. 1, 3 | `prioritization` (15) |
| R4 Je Risiko eine Maßnahme (vermeiden, mindern, übertragen, akzeptieren) und eine verantwortliche Person | Abschn. 3; Lieferumfang | `measures` (15) |
| R5 Aktualisierte Termine, die B2 und B3 weiter erfüllen | Abschn. 1, 2, 4 | `measures` |
| R6 Entscheidung zur Expressoption mit Begründung innerhalb der freigegebenen Reserve | Abschn. 4 | `measures` |
| R7 Eskalation an die entscheidende Stelle, wo die Projektleitung nicht entscheiden darf; Maßnahme nicht als beschlossen dargestellt | Abschn. 4; `prompt.txt` | `measures` |

### Schwere Fehler (`severe_errors`)

Gemeinsame Liste mit [`03-Experiment/bewertungsrubrik.md`](../03-Experiment/bewertungsrubrik.md)
(Vorschlag zur Zählung je Abgabe, von der Gruppe zu bestätigen):

1. Test oder Freigabe entfällt (verletzt harte Fallbedingung, B6).
2. Eine Ressource ist an einem Tag für zwei Pakete eingeplant oder ein Paket startet vor dem
   Ende seines Vorgängers (B2, B3, R5), **und** das ändert den Endtermin.
3. Ausgaben über Kostenbasis plus freigegebene Reserve, ohne eine Sponsorentscheidung zu
   verlangen (R6, R7).
4. Erfundene Fakten, Freigaben oder Ressourcen (etwa eine Vertretung, Überstunden oder ein
   anderer Lieferant), die der Fall ausschließt (`prompt.txt`: „Erfinde keine Fakten, Freigaben
   oder Ressourcen“).
5. Eine Terminverschiebung über den Zieltermin hinaus ohne Eskalation an die entscheidende
   Stelle (B6, R7).

### Zeit

Bearbeitungszeit je Runde = `ended_at − started_at` (`analysis.py`, Feld `seconds`); Vergleich
nur für vollständige Paare (`time_delta_ai_minus_manual`).

## Offen

- Abgleich mit ISO 21502 (Planung, Änderungssteuerung) und ISO 31000 (Risikoprozess) über den
  Normenzugang der Hochschule.
- Bewertungsleitfaden mit Punktvergabe je Schritt; Probebewertung durch zwei Personen, um die
  Übereinstimmung zu prüfen (`rater_disagreements`).
- Prüfen, ob Fall A und B gleich schwer sind (`cases.json`: „Noch nicht empirisch auf gleiche
  Schwierigkeit geprüft“).
