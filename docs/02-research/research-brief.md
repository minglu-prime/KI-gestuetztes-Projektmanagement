# Recherchebrief — Arbeitsstand 28.10.2026

Diese erste, gezielte Recherche liefert eine begründete Ausgangsbasis; sie ist **kein systematisches Review** und kein empirisches Ergebnis unseres Teams. Externe Befunde, Herstellerangaben und eigene Designentscheidungen sind getrennt.

## 1. Baseline als untersuchbarer Arbeitsablauf

Für dieses Experiment definieren wir folgende operative Baseline: Projektauftrag lesen → Arbeitspakete und Abhängigkeiten erfassen → Dauer und Ressourcen prüfen → Plan/Meilensteine formulieren → neue Statusinformationen bewerten → Risiken/Maßnahmen dokumentieren → Entscheidung eskalieren oder freigeben. Das ist unsere fallbezogene Operationalisierung, keine Behauptung, dass alle Organisationen gleich arbeiten.

| Tätigkeit | Ohne generative KI | Mit unserem Demonstrator | Menschliche Prüfung |
|---|---|---|---|
| Planung | Materialien lesen, Termine/Abhängigkeiten selbst ableiten | Vorschlag oder Gegenprüfung aus demselben Material | Kapazität, Vorgänger und Vollständigkeit |
| Risikoanalyse | Probleme markieren, Auswirkungen und Maßnahmen formulieren | Hinweise strukturieren, Optionen erläutern | Faktentreue, Priorität, Verantwortlichkeit |
| Änderungsentscheidung | Alternativen rechnen und begründen | Argumentations-/Entwurfshilfe | Budget, Freigabe, Stakeholder und Restunsicherheit |

## 2. Was die recherchierten Quellen tragen

