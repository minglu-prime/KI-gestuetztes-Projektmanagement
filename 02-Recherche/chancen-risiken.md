# Chancen, Risiken und neue PM-Verantwortung

Zu Issue #4 · Stand: 21.11.2026 · Status: **Entwurf, von der Gruppe zu bestätigen**

Frage: Welche Tätigkeiten könnten automatisiert, unterstützt oder durch zusätzliche Prüfung
verändert werden? Quellen-IDs (L…) verweisen auf `literaturregister.md`. Aussagen aus Quellen,
die nur als Abstract/Seite gelesen wurden, sind mit *(vorläufig)* markiert.

Das Dokument trennt drei Dinge:

1. **Befunde** (Abschnitt 1 und 2): in einer Quelle gemessen oder beschrieben.
2. **Prüfbare Beobachtungen** (Abschnitt 3): was das KI-Lab dazu messen kann.
3. **Hypothesen** (Abschnitt 4): Vermutungen zu Rollen und Kompetenzen, noch nicht belegt.

## 1. Chancen (Befunde)

| # | Kernaussage | Beleg | Grenze | Übertragbarkeit auf das Lab |
|---|---|---|---|---|
| C1 | Bei Aufgaben, die das Modell beherrscht, arbeiten Menschen mit KI schneller und liefern bessere Texte. | L06: 25,1 % schneller, über 40 % höhere Qualität; L07: 37 % weniger Zeit, Bewertung +0,45 SD | Beratungs- und Schreibaufgaben, keine Pläne mit harten Regeln; Modelle von 2023 | mittel: Der Lab-Fall ist kurz wie in L07, hat aber feste Abhängigkeiten und Ressourcen. Ob er „innerhalb“ der Fähigkeit liegt, ist offen. |
| C2 | Schwächere Personen gewinnen mehr als starke. | L06: +43 % unter, +17 % über dem Durchschnitt; L07: Abstand zwischen Personen sinkt; L08: +34 % für Neulinge *(vorläufig)* | andere Aufgaben; Leistung vorher gemessen | mittel: Das Lab erfasst Vorerfahrung (`experience`); Untergruppen werden klein. |
| C3 | KI-Entwürfe für Risikolisten sind vollständiger als die vieler Fachleute. | L03: KI Ø 8,6 vs. Fachleute Ø 5,7 bei verblindeter Bewertung; L02: KI-Plan bei Risiken strukturierter | eine KI-Antwort (L03), ein Plan (L02); Bau bzw. App | hoch für Aufgabe 2 (Risiken identifizieren); gering für Termine. |
| C4 | Ein KI-Entwurf ist ein Startpunkt, den der Mensch verfeinert. | L02 (Abschn. 5.2); Hersteller: „head start“ wie eine Vorlage [L20] | L02 qualitativ; Herstellerangabe ist kein Wirkungsbeleg | hoch: entspricht der Lab-Runde mit KI. |

## 2. Risiken (Befunde)

| # | Kernaussage | Beleg | Grenze | Übertragbarkeit auf das Lab |
|---|---|---|---|---|
| K1 | Außerhalb der Fähigkeit des Modells liegen Menschen mit KI häufiger falsch als ohne. | L06: richtige Lösung 84,5 % ohne KI, 60–70 % mit KI | eine Aufgabe, ein Modell (GPT-4) | hoch: Termin- und Ressourcenlogik kann außerhalb liegen (siehe K2). |
| K2 | Sprachmodelle verletzen Randbedingungen, sobald mehrere zusammenwirken; die Modelle unterscheiden sich stark. | L05: WAUC bei reinen Vorgängern bis 0,97, mit Ausfallzeiten, Zeitfenstern und Ausschlüssen 0,18–0,92 | Preprint; ohne Mensch; andere Modelle als `gpt-6-sol` | hoch: Der Lab-Fall hat genau solche Regeln (Abwesenheiten, gleichzeitige Ressourcen). |
| K3 | KI-Maßnahmen sind weniger praxisnah und spezifisch; Auslassungen und Fehleinschätzungen kommen vor. | L03 (qualitative Bewertung); L04 *(vorläufig)* | Bau, Modelle von 2023 | hoch für Aufgabe 2 (Maßnahmen). |
| K4 | Generierte Texte können Inhalte enthalten, die nicht durch die Quelle gedeckt sind („Halluzination“). | L12 *(vorläufig)* | Übersicht über NLG-Aufgaben, nicht PM | mittel: `prompt.txt` verlangt Belege aus dem Fall; ob das hilft, ist offen. |
| K5 | Wer der KI mehr vertraut, prüft weniger kritisch. | L10: höheres Vertrauen in KI geht mit weniger kritischem Denken einher; 83 von 319 nennen Vertrauen als Grund, nicht zu prüfen | Selbstauskunft, keine Messung des Denkens (L10 Abschn. 6.3) | hoch: messbar über Fehler, die aus dem KI-Entwurf in die Abgabe gelangen (O6 unten). |
| K6 | Automation Bias führt zu Auslassungs- und Ausführungsfehlern, bei Laien wie Fachleuten; Training allein verhindert ihn nicht. | L11 *(vorläufig)* | Studien zu älteren Entscheidungshilfen | mittel. |
| K7 | Menschen schätzen den Zeitgewinn falsch ein. | L09: erwartet 24 % schneller, gemessen 19 % langsamer; danach glaubten sie an 20 % Gewinn *(vorläufig)* | Softwareentwicklung, 16 Personen | mittel: Lab fragt Zeitempfinden in der Reflexion ab (`time_spent`). |
| K8 | Aufsicht durch Menschen allein reicht gegen Automation Bias nicht; Gestaltung und Kontext zählen. | L14 *(vorläufig)*; L18 Art. 14 Abs. 4 b (Bewusstsein für Automation Bias), d (Ausgabe verwerfen können) | L18 gilt für Hochrisiko-Systeme; ein PM-Assistent ist das in der Regel nicht | gering rechtlich, hoch als Gestaltungsprinzip: `prompt.txt` lässt Entscheidung beim Menschen. |
| K9 | Organisationen mit größerem Nutzen kümmern sich häufiger um Datenqualität und Daten-Governance. | L17: 45 % der Organisationen mit fortgeschrittenem Produktivitätsgewinn bereinigen interne Projektdaten vorrangig, vs. 29 % mit ersten Gewinnen (Befragung, n = 2 000) | Befragung eines Berufsverbands, Zusammenhang, keine Ursache; keine Leistungsmessung | gering für das Lab (synthetische Fälle); hoch für reale Projektdaten. |

