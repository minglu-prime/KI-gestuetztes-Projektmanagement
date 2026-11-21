# Suchprotokoll

Stand: 21.11.2026 · Status: **Entwurf, von der Gruppe zu bestätigen**

Die Suche lief an einem Tag (21.11.2026) durch einen Coding-Agenten. Sie ist eine
Startsuche, keine systematische Übersichtsarbeit. Eine Datenbanksuche in Scopus oder Web of
Science über den Hochschulzugang fehlt (siehe „Offen“).

## Werkzeuge

- **Websuche** (allgemeine Suchmaschine über das Werkzeug des Agenten). Liefert je Anfrage rund
  zehn Treffer, keine Gesamtzahl.
- **Abruf der Originale**: Verlagsseiten, Repositorien (Aalto, QUB, arXiv, SSRN, NBER),
  Europe PMC (REST-Schnittstelle für die PubMed-Angaben), Microsoft Learn, LibreTexts,
  nasa.gov. PDFs wurden lokal mit `pdftotext` in Text umgewandelt und gelesen.

## Suchanfragen

„Treffer“ = Zahl der Ergebnisse, die die Suche zeigte; „Auswahl“ = daraus ins Register
übernommen.

| # | Suchbegriffe | Treffer | Auswahl |
|---|---|---|---|
| S1 | large language models project scheduling resource-constrained evaluation study arXiv | 10 | L05 |
| S2 | generative AI project management empirical study risk identification ChatGPT journal | 10 | L03, L04 |
| S3 | Dell'Acqua Navigating the Jagged Technological Frontier field experiment BCG SSRN | 10 | L06 |
| S4 | Noy Zhang 2023 Science experimental evidence productivity effects generative artificial intelligence | 10 | L07 |
| S5 | Parasuraman Manzey 2010 complacency and bias in human use of automation Human Factors | 10 | L11 |
| S6 | PMI report AI in project management survey 2024 2025 | 18 | L17 |
| S7 | Barcaui Monat 2023 Who is better in project planning … Project Leadership and Society DOI | 10 | L02 (S7 zeigte auch L13) |
| S8 | METR 2025 randomized controlled trial early-2025 AI experienced open-source developer productivity arXiv | 10 | L09 |
| S9 | Survey of hallucination in natural language generation Ji 2023 ACM Computing Surveys DOI | 10 | L12 |
| S10 | Lee 2025 CHI impact of generative AI on critical thinking knowledge workers survey Microsoft Research | 10 | L10 |
| S11 | Kelley Walker 1959 critical-path planning and scheduling Eastern Joint Computer Conference DOI | 10 | L01 |
| S12 | Microsoft Copilot in Project Planner generate project plan risks feature documentation learn.microsoft.com | 17 | L19, L20 |
| S13 | Brynjolfsson Li Raymond Generative AI at Work Quarterly Journal of Economics 2025 DOI | 10 | L08 |
| S14 | ISO 21502:2020 project, programme and portfolio management guidance on project management iso.org | 10 | – (nicht prüfbar) |
| S15 | ISO 31000:2018 risk management guidelines iso.org standard page | 19 | – (nicht prüfbar) |
| S16 | Atlassian Intelligence Jira AI features work breakdown support.atlassian.com | 15 | – (nicht lesbar) |
| S17 | arXiv 2604.21958 systematic review generative AI usage IT project management | 10 | L13 |
| S18 | Regulation (EU) 2024/1689 Artificial Intelligence Act Article 14 human oversight automation bias eur-lex | 10 | L18, L14 |
| S19 | GovS 002 Project delivery functional standard gov.uk pdf change control risk planning | 18 | – (nicht abrufbar) |
| S20 | NASA Schedule Management Handbook pdf critical path resource leveling | 10 | L16 |
| S21 | V-Modell XT Änderungsmanagement Änderungssteuerungsgruppe Änderungsantrag Rolle Dokumentation pdf | 15 | – (nur Inhaltsverzeichnis) |
| S22 | Watt Project Management 2nd edition BCcampus open textbook risk management planning change | 18 | L15 |

## Auswahlkriterien

Aufgenommen, wenn alle zutreffen:

1. **Bezug** zu einer der beiden Aufgaben des KI-Labs (Basisplan mit Abhängigkeiten und
   Ressourcen; Risiko- und Änderungsanalyse) oder zu Wirkungen generativer KI auf
   Wissensarbeit (Zeit, Qualität, Fehler, Prüfverhalten).
2. **Original erreichbar**: mindestens Abstract und bibliografische Angaben beim Verlag, im
   Repositorium oder beim Herausgeber geprüft. Angaben nur aus Suchtreffern oder Sekundärseiten
   reichen nicht.
3. **Empirische Studien**: Methode, Stichprobe und Modell aus dem Original erkennbar.
4. **Sprache**: Deutsch oder Englisch.

Ausgeschlossen: Aggregator- und Statistikseiten, Blogs von Drittanbietern, Pressetexte ohne
Originaldaten, Quellen, deren Original nicht abrufbar war.

## Nicht prüfbar (ausgeschlossen)

| Quelle | Grund |
|---|---|
| ISO 21502:2020, ISO 31000:2018 | iso.org antwortete dem Abrufwerkzeug mit HTTP 403; Normtext kostenpflichtig |
| GovS 002 Project Delivery (UK) | PDF v2.0 HTTP 410; Seite der Neufassung HTTP 403 |
| Atlassian Community „AI Work Breakdown“ | Seite ohne lesbaren Text (vermutlich per JavaScript geladen) |
| PMI-Pressemitteilung „genai-adoption-research“, PMI-Artikel „origins of CPM“ | HTTP 403 |
| V-Modell XT Bund 2.3 (Änderungsmanagement) | Suchtreffer zeigten nur Deckblatt und Inhaltsverzeichnis; Kapitel nicht gelesen |

## Offen

- Datenbanksuche (Scopus, Web of Science, IEEE Xplore, ACM DL) mit festem Suchstring, z. B.
  `("generative AI" OR "large language model" OR ChatGPT) AND ("project management" OR
  "project planning" OR "risk management" OR "change control")`, Zeitraum 2022–2026, mit
  Trefferzahlen je Datenbank.
- ISO 21502 und ISO 31000 über die Hochschulbibliothek (Normenzugang) prüfen; danach die
  Baseline gegen die Normbegriffe abgleichen.
- Deutsche Fachquellen (z. B. DIN 69901, GPM) ergänzen; nicht gesucht.
- Volltexte der Quellen mit „nur Abstract/Seite“ lesen (L04, L08, L09, L11–L14).
