# Entscheidungen

Beschlüsse zu Studie und Werkzeug, mit Datum und Begründung. Ein Vorschlag ist kein Beschluss: Er steht erst hier, wenn er gefallen ist. Eine spätere Entscheidung ersetzt eine frühere nicht stillschweigend; sie nennt die ID, die sie ablöst.

Neue Einträge haben die Form: ID, Datum, wer entschieden hat (als Rolle), Frage, Beschluss, Begründung, Folgen, Issue.

## E01: Modellstand ohne datierten Snapshot

- **Datum:** 21.11.2026
- **Entschieden von:** Projektleitung
- **Frage:** Der Freeze des KI-Labs verlangte eine datierte Modell-Snapshot-ID (Name endet auf `JJJJ-MM-TT`). Das Modell am Endpunkt der Hochschule, `gpt-6-sol`, hat keine. Damit war die formale Studie gesperrt.
- **Beschluss:** Der Freeze verlangt einen API-Key und einen Modellnamen, kein Datum. Der Name wird mit der Konfiguration eingefroren; ändert er sich danach, sperrt das Lab formale Sitzungen wie bisher. Jeder KI-Aufruf speichert das Modell, das der Anbieter als antwortend meldet (`model_returned`). Die Auswertung nennt alle diese Modelle (`models_returned`) und ob es mehr als eines war (`model_varies`).
- **Begründung:** Ein datiertes Modell ist am verfügbaren Endpunkt nicht zu bekommen. Ohne Freeze gäbe es keine formale Studie. Der gemeldete Modellname je Aufruf macht sichtbar, ob sich der Modellstand während der Erhebung geändert hat.
- **Folgen:**
  - Ein Wechsel des Modells hinter demselben Namen ist nicht ausgeschlossen, und der gemeldete Name zeigt ihn nur, wenn der Anbieter den Namen ändert.
  - Der Bericht nennt das als Grenze (`05-Ergebnisse`).
  - Die Erhebung soll in einem kurzen Zeitraum laufen.
- **Issue:** #9 (Kriterium „Echter Provider-Erfolg mit gewähltem Snapshot“), Code in `04-Prototyp/ki_lab/lab.py` (`freeze`) und `analysis.py` (`summarize`).
