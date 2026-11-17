# Design-Vorschlag: Abschluss, Betrieb und Iteration (Batch 5 des Lebenszyklus)

Stand 17.11.2026. **Vorschlag, nicht freigegeben.** Baut auf Batch 1–4 auf (Anforderungen,
Entwurf, Wochen-Demos mit Rückblick, Testplan mit Ergebnissen und Fehlern). Gesamtbild:
`docs/lebenszyklus.md`, Phasen 8–10.

## Wozu

Mit Batch 4 weiß das Tool, ob das Gebaute die Akzeptanzkriterien erfüllt. Es fehlt das Ende
eines Durchlaufs:

- **Abschluss:** Ist jede Anforderung abgenommen, und was lernen wir daraus?
- **Betrieb:** Wie wird das System bereitgestellt, überwacht und zurückgenommen, und welche
  Störungen gab es?
- **Iteration:** Was kommt in den nächsten Durchlauf? Gemeint sind zurückgestellte
  Anforderungen, offene Fehler, offene Maßnahmen aus den Rückblicken und Folgen von Störungen.

So schließt sich der Kreis im Ablaufdiagramm („nächster Backlog → Anforderungen“).

## Ziele

- **Abnahme je Anforderung** durch die Projektleitung: `abgenommen` oder `zurückgestellt`
  mit Grund. Python schlägt den Stand vor: abnehmbar ist eine Anforderung, wenn alle ihre
  Testfälle bestanden sind und kein offener Fehler an ihnen hängt.
- **Abschlussbericht** (Markdown aus Vorlage): Ziel und Erfolgskriterien, Abnahme je
  Anforderung, Termine Plan/Ist, Kennzahlen, Demos und Rückblicke, Fehlerbilanz, Lessons
  Learned. Claude entwirft die Lessons Learned aus Rückblicken und Fehlern; die
  Projektleitung ändert sie.
- **Betriebshandbuch:** je Komponente des Entwurfs Verantwortliche (Rolle, kein Name),
  Bereitstellung, Überwachung, Rücknahme. Störungen erfassen (Datum, Komponente, Auswirkung,
  Ursache, Maßnahme).
- **Nächster Backlog:** Python stellt ihn zusammen, jeder Eintrag mit Herkunft (`R3
  zurückgestellt`, `F2 offen`, `Maßnahme Woche ab 16.11.`, `Störung 3`). Ein Knopf übernimmt
  ihn als Entwurf neuer Anforderungen in ein neues Vorhaben; das alte wird archiviert.

## Prüfung

- Abschluss, Fehler: kein offener schwerer Fehler; jede Muss-Anforderung abgenommen oder mit
  Grund zurückgestellt.
- Abschluss, Warnung: eine Anforderung wird abgenommen, obwohl ein Testfall nicht bestanden
  ist (die Projektleitung darf das, aber es steht im Bericht).
- Betrieb, Fehler: Komponente ohne Verantwortliche oder ohne Überwachung.
- Iteration: jeder Eintrag nennt seine Herkunft (wird von Python erzeugt, kann also nicht
  fehlen); Warnung bei leerem Backlog mit offenen Fehlern (Widerspruch).

## Seiten

- **Abschluss** (nach Kontrolle): Abnahmetabelle, Lessons Learned (Entwurf von Claude),
  Abschlussbericht.
- **Betrieb:** Handbuchtabelle je Komponente, Störungen.
- **Iteration:** nächster Backlog mit Herkunft, „Als neues Vorhaben beginnen“.
- Projektpfad: Abschluss → Betrieb → Iteration hinten an (11 Schritte). Vorschlag: Der Pfad
  zeigt die Vorbereitung und die Durchführung als zwei Zeilen, damit er lesbar bleibt.

## Offene Fragen an den Nutzer

1. **Archiv:** Beim neuen Durchlauf das alte Vorhaben (`vorhaben.json`, `projekt.json`) unter
   `data/archiv/<Datum>/` ablegen? Vorschlag: ja, nichts wird gelöscht.
2. **Betrieb im Studienprojekt:** Viele Gruppenprojekte gehen nie in Betrieb. Phase 9 als
   optional markieren (Soft Gate wie bisher)? Vorschlag: ja.
3. **Lessons Learned:** Claude-Entwurf aus Rückblicken und Fehlern (kostet einen API-Lauf)
   oder nur ein Textfeld? Vorschlag: Entwurf von Claude, wie bei den anderen Dokumenten.

## Annahmen

- Abnahme ist eine Entscheidung der Projektleitung; das Tool schlägt nur vor.
- Ein Durchlauf endet mit dem Abschluss; Betrieb und Iteration können parallel laufen.

## Bekannte Grenzen

- Der neue Agent für Lessons Learned lief nicht gegen die echte API.
- Kein Versionsvergleich zwischen Durchläufen (nur das Archiv).
