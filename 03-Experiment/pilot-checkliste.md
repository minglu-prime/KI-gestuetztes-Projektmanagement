# Pilot-Checkliste (Entwurf zu Issue #7)

> **Entwurf, von der Gruppe zu bestätigen.** Ablauf für 2–3 Piloten vor der formalen Erhebung. Pilotdaten bleiben getrennt: Pilot-Sitzungen sind gekennzeichnet und fallen aus der formalen Auswertung heraus (`export_bundle` ohne `--include-pilots`, `summarize`).

## Vorbereiten

- [ ] Eigene Datenbank für die Piloten, nicht die spätere formale: `python manage.py --db data/pilot.db status`.
- [ ] Key und Modell gesetzt; `/api/health` meldet `ai_configured: true` und das Modell.
- [ ] Pilotpersonen: Teammitglieder oder Freiwillige, die **nicht** an der formalen Erhebung teilnehmen. Jede Person bekommt eine Pilot-Sitzung (Startseite → „Pilot-Sitzung öffnen“).
- [ ] Je Pilot ein anderer Ablauf, damit beide Fälle mit und ohne KI vorkommen. **Entscheidung der Gruppe:** Welche Gruppen (1–4) für welchen Pilot?
- [ ] Beobachtungsbogen bereit (unten); Notizen ohne Namen, nur Pilotkennung.

## Während des Piloten beobachten

| Frage | Notiz |
|---|---|
| Versteht die Person die Regeln des Falls ohne Nachfrage? Welche Stellen waren unklar? | |
| Reicht die Zeit (25 Minuten für beide Aufgaben)? Wie viele Minuten blieben übrig, oder lief die Zeit ab? | |
| Bedienung: Wurde das Sperren des Basisplans verstanden? Gab es Fehlermeldungen? | |
| KI-Runde: Wie viele Fragen? Kam jede Antwort? Wie lange dauerte sie? | |
| Wirkte ein Fall schwerer als der andere? Woran? | |
| Reflexion: Waren die fünf Fragen verständlich? | |

Nur Beobachtungen festhalten, keine Hilfen zum Inhalt geben.

## Danach

- [ ] Export mit Piloten: `python manage.py --db data/pilot.db export --out private/pilot --include-pilots`.
- [ ] **Raterkalibrierung** mit mindestens zwei Antworten aus den Piloten, nach [`bewertungsrubrik.md`](bewertungsrubrik.md):
  - Rater 1 und Rater 2 bewerten unabhängig, jede Person in ihrer eigenen Datei (`R1/`, `R2/`).
  - Danach den Unterschied je Antwort vergleichen (`rater_disagreements` aus `manage.py analyze` mit `--ratings`).
  - Gründe für Abweichungen besprechen und die Ankerbeispiele der Rubrik schärfen.
  - **Entscheidung der Gruppe:** Ab welcher Abweichung in Punkten wird eine Antwort gemeinsam nachbewertet?
- [ ] Fälle vergleichen: Zeit, Punkte und Fehler je Fall. Ist ein Fall klar schwerer, dann Fall anpassen und nicht die Bewertung.
- [ ] Jede Änderung an Fällen, Prompt, Rubrik oder Zeit notieren und die betroffenen Abläufe erneut prüfen (ein weiterer Pilot oder ein Probelauf).
- [ ] Technischer Stand: echter KI-Aufruf und Fehlerpfade sind in `04-Prototyp/ki_lab/VERIFIKATION.md` belegt (21.11.2026). Nach einer Änderung am Lab erneut prüfen.

## M2-Freigabe, dann Freeze

Erst wenn alle Punkte oben erledigt sind:

1. Die Freigabe in `01-Projektplanung/entscheidungen.md` eintragen: Datum, was geprüft ist, was abweicht.
2. Freeze in der **formalen** Datenbank: `python manage.py freeze --attestation "<Text der Freigabe, mindestens 20 Zeichen>"`. Der Freeze hält Fallversion, Prüfsummen von Material und Prompt, Modell, Zeitlimit und Protokollversion fest.
3. Danach keine Änderung mehr an Fällen, Prompt oder Modell. Das Lab sperrt formale Sitzungen, wenn sich die Konfiguration ändert.

Pilotdaten (Datenbank, Exporte, Bögen) bleiben privat und kommen nicht ins Repository. Öffentlich nur aggregierte Befunde.
