# Design-Vorschlag: Test und Fehlersuche (Batch 4 des Lebenszyklus)

Stand 17.11.2026. **Umgesetzt auf dem Branch `feat/test-phase`, mit den vorgeschlagenen Antworten auf die drei Fragen unten (feste IDs, eigene Seite „Test“, Wiederöffnen nur auf Knopfdruck). Die Klassen heißen `Case`, `Cases`, `CaseResult`: Namen mit „Test“ sammelt pytest als Tests ein.** Baut auf Batch 1 (Anforderungen mit
Akzeptanzkriterien), Batch 2 (Entwurf mit typisierten Schnittstellen, PR #43) und Batch 3
(Wochen-Demos, `feat/weekly-demos`) auf. Gesamtbild: `docs/lebenszyklus.md`, Phase 7.

## Wozu

Bisher endet der Ablauf mit der Kontrolle: Wir wissen, welche Aufgaben fertig sind, aber
nicht, ob das Gebaute tut, was die Anforderungen verlangen, und ob die Teile zusammenpassen.
In einer echten Softwareentwicklung kommt jetzt der Integrationstest: Testfälle aus den
Akzeptanzkriterien und Schnittstellen, Ergebnisse, und für jeden Fehlschlag ein Fehler mit
vermuteter Ursache, der in die Durchführung zurückgeht.

## Ziele

- **Testfälle:** der Agent entwirft sie aus zwei Quellen, Python prüft die Abdeckung:
  - je Akzeptanzkriterium (R1.1, R1.2 …) mindestens ein Testfall;
  - je Schnittstelle mindestens ein Integrationstest, und je Fehlercode des Vertrags
    (`409 Raum belegt`) ein Testfall, der ihn auslöst.
- **Ergebnisse:** Die Projektleitung trägt je Testfall ein: bestanden / fehlgeschlagen /
  blockiert, Datum, Notiz. Fakten trägt der Mensch ein, nicht der Agent.
- **Fehler:** Jeder fehlgeschlagene Testfall braucht einen Fehlereintrag (Schwere, vermutete
  Ursache, zuständige Aufgabe oder Komponente, Status offen/behoben). Ein Fehler kann eine
  Aufgabe in der Durchführung wieder auf „in Arbeit“ setzen (der Pfeil „Fehler → Durchführung“
  im Ablaufdiagramm).
- Die Kontrolle zeigt „Testabdeckung“ und „offene Fehler“; der Abschluss (Batch 5) verlangt
  später „kein offener schwerer Fehler“.

## Nicht-Ziele (Batch 4)

- Tests ausführen. Das Tool führt keine Software des Teams aus; es plant und dokumentiert.
- Testcode erzeugen (pytest, Playwright). Möglich später als Export.
- Fehlerverfolgung mit externen Systemen (GitHub Issues, Jira).

## Datenformat

```python
class TestCase(_Model):  # models.py
    id: Ref  # T1, T2 …
    title: NonEmpty
    kind: Literal["Akzeptanz", "Integration"]
    criteria: list[Ref] = []  # R1.1 … (Akzeptanzkriterien)
    interface: Ref | None = None  # S1 (Integration)
    error_code: Ref | None = None  # 409: der Fall löst diesen Fehler aus
    steps: list[NonEmpty]  # was man tut
    expected: NonEmpty  # was herauskommen muss


class TestPlan(_Model):  # in vorhaben.json: Lifecycle.tests, tests_ok
    cases: list[TestCase]


class TestRun(BaseModel):  # in projekt.json: Tracking.test_runs
    case_id: str
    result: Literal["bestanden", "fehlgeschlagen", "blockiert"]
    on: date
    note: str = ""


class Defect(BaseModel):  # in projekt.json: Tracking.defects
    id: str  # F1 …
    case_id: str
    severity: Literal["schwer", "mittel", "leicht"]
    cause: str  # vermutete Ursache
    task_id: str | None  # die Aufgabe, die es beheben soll
    status: Literal["offen", "behoben"]
    fixed_on: date | None  # Tag der Behebung; ältere Dateien haben keinen
```

Akzeptanzkriterien brauchen dafür **feste IDs**. Heute ergeben sie sich aus der Reihenfolge
(R1.1, R1.2 …); löscht man eins, rutschen die anderen nach. Vorschlag: Nummer beim Anlegen
festschreiben (`Requirement.criteria` wird `list[Criterion]` mit `id` wie „R1.1“). Das ist
eine Datenänderung an Batch 1 mit Übernahme alter Dateien.

## Prüfung

`check_tests(tests, requirements, design)`:

- Fehler: unbekanntes Kriterium, unbekannte Schnittstelle, Fehlercode, den die Schnittstelle
  nicht hat; doppelte IDs.
- Fehler: Muss-Anforderung, deren Kriterien nicht alle einen Testfall haben.
- Warnung: Soll-/Kann-Kriterium ohne Testfall; Schnittstelle ohne Integrationstest;
  Fehlercode ohne Testfall.

`check_results(tracking)`:

- Fehler: fehlgeschlagener Testfall ohne Fehlereintrag; schwerer Fehler ohne Aufgabe.
- Fehler: fehlgeschlagener Testfall, dessen Fehler alle behoben sind. Mit `fixed_on` nennt
  die Meldung, was zu tun ist: Ergebnis vor der Behebung „Testfall wiederholen“, danach
  „neuen Fehler erfassen oder Fehler wieder öffnen“; am selben Tag ist die Reihenfolge
  unbekannt, die Meldung nennt beides. Ohne Datum wie früher „Testfall wiederholen“.
- Warnung: Testfall ohne Ergebnis; Fehler offen, dessen Aufgabe „fertig“ ist.

## Seiten

- **Vorbereiten · Testplan** (nach Entwurf): Entwurf vom Agenten, Tabelle der Testfälle,
  Abdeckung je Kriterium und je Schnittstelle, Freigabe, Markdown. Projektpfad: 7 Schritte.
- **Agenten · Test** (nach Durchführung): Ergebnisse eintragen, Fehler erfassen, „Aufgabe
  wieder öffnen“ setzt die zuständige Aufgabe auf „in Arbeit“. „behoben“ hält den Tag fest,
  „wieder öffnen“ setzt den Fehler zurück auf offen. Über „Eintrag“ lässt sich ein Fehler
  ändern: Die Felder zeigen ihn, Status und Tag der Behebung bleiben.
- **Kontrolle:** Testabdeckung, offene Fehler nach Schwere.

## Offene Fragen an den Nutzer

1. **Feste IDs für Akzeptanzkriterien** (Datenänderung an Batch 1): einverstanden?
2. **Wo die Ergebnisse eintragen?** Vorschlag: eigene Seite „Test“ zwischen Durchführung und
   Kontrolle. Alternative: ein Panel in der Durchführung (weniger Seiten, aber voller).
3. **Fehler → Aufgabe:** Soll ein schwerer Fehler die Aufgabe automatisch wieder öffnen, oder
   nur auf Knopfdruck? Vorschlag: auf Knopfdruck, die Projektleitung entscheidet.

## Annahmen

- Testfälle gehören zum Vorhaben (geplant, freigegeben), Ergebnisse und Fehler zum
  übernommenen Projekt (Fakten aus der Umsetzung).
- Kein neues Abhängigkeitspaket.

## Bekannte Grenzen

- Ob ein Test wirklich bestanden ist, sagt der Mensch; das Tool prüft nur Vollständigkeit.
- Der neue Agent lief nicht gegen die echte API.
