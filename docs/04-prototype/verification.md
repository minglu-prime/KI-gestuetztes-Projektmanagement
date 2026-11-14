# Verifikationsstand

Stand 29.10.2026: **24 Unit-/HTTP-Tests erfolgreich**, JavaScript-Syntaxprüfung erfolgreich. Dokumentenlinks werden zusätzlich mit `scripts/check_docs.py` geprüft. Keine empirische Studie, keine realen Teilnehmerdaten.

## Automatisch abgedeckt

- Vier Sequenzen, Einwilligung, versteckte Fälle vor Rundenstart.
- Gleicher Startzeitpunkt bei wiederholtem Start, Speicherung/Neuladen, Timeout mit letztem rechtzeitig gespeichertem Teilstand.
- Unveränderliche Abgabe, expliziter Start der nächsten Runde, serverseitige KI-Sperre im Manualmodus.
- Sperren des Basisplans vor Sichtbarkeit der Änderungs-/Referenzmaterialien.
- Ablehnung veralteter Fall-/Phasenanfragen; späte KI-Antwort bleibt im Audit der richtigen Runde.
- Fehlender Key als protokollierter Fehler; simulierte erfolgreiche Anbieterantwort erhält Erstentwurf und Modellmetadaten.
- Formal-Freeze/Voraussetzungen und Modellabweichung; separate Raterpakete; Pilottrennung und gepaarte deskriptive Analyse.
- HTTP-Zugriffsschutz für private Dateien, fremde Origins, ungültiges JSON sowie exklusive lokale Portbelegung.

## Noch offen

- Echter API-Erfolg einschließlich aktueller Modellzugänglichkeit, Kosten und deutscher Qualität; Key nicht vorhanden.
- Vollständiger UI-Ablauf nach den letzten Phasen-/Race-Fixes; frühe Startseite wurde im Browser geprüft, dies ersetzt keinen End-to-End-Nachweis.
- Empirische A/B-Verständlichkeit/-Vergleichbarkeit mit 2–3 Piloten.
- Fachliche Referenzprüfung, Raterkalibrierung, institutionelle Vorgaben, private formale Materialien und bestätigte Rekrutierung.

Der unabhängige Review fand verzögerte Anfragen über Rundengrenzen und überholte KI-Callbacks; Kontextbindung/Render-Guards wurden ergänzt. Der zweite unabhängige Review konnte wegen eines Tool-/Accountlimits nicht abgeschlossen werden. Die offenen Punkte bleiben sichtbar.

## Reproduzieren

```powershell
python -m unittest discover -s tests -v
python scripts/check_docs.py
node --check web/app.js
```

Den tatsächlichen letzten Lauf und dessen Ergebnis in PR/CI prüfen. CI enthält absichtlich keine echten Modellaufrufe. Die simulierte Antwort ist ausschließlich Testfixture, nicht Fallback der Anwendung.