Datenweg im Lab: Fall und Eingaben gehen an den Dienst der Hochschule, nicht an einen
öffentlichen Anbieter. Die Fälle sind erfunden; personenbezogene Daten entstehen nur in den
Eingaben der Teilnehmenden. Die Einwilligung muss den Dienst genau benennen (vgl. `CLAUDE.md`,
„Offen“, Punkt 6).

## 3. Prüfbare Beobachtungen im Experiment

Zuordnung zu den Größen in `04-Prototyp/ki_lab/analysis.py`, Funktion `summarize`. Alle
Vergleiche sind innerhalb der Person (Runde mit KI minus Runde ohne KI) und deskriptiv
(`interpretation` in `summarize`).

| # | Beobachtung | Prüft | Größe in `analysis.py` | Stand |
|---|---|---|---|---|
| O1 | Zeitunterschied je Person | C1, K7 | `pairs[].time_delta_ai_minus_manual`, `median_time_delta` | vorhanden |
| O2 | Qualität Basisplan mit vs. ohne KI | C1, K2 | `quality_pairs[].delta_ai_minus_manual.plan` (Summe aus `dependencies`, `resources`, `milestones`) | vorhanden |
| O3 | Qualität Risikoanalyse mit vs. ohne KI | C3, K3 | `quality_pairs[].delta_ai_minus_manual.risk` (Summe aus `risk_identification`, `prioritization`, `measures`) | vorhanden |
| O4 | Schwere Fehler mit vs. ohne KI | K1, K2, K4 | `quality_pairs[].delta_ai_minus_manual.errors` (`severe_errors`) | vorhanden; Definition in `baseline.md` |
| O5 | Einzelkriterium Abhängigkeiten und Ressourcen | K2 | Einzelwerte `dependencies`, `resources` in den Bewertungszeilen; `summarize` fasst sie nur zu `plan` zusammen | Rohdaten vorhanden, Auswertung fehlt |
| O6 | Übernommene Fehler: Fehler im ersten KI-Entwurf, die in der Abgabe bleiben | K5, K6 | `first_ai_draft` und `final` im Rohexport (`raw`); keine Größe in `analysis.py` | **neu**, Vorschlag: Bewertende markieren Fehler im KI-Entwurf und prüfen, ob sie in `final` stehen |
| O7 | Zeitempfinden vs. gemessene Zeit | K7 | Reflexion `time_spent`, `trust` (`lab.py`, `reflect`) gegen O1 | Rohdaten vorhanden, Auswertung fehlt |
| O8 | Ausfälle der KI und Zeitüberschreitungen | Zuverlässigkeit | `ai_failed_or_unfinished_calls`, `timeouts` | vorhanden |
| O9 | Übereinstimmung der zwei Bewertenden | Messgüte | `rater_disagreements` | vorhanden |

Vorab festzulegen (Gruppe): welche Richtung bei B2–O4 als Chance oder Risiko zählt, und ab
welcher Zahl vollständiger Paare überhaupt berichtet wird.

## 4. Hypothesen zu Rollen und Kompetenzen (nicht belegt)

Diese Sätze sind **Hypothesen** dieser Arbeit. Keine der gelesenen Quellen prüft sie für das
Projektmanagement.

| # | Hypothese | Anlass | Prüfbar durch |
|---|---|---|---|
| H1 | Die Tätigkeit der Projektleitung verschiebt sich vom Schreiben eines Plans zum Prüfen und Zusammenführen eines KI-Entwurfs. | L10 beschreibt diese Verschiebung für Wissensarbeit allgemein (Prüfen, Integrieren, „task stewardship“) | O1, O6; Interviews |
| H2 | Regeln prüfen (Abhängigkeiten, Kapazität, Budgetgrenzen) wird zur Kernkompetenz, weil das Modell dort schwach ist. | K2 | O5 |
| H3 | Weniger Erfahrene erreichen mit KI bessere Entwürfe, übersehen aber mehr Fehler des Modells. | C2, K5 | B2–O4 und O6 nach `experience` |
| H4 | Die Entscheidung (z. B. Expresslieferung, Eskalation) bleibt beim Menschen; KI-Vorschläge werden trotzdem als beschlossen übernommen. | K8, `prompt.txt` | Kriterium R7 in `baseline.md`; O6 |

## Offen

- Praxisinterview-Leitfaden (optional laut Issue #4): nicht entworfen. Zweck mit der Gruppe
  klären (z. B. H1 und H4 bei Praktikerinnen und Praktikern prüfen), dann entwerfen.
- O6 und O7 brauchen eine Auswertung, die `analysis.py` noch nicht hat; zuerst mit der Gruppe
  entscheiden, ob sie zum Messplan gehören.
- Volltexte der *(vorläufig)* markierten Quellen lesen.
