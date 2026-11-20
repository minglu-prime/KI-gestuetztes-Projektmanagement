# Design: Phase 3 „Entwurf“ (Batch 2 des Lebenszyklus)

Stand 16.11.2026. Baut auf Batch 1 (Projektauftrag, Anforderungen, Rückverfolgung in die
Planung, PR #42) auf. Gesamtbild: `docs/lebenszyklus.md`.

## Wozu

Zwischen „was soll das System können“ (Anforderungen) und „wer macht was bis wann“ (Planung)
fehlt bisher „wie ist das System gebaut“: welche Teile es hat, wie sie miteinander reden und
in welcher Reihenfolge. In einer echten Softwareentwicklung sind das Schnittstellenverträge
und Sequenzdiagramme. Ohne sie plant das Team Aufgaben, ohne zu wissen, wo zwei Teile
zusammenpassen müssen, und merkt das erst im Integrationstest.

Die Phase folgt demselben Muster wie Phase 1 und 2: **AGENT** entwirft, **PYTHON** prüft
(vor allem: lässt sich alles auf die Anforderungen zurückführen?), **DU** änderst und gibst
frei. Soft Gate: Wer den Entwurf überspringt, plant wie bisher; der Pfad zeigt ihn gestrichelt.

## Ziele

- Ein Entwurf besteht aus **Bausteinen** (Rollen, Komponenten, Fremdsysteme),
  **Schnittstellen** (Verträge mit typisierten Feldern) und **Abläufen** (Schrittfolgen).
- Jeder Ablauf dient Anforderungen; jede Muss-Anforderung hat mindestens einen Ablauf.
- Das Sequenzdiagramm jedes Ablaufs zeichnet **Python** aus den Schritten und den Verträgen.
  Diagramm und Vertrag können sich deshalb nicht widersprechen.
- Der Entwurf ist als Markdown-Dokument herunterladbar, mit Mermaid-Diagrammen (GitHub
  zeigt sie als Bild).

## Nicht-Ziele (Batch 2)

- Testfälle aus den Verträgen (Batch 4).
- Aufgaben auf Schnittstellen zurückverfolgen und prüfen (Batch 4).
- Datenmodell, Klassendiagramm, OpenAPI-Export.
- „Mit dem Agenten ändern“-Dialog (wie in Batch 1 nicht gebaut).

## Anti-Ziele

- der Agent schreibt Diagrammcode (Mermaid, SVG). Dann könnte das Bild etwas anderes zeigen als
  die Daten.
- Neue Abhängigkeiten oder Skripte von fremden Servern (CDN) nur für Diagramme. Die Seite
  läuft nur an localhost.
- Ein Formular, das nur Informatiker ausfüllen können: Der Agent liefert den Entwurf, der Mensch
  korrigiert.

## Ansätze

**Format der Verträge** (vom Nutzer am 16.11.2026 freigegeben: typisierte Felder):

| | Typisierte Felder (gewählt) | Freier Text |
|---|---|---|
| Form | Eingabe/Ausgabe als `name: Typ`, Fehler als `Code Bedeutung` | je ein Satz für Eingabe, Ausgabe, Fehler |
| Python prüft | doppelte Feldnamen und Fehlercodes; Diagramm zeigt die Felder aus dem Vertrag | nur „ausgefüllt?“ |
| Batch 4 | Testfälle je Feld und Fehlercode ableitbar | Der Agent muss Text deuten |
| Aufwand für Nutzer | höher, aber der Agent füllt vor | gering |

**Diagramm zeichnen:**

| | SVG aus Python (gewählt) | Mermaid über CDN im iframe | `st.graphviz_chart` |
|---|---|---|---|
| Abhängigkeit | keine | Skript von fremdem Server | keine |
| Sequenzdiagramm | passt | passt | schlecht (Graph, keine Zeitachse) |
| testbar | ja (SVG ist XML) | nein | kaum |

## Datenformat (`models.py`)

```python
FieldName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
TypeName  = Annotated[str, Field(min_length=1, pattern=r"^[^,;:]+$")]   # kein , ; :

class DataField(_Model):   name: FieldName; type: TypeName; required: bool = True
class ErrorCase(_Model):   code: Ref; meaning: NonEmpty (kein Semikolon)
class Component(_Model):   id: Ref; name: NonEmpty; kind: Literal["Rolle", "Komponente", "Fremdsystem"]; purpose: str = ""
class Interface(_Model):   id: Ref; name: NonEmpty; provider: Ref; consumers: list[Ref] (min 1)
                           input: list[DataField] = []; output: list[DataField] = []; errors: list[ErrorCase] = []
class Step(_Model):        sender: Ref; receiver: Ref; kind: Literal["Aufruf", "Antwort"] = "Aufruf"
                           interface: Ref | None = None; text: str = ""
class Flow(_Model):        id: Ref; title: NonEmpty; requirement_ids: list[Ref]; steps: list[Step] (min 1)
class Design(_Model):      components: list[Component] (min 1); interfaces: list[Interface] = []; flows: list[Flow] (min 1)
```

- `Lifecycle` bekommt `design: Design | None` und `design_ok: Approval | None`. Alte
  `vorhaben.json` ohne diese Felder bleiben lesbar.
- Prüfsumme der Freigabe: Projekt, Auftrag, Anforderungen, Entwurf. Ändert sich eines davon,
  ist der Entwurf „geändert“.

## Prüfung (`lifecycle.check_design(design, requirements)`)

Fehler (Freigabe gesperrt, der Agent bekommt den Entwurf zurück):

1. Doppelte IDs bei Bausteinen, Schnittstellen, Abläufen; doppelte Feldnamen je Eingabe bzw.
   Ausgabe; doppelte Fehlercodes je Schnittstelle.
2. Anbieter oder Nutzer einer Schnittstelle ist kein bekannter Baustein; Anbieter ist eine
   Rolle.
3. Absender oder Empfänger eines Schritts ist kein bekannter Baustein; Schritt nennt eine
   unbekannte Schnittstelle.
4. Schritt widerspricht dem Vertrag: Bei „Aufruf“ muss der Empfänger der Anbieter und der
   Absender ein Nutzer sein, bei „Antwort“ umgekehrt.
5. Eine Schnittstelle kommt in keinem Ablauf vor.
6. Mit Anforderungen: ein Ablauf nennt eine unbekannte Anforderung; eine Muss-Anforderung hat
   keinen Ablauf.

Warnungen (Freigabe möglich):

- Soll- oder Kann-Anforderung ohne Ablauf.
- Ein Ablauf nennt keine Anforderung.
- Schritt zwischen zwei Nicht-Rollen ohne Schnittstelle (die Rolle → System-Bedienung braucht
  keine).
- Baustein kommt in keinem Ablauf vor.
- Ganz ohne Anforderungen: „lässt sich nicht gegen die Anforderungen prüfen“; Regel 6 entfällt.

Geprüft wird gegen die Anforderungen, wie sie in `vorhaben.json` stehen, ob freigegeben oder
nicht (wie Batch 1 gegen den Auftrag, wie er gerade steht). Regel 6 gilt also auch für nicht
freigegebene Anforderungen; dass sie nicht freigegeben sind, sagt der Hinweis im Panel
„Grundlage“. `run_design` schickt dem Agenten dieselben Anforderungen. *(Entscheidung des
Entwerfenden, nach dem Muster von Batch 1.)*

## Agent

- `lifecycle.run_design(project, charter, requirements, …)` mit Werkzeug `submit_entwurf`,
  noun „Entwurf“, Prompt `prompts/entwurf.md`, Log-Präfix `entwurf`; `tracking.AGENTS` um
  `entwurf` ergänzen. Nutzt `agent.run_submission`.
- An den Agenten gehen Idee, Termine, Auftrag, Anforderungen. Keine Teamdaten.
- Der Prompt verlangt: Rollen aus den Beteiligten des Auftrags, kurze IDs (`B1`, `S1`, `A1`),
  einfache Typen (`Text`, `Zahl`, `Ganzzahl`, `Datum`, `Uhrzeit`, `JaNein`, `Liste[X]`, oder
  ein Baustein-Objekt), höchstens etwa 8 Abläufe.
- `max_tokens` (16 000) reicht nach Schätzung für etwa 10 Abläufe mit je 8 Schritten; wird es
  knapp, meldet die Schleife das wie bisher als Fehler.

## Diagramm (`src/pm_agent/diagram.py`, neu)

- `sequence_svg(flow, design) -> str`: Teilnehmer in der Reihenfolge ihres ersten Auftretens
  als Spalten, gestrichelte Lebenslinien, ein Pfeil je Schritt (Aufruf durchgezogen, Antwort
  gestrichelt, Schritt an sich selbst als Schleife). Beschriftung aus dem Vertrag:
  Aufruf `S1 Buchung anlegen(raum, datum)`, Antwort `buchung_id` bzw. Schrittext. Rollen mit
  Figur-Symbol. Farben über `currentColor`, damit helles und dunkles Thema passen. Text mit
  `html.escape`.
- `sequence_mermaid(flow, design) -> str` für das Markdown-Dokument; Sonderzeichen als
  Mermaid-Entitäten (`#59;` usw.).

## Seite `views/entwurf.py`

Menügruppe „Vorbereiten“ nach Anforderungen, Symbol `:material/account_tree:`. Panels wie die
Anforderungen-Seite:

1. Grundlage: Hinweis, wenn Anforderungen fehlen oder nicht freigegeben sind (Soft Gate).
2. Entwurf vom Agenten (Ersetzen-Checkbox wie bisher).
3. Bausteine: vier Tabellen in `st.tabs`: Bausteine, Schnittstellen (Eingabe/Ausgabe als
   `name: Typ, name?: Typ`; `?` = optional; Fehler als `409 Raum belegt; 404 Raum unbekannt`),
   Abläufe (ID, Titel, Anforderungen), Schritte (Ablauf, Von, An, Art, Schnittstelle, Text;
   Reihenfolge = Zeilenreihenfolge je Ablauf). Ein Knopf speichert alle vier.
4. Diagramme: Auswahl eines Ablaufs, SVG über `st.html`.
5. Freigabe, 6. Dokument (Vorlage `templates/entwurf.md`).

Lade-, Leer- und Fehlerzustände wie auf den Seiten aus Batch 1.

## Projektpfad und Planung

- `ui.JOURNEY` bekommt `entwurf` zwischen Anforderungen und Planung (6 Schritte).
- Planung: Ist der Entwurf freigegeben, bekommt der Planungsagent Bausteine und
  Schnittstellen als Kontext („Freigegebener Entwurf:“), damit Aufgaben entlang der
  Komponenten geschnitten werden. Keine neue Prüfung, keine neue Spalte. Ohne Freigabe ändert
  sich nichts. Chip „Entwurf“ in der Statusleiste der Planung.
- `approved_design(life)` hängt nur an der Freigabe des Entwurfs, nicht an der der
  Anforderungen (Soft Gate wie in Batch 1). Damit der Planungsagent keine Anforderungs-IDs
  sieht, die er selbst nicht zuordnet, gehen nur Bausteine und Schnittstellen an ihn, keine
  Abläufe. Gilt für „Plan erstellen“ und „Rest neu planen“. *(Entscheidung des Entwerfenden.)*

## Dem Bauenden überlassen

- Genaue Maße und Abstände im SVG.
- Wortlaut der Meldungen, solange er die Form von Batch 1 hat („Ablauf 'A1', Schritt 3: …“).
- Aufteilung in Commits (TDD, wie in Batch 1).

## Annahmen

- Rollen stehen als Bausteine im Entwurf, damit sie im Diagramm erscheinen; sie werden nicht
  automatisch aus dem Auftrag übernommen, der Agent schlägt sie vor.

## Bekannte Grenzen

- Schritte sind über die Zeilenreihenfolge geordnet; Verschieben einer Zeile im Editor geht
  in Streamlit nicht, nur Löschen und neu Einfügen.
- Keine Verzweigungen oder Schleifen (`alt`, `loop`) im Ablauf; ein Fehlerfall wird als
  eigener Ablauf beschrieben.
- Die neuen Prompts laufen ohne Auftrag des Nutzers nicht gegen die echte API.
