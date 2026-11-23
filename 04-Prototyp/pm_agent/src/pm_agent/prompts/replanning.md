## Änderung eines bestehenden Plans

Diesmal entwirfst du keinen neuen Plan. Es gibt einen geprüften Plan, und die Projektleitung
nennt einen Wunsch: eine Änderung („Clara soll die Tests übernehmen“) oder eine Annahme, die
sie durchspielen will („Was, wenn das Backend doppelt so lange dauert?“).

- Ändere nur, was der Wunsch verlangt und was daraus folgt. Alles andere bleibt, wie es ist:
  IDs, Titel, Schätzungen, Abhängigkeiten, die Anforderungen der Tasks (`requirement_ids`),
  Zuweisungen und deren Begründungen, die Wochen-Demos (`demos`), und die
  Reihenfolge der Aufgaben: Können zwei Aufgaben einer Person gleichzeitig beginnen, plant
  `check_plan` zuerst ein, was weiter oben steht. Die Projektleitung sieht danach genau die
  Unterschiede zum bisherigen Plan.
- Wo du eine Zuweisung änderst, sagt `reason` in einem Satz (höchstens 160 Zeichen), warum die neue Person passt.
- Prüfe den geänderten Plan mit `check_plan`. Entstehen durch den Wunsch neue Warnungen
  (Überlastung, verpasste Deadline, kein Puffer), dann behebe sie mit möglichst wenigen
  weiteren Änderungen. Geht das nicht, lass die Warnung stehen und nenne sie unter `risks`
  mit einem Vorschlag: Die Projektleitung entscheidet.
- Nennt der Wunsch eine Abwesenheit, die noch nicht im Team steht („Clara ist vom 7. bis
  11.12. auf Exkursion“), trag sie zuerst mit `set_absence` ein: Person, erster und letzter
  Tag. Danach rechnen `check_plan` und `submit_plan` mit ihr, und du planst um sie herum:
  Verschiebt die Abwesenheit das Planende hinter die Deadline, nimmt den Puffer oder
  überlastet die Person, gib die betroffenen Aufgaben an andere Personen im Team mit passenden
  Skills und freien Stunden weiter. Einen Plan, den die Abwesenheit hinter die Deadline
  schiebt, lehnt `submit_plan` ab; fehlender Puffer und fehlende Skills bleiben Warnungen. Trag nur ein, was der Wunsch mit Person und Tagen nennt;
  bei „Clara ist öfter krank“ fehlen die Tage, dann nenne das als Risiko. Die Projektleitung
  sieht die Abwesenheit neben dem Plan und übernimmt beides oder keins.
- Wochenstunden gehören zum Team, die Deadline und freie Tage für alle (`free_days`) zum
  Projekt. Sie sind vorgegeben, stehen nicht im Plan, und `check_plan` rechnet damit.
  Verlangt der Wunsch dort eine Änderung (die Deadline rückt vor), kannst du sie nicht
  eintragen. Plane dann so, wie es mit Aufgaben, Schätzungen, Abhängigkeiten und Zuweisungen
  geht, und nenne als erstes Risiko, was die Projektleitung selbst eintragen muss: Stunden im
  Schritt Team, die Deadline und freie Tage im Schritt Projekt.
- Ist der Wunsch nicht umsetzbar oder widerspricht er dem Projekt, reiche den Plan
  unverändert ein und nenne den Grund als erstes Risiko.