| Quelle / Typ | Verwendbare Aussage | Grenze für unser Projekt |
|---|---|---|
| Dell’Acqua et al., HBS/BCG, 2023 Arbeitsbericht; [Primärzusammenfassung](https://aiinstitute.hbs.edu/navigating-the-jagged-technological-frontier/) | Kontrolliertes Experiment mit 758 Consultants; Nutzen unterscheidet sich nach Aufgabe, unterschiedliche Formen der Mensch-KI-Arbeit werden beschrieben. | Beratungsaufgaben, damaliges Modell; keine Effektgröße als Erwartungswert für unser PM-Experiment übernehmen. |
| PMI, September 2024, [Pushing the Limits](https://www.pmi.org/learning/thought-leadership/transforming-project-management-with-generative-ai) | Berufsbezogener Bericht über GenAI-Nutzung, Fähigkeiten und organisatorische Voraussetzungen im PM. | Verbands-/Praxisbericht; keine isolierte kausale Wirksamkeitsprüfung unseres konkreten Workflows. |
| NIST, 2024, [Generative AI Profile, AI 600-1](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence) | Branchenübergreifender Rahmen für vertrauenswürdige Entwicklung, Nutzung und Evaluation generativer KI. | Orientierung für Risikofragen, kein Produktvergleich und kein Beleg einer PM-Zeitersparnis. |
| OpenAI, [Text generation](https://developers.openai.com/api/docs/guides/text) | Offizielle technische Grundlage für Textgenerierung über die Responses API. | API-Dokumentation belegt Schnittstellen, keine experimentelle Ergebnisqualität. |

Alle verlinkten Webseiten wurden am 28.10.2026 aufgerufen. Bei der Weiterarbeit vollständige Publikationen und Methodenteile prüfen; bibliografische Angaben und Versionsstände in der Literaturverwaltung sichern.

## 3. KI-Lösungen: erste Kandidatenübersicht

| Ansatz | Nachgewiesene Produktbeschreibung | Passung und Trade-off |
|---|---|---|
| Atlassian Rovo | Hersteller beschreibt Suche, Chat, Agenten und Nutzung von Organisationskontext. [Produktseite](https://www.atlassian.com/software/rovo) | Interessant für existierende Atlassian-Prozesse; Account-/Integrationsbedarf und zusätzlicher Kontext erschweren einen kleinen kontrollierten Vergleich. |
| Asana AI | Hersteller beschreibt Agentic Work Management sowie AI Teammates und AI Studio. [Produktseite](https://asana.com/product/ai) | Für reale Workflows relevant; Produktfunktionen sind keine unabhängigen Belege für bessere PM-Ergebnisse. |
| Eigenes kleines Interface mit Modell-API | Gleiches Fallmaterial/Editor für beide Bedingungen, separate Logs und eingefrorene Konfiguration | Unsere Wahl für experimentelle Kontrolle. Ergebnisse gelten für diese Implementierung und diesen Prompt, nicht für alle Produkte. |

Kein Toolranking und keine Preisannahmen. Modellwahl vor Freeze anhand realer Zugänglichkeit, deutscher Antworten, Latenz, Kostenrahmen und Logfähigkeit. Kein Live-API-Erfolg wurde beim Erstellen dieses Pakets nachgewiesen; dafür fehlte der Key.

## 4. Chancen und Risiken als prüfbare Fragen

- **Zeitgewinn:** sinkt Gesamtzeit einschließlich Lesen, Warten und Korrigieren? Nicht nur Generierungsdauer messen.
- **Qualität:** werden Abhängigkeiten/Ressourcen vollständig erkannt? Gegen Rubrik prüfen statt sprachliche Eleganz bewerten.
- **Unbelegte Aussagen:** übernimmt die Person eine erfundene Freigabe oder einen nicht vorhandenen Lieferanten? Schwere Fehler gesondert erfassen.
- **Übernahme ohne Prüfung:** bleiben fehlerhafte Vorschläge im Endtext? Erste KI-Antwort und finalen Text vergleichen; Textänderungen beweisen allein keine gedankliche Prüfung.
- **Verantwortung:** wer entscheidet bei Budget-/Terminabweichungen? In Reflexion und optionalen Praxisinterviews prüfen.
- **Daten:** welche Inputs dürfen an einen Anbieter gehen? Im Pilot ausschließlich synthetisches Material; institutionelle Vorgaben vor formaler Erhebung klären.

## 5. Rechercheaufträge für Woche 1

Marla: zwei bis vier belastbare Quellen zum Planungs-/Änderungsprozess und eine begründete Baseline-Prozesskarte. Tim: Studien zu generativer KI bei Wissensarbeit/PM und offizielle Produktdokumentation. Cara: empirische Grenzen, menschliche Kontrolle und Risikoaspekte. Je Quelle ein Eintrag:

| ID | Suchdatum / Suchstring | Autor/Jahr/Link | Quellentyp | Aufgabe & Stichprobe | Modell/Version | Gemessene Größen | Befund | Grenzen | Verwendung |
|---|---|---|---|---|---|---|---|---|---|
| auszufüllen | | | | | | | | | |

Suchstrings: `generative AI project management controlled experiment`; `human AI collaboration project planning quality`; `LLM project scheduling resource constraints evaluation`; `generative AI automation bias knowledge work`. Fachbibliothek/Scholar als Discovery verwenden, zitierfähige Originalpublikationen lesen. Zeitraum für KI-Wirksamkeit ab 2023 bis Recherchedatum; ältere PM-Grundlagen zulassen. Deutsch/Englisch. Ausschließen: unbelegte SEO-Listen, rein anekdotische Erfolgsmeldungen, Quellen ohne nachvollziehbare Methodik für Wirksamkeitsbehauptungen. Nicht zugängliche Volltexte kennzeichnen.

Auswahl der Fallstudie: Kursbezug, fachliche Verständlichkeit, beurteilbare harte Randbedingungen, Beschaffbarkeit vollständiger Materialien, geringe Datenschutzlast, Aufwand innerhalb 4 Wochen. Produktfall vorläufig gewählt; Software-/Eventfall nur wechseln, wenn die erste fachliche Prüfung einen konkreten Vorteil zeigt, und dann vor Freeze.
