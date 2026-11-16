# Design-Vorschlag: Wochen-Demo und Wochenrückblick (Batch 3 des Lebenszyklus)

Stand 16.11.2026. **Vorschlag, nicht freigegeben.** Baut auf Batch 1 (PR #42) und Batch 2
(`feat/lifecycle-design`) auf. Gesamtbild: `docs/lebenszyklus.md`, Phasen 4 und 6.

## Wozu

Der Nutzer will, dass jede Woche ein vorführbares Ergebnis entsteht, damit Fehler früh
sichtbar werden und sich im Rückblick aufarbeiten lassen. Bisher kennt der Plan nur Aufgaben
und das Projektende; ob in Woche 3 etwas Zeigbares fertig ist, sagt er nicht. Und die
Kontrolle misst Verzug, fragt aber nie: Was haben wir gezeigt, was nicht, warum, was ändern
wir?

## Ziele

- **Planung:** Der Plan nennt je Projektwoche eine **Demo**: was gezeigt wird und welche
  Aufgaben dafür fertig sein müssen. Claude schlägt sie vor, Python prüft sie gegen den
  Zeitplan.
- **Kontrolle:** Für jede vergangene Woche ein **Rückblick**: Demo gezeigt (ja / teilweise /
  nein), was schiefging, vermutete Ursache, Maßnahme. Die Fakten trägt der Mensch ein.
- Python rechnet für jede Demo vorab, ob ihre Aufgaben laut Fortschritt fertig sind; der
  Mensch sieht so vor dem Termin, welche Demo wackelt.
- Offene Maßnahmen bleiben sichtbar, bis sie erledigt sind (Grundlage für Batch 5 Iteration).

## Nicht-Ziele (Batch 3)

- Claude schreibt den Rückblick (später möglich: Claude schlägt Ursache und Maßnahme aus den
  Daten vor, wie beim Kontrollbericht).
- Termine, Erinnerungen, Kalender.
- Demos für frühere Pläne nach „Rest umplanen“ (nur der aktuelle Plan hat Demos).

## Datenformat

```python
class Demo(_Model):          # in models.py, Teil des Plans
    week: int = Field(ge=1)  # Projektwoche: Woche 1 beginnt am Startdatum
    title: NonEmpty          # „Raum buchen im Browser vorführen“
    task_ids: list[NonEmpty] = Field(min_length=1)

class Plan(_Model):          # neu: demos, Standard leer (alte Pläne und Logs bleiben lesbar)
    ...
    demos: list[Demo] = Field(default_factory=list)

class Retro(BaseModel):      # in tracking.py, Teil des übernommenen Projekts
    week: int
    shown: Literal["ja", "teilweise", "nein"]
    went_wrong: str = ""
    cause: str = ""
    measure: str = ""
    measure_done: bool = False

class Tracking(...):         # neu: retros, Standard leer
    retros: list[Retro] = []
```

Projektwoche `n` = die Kalenderwoche (Mo–Fr), die `n − 1` Wochen nach der Woche des
Startdatums liegt; die letzte Woche endet an der Deadline.

## Prüfung

In `planning.check_plan` (nur, wenn der Plan Demos hat oder `demos_required=True`):

- Fehler: Demo nennt unbekannte Aufgabe; Woche außerhalb des Projekts; zwei Demos in
  derselben Woche.
- Warnung `("demo_missing", n)`: Projektwoche `n` hat keine Demo.
- Warnung `("demo_late", n)`: eine Aufgabe der Demo endet laut Zeitplan nach dem Freitag
  dieser Woche (das Ergebnis wäre zum Vorführen nicht fertig).

Im Rückblick (`tracking.check_retros`):

- Fehler: eine Demo mit „nein“ oder „teilweise“ ohne Maßnahme.
- Warnung: vergangene Woche ohne Rückblick.

Soft Gate wie bisher: Ein Plan ohne Demos bleibt gültig; die Statusleiste der Planung zeigt
„Wochen-Demos: keine“.

## Seiten

- **Planung**, Ergebnis: neue Tabelle „Demos je Woche“ (Woche, Freitag, Demo, Aufgaben,
  „rechtzeitig fertig?“), Rauten im Gantt-Diagramm am Freitag jeder Demo. Anpassen: Demos
  lassen sich im Chat ändern („Demo in Woche 2 nur mit der Liste“), von Hand in einer Tabelle.
- **Kontrolle**, neues Panel „Wochenrückblick“: je vergangener Woche die Demo, was Python
  aus dem Fortschritt sieht (alle Aufgaben fertig / x von y), und ein Formular für gezeigt,
  was schiefging, Ursache, Maßnahme; darunter offene Maßnahmen mit Haken „erledigt“.
- **Durchführung**: In „Die nächsten fünf Arbeitstage“ ein Hinweis auf die Demo dieser Woche.
- Kontrollbericht und Statusbericht bekommen einen Abschnitt „Demos“.

## Offene Fragen an den Nutzer

1. **Was heißt „vorführbar“?** (a) ein laufendes Stück Software, das man am Rechner zeigt;
   (b) jedes Ergebnis, das man ansehen kann (Dokument, Klick-Prototyp, Testbericht). Bei (a)
   verlangt der Prompt Demos aus Umsetzungsaufgaben; bei (b) zählt jede Aufgabe.
2. **Wer bewertet „gezeigt“?** Vorschlag: die Projektleitung allein; die Betreuung taucht im
   Tool nicht auf.
3. **Eine Demo pro Woche Pflicht, oder darf eine Woche (z. B. Klausurwoche) frei sein?**
   Vorschlag: Warnung statt Fehler, die Projektleitung entscheidet.

## Annahmen

- Wochen beginnen montags; Projekte sind höchstens einige Monate lang.
- Rückblicke gehören zum übernommenen Projekt (`projekt.json`), nicht zu `vorhaben.json`.

## Bekannte Grenzen

- Nach „Rest umplanen“ beginnt die Wochenzählung weiter beim ursprünglichen Startdatum; die
  Demos des alten Plans gehen nicht in den neuen über (nur ihre Rückblicke bleiben).
- Die geänderten Prompts liefen nicht gegen die echte API.
