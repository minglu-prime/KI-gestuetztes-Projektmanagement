# Demonstrator starten

## Start in zwei Schritten

Python 3.11+ genügt; keine Pakete installieren.

```powershell
python server.py
```

Dann im Browser **http://127.0.0.1:8874** öffnen. Alternativ `Start-Lab.cmd` doppelklicken. Server-Terminal zum Stoppen mit Strg+C beenden.

Die Anwendung ist bewusst lokal und für betreute Versuche auf einem Studienrechner ausgelegt. Einladungslinks funktionieren auf diesem Rechner. Für parallele Rechner oder Internetzugang sind zusätzlich authentifiziertes Hosting und ein abgestimmtes Datenkonzept nötig.

## KI aktivieren

Der Server ruft die OpenAI Responses API auf. Schlüssel ausschließlich als Umgebungsvariable im Serverprozess setzen; nicht in Git, Browser oder Chat eintragen. `PM_MODEL` muss die vom Team gewählte und im eigenen Account getestete Snapshot-ID enthalten. Es wird kein Modell geraten oder automatisch gewechselt.

```powershell
$keyInput = Read-Host 'OpenAI API-Key' -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $keyInput).Password
$env:PM_MODEL = Read-Host 'Getestete datierte Modell-Snapshot-ID'
python server.py
```

Nach Beenden: `Remove-Item Env:OPENAI_API_KEY`. Ein vorhandenes ChatGPT-Abonnement ersetzt keinen API-Key. Ohne Konfiguration funktioniert der manuelle Ablauf; KI-Aufrufe scheitern sichtbar und werden protokolliert. Keine Ersatzantworten. Maximal 12 Anfragen pro Runde; tatsächliche Kosten hängen vom gewählten Modell ab.


Alle Befehle im Repository-Hauptverzeichnis ausführen. [Betrieb und Daten](operations.md). [Zurück zum Projekt](../../README.md).
