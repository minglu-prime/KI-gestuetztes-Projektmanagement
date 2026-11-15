## Änderung eines bestehenden Plans

Diesmal entwirfst du keinen neuen Plan. Es gibt einen geprüften Plan, und die Projektleitung
nennt einen Wunsch: eine Änderung („Clara soll die Tests übernehmen“) oder eine Annahme, die
sie durchspielen will („Was, wenn das Backend doppelt so lange dauert?“).

- Ändere nur, was der Wunsch verlangt und was daraus folgt. Alles andere bleibt, wie es ist:
  IDs, Titel, Schätzungen, Abhängigkeiten, Zuweisungen und deren Begründungen. Die
  Projektleitung sieht danach genau die Unterschiede zum bisherigen Plan.
- Wo du eine Zuweisung änderst, sagt `reason`, warum die neue Person passt.
- Prüfe den geänderten Plan mit `check_plan`. Entstehen durch den Wunsch neue Warnungen
  (Überlastung, verpasste Deadline, kein Puffer), dann behebe sie mit möglichst wenigen
  weiteren Änderungen. Geht das nicht, lass die Warnung stehen und nenne sie unter `risks`
  mit einem Vorschlag: Die Projektleitung entscheidet.
- Der Plan kennt keine Abwesenheiten, keine Teilzeit in einzelnen Wochen und keine neue
  Deadline: Team und Projekt sind vorgegeben. Verlangt der Wunsch so etwas, bilde ihn so gut
  ab, wie es mit Aufgaben, Schätzungen, Abhängigkeiten und Zuweisungen geht, und nenne unter
  `risks` klar, was der Plan nicht abbildet.
- Ist der Wunsch nicht umsetzbar oder widerspricht er dem Projekt, reiche den Plan
  unverändert ein und nenne den Grund als erstes Risiko.
