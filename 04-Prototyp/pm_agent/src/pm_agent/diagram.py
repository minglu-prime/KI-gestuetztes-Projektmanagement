"""Sequence diagrams of the design, drawn by Python from the steps of a flow and the
contracts of its interfaces. The agent never writes diagram code: what the picture shows is
what the data says.

Two forms: SVG for the page (no library, nothing loaded from elsewhere) and Mermaid text
for the Markdown document (GitHub draws it).
"""

from html import escape

from pm_agent.models import Design, Flow, Step

COLUMN = 170  # px between two lifelines
ROW = 44  # px between two steps
TOP = 64  # px down to the first step
SIDE = 20


def _text(text: str) -> str:
    """Text for the SVG: escaped, and on one line. The page shows the SVG through
    st.markdown, where a blank line would end the HTML block."""
    return escape(" ".join(text.split()))


def _participants(flow: Flow) -> list[str]:
    """Part IDs in the order they first appear in the flow."""
    return list(dict.fromkeys(part for s in flow.steps for part in (s.sender, s.receiver)))


def _label(step: Step, design: Design) -> str:
    """What the arrow says: the call with its input fields, the answer with its output
    fields, or the text of a step without interface."""
    contract = next((i for i in design.interfaces if i.id == step.interface), None)
    if contract is None:
        return " · ".join(filter(None, [step.interface or "", step.text]))
    if step.kind == "Aufruf":
        said = f"{contract.id} {contract.name}({', '.join(f.name for f in contract.input)})"
    else:
        said = ", ".join(f.name for f in contract.output) or contract.name
    return " · ".join(filter(None, [said, step.text]))


def sequence_svg(flow: Flow, design: Design) -> str:
    parts = _participants(flow)
    names = {c.id: c for c in design.components}
    x = {part: SIDE + COLUMN // 2 + n * COLUMN for n, part in enumerate(parts)}
    width = 2 * SIDE + COLUMN * len(parts)
    height = TOP + ROW * len(flow.steps) + 24
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="sequence" role="img" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'aria-label="{_text(f"Sequenzdiagramm {flow.id}: {flow.title}")}" '
        'font-family="sans-serif" font-size="12" fill="currentColor" stroke="currentColor">',
        '<defs><marker id="head" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z"/></marker>'
        "</defs>",
    ]
    for part in parts:
        component = names.get(part)
        name = component.name if component else part
        role = component is not None and component.kind == "Rolle"
        cx = x[part]
        figure = (
            f'<circle cx="{cx - 58}" cy="22" r="5" fill="none"/>' if role else ""
        )  # a head marks a role
        out.append(
            f'<g class="participant">{figure}'
            f'<rect x="{cx - 70}" y="8" width="140" height="28" rx="{14 if role else 4}" '
            'fill="none"/>'
            f'<text x="{cx}" y="26" text-anchor="middle" stroke="none">{_text(name)}</text>'
            f'<line class="lifeline" x1="{cx}" y1="36" x2="{cx}" y2="{height - 8}" '
            'stroke-dasharray="4 4" stroke-opacity="0.5"/></g>'
        )
    for n, step in enumerate(flow.steps):
        y = TOP + n * ROW
        a, b = x[step.sender], x[step.receiver]
        dash = ' stroke-dasharray="6 4"' if step.kind == "Antwort" else ""
        kind = "reply" if step.kind == "Antwort" else "call"
        if a == b:  # a step to itself
            arrow = (
                f'<path class="self" d="M{a},{y} h30 v14 h-30" fill="none"{dash} '
                'marker-end="url(#head)"/>'
            )
            label_x, anchor = a + 36, "start"
        else:
            arrow = (
                f'<line class="{kind}" x1="{a}" y1="{y}" x2="{b}" y2="{y}"{dash} '
                'marker-end="url(#head)"/>'
            )
            label_x, anchor = (a + b) // 2, "middle"
        out.append(
            f'<g class="step">{arrow}<text x="{label_x}" y="{y - 6}" text-anchor="{anchor}" '
            f'stroke="none">{_text(_label(step, design))}</text></g>'
        )
    out.append("</svg>")
    return "".join(out)


def _mermaid(text: str) -> str:
    # Mermaid reads ";" as a line break, "#" as the start of an entity and "<…>" as HTML; a
    # backtick could end the code block the document puts the diagram in. One pass, since
    # "#35;" itself has a ";".
    text = " ".join(text.split())
    return text.translate(
        {
            ord("#"): "#35;",
            ord(";"): "#59;",
            ord("`"): "#96;",
            ord("<"): "#60;",
            ord(">"): "#62;",
        }
    )


def sequence_mermaid(flow: Flow, design: Design) -> str:
    """Mermaid text. Parts get aliases p1, p2 …: an ID like "B-1" would read as an arrow."""
    parts = _participants(flow)
    alias = {part: f"p{n}" for n, part in enumerate(parts, start=1)}
    names = {c.id: c for c in design.components}
    lines = ["sequenceDiagram"]
    for part in parts:
        component = names.get(part)
        kind = "actor" if component is not None and component.kind == "Rolle" else "participant"
        lines.append(f"  {kind} {alias[part]} as {_mermaid(component.name if component else part)}")
    for step in flow.steps:
        arrow = "-->>" if step.kind == "Antwort" else "->>"
        label = _mermaid(_label(step, design)) or " "
        lines.append(f"  {alias[step.sender]}{arrow}{alias[step.receiver]}: {label}")
    return "\n".join(lines)
