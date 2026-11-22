# Migrationsplan: PM-Agent im Netz (Weg A)

> **Entwurf, von der Projektleitung und der Gruppe zu bestätigen.** Stand 22.11.2026, `main`
> nach PR 80. Nichts davon ist umgesetzt. Offene Entscheidungen sind als **Entscheidung**
> markiert.

## Ziel und Rahmen

Die Streamlit-Seite läuft heute nur auf `localhost` und speichert in Dateien. Ziel: Die Gruppe
nutzt sie über das Netz, mit Anmeldung, ohne dass der Schlüssel oder das Kontingent offenliegt.

Weg A heißt: **Streamlit bleibt**, läuft als dauerhafter Prozess in einem Container; die Daten
gehen in **Supabase Postgres**. Die Agenten laufen weiter im Prozess der Seite (`agent._run`),
wie heute. Ein dauerhafter Prozess hat keine Zeitgrenze pro Anfrage, deshalb kein Umbau der
Agenten. Vercel wird nicht gebraucht; Cloudflare höchstens für Domain und DNS.

Nicht Teil der Migration:

- **KI-Lab.** Bleibt lokal (eigener Server, SQLite, Studiendaten). Im Netzbetrieb zeigt die
  Seite KI-Lab nur einen Hinweis.
- Neue Funktionen. Jede Seite verhält sich wie lokal; alle 650 Offline-Tests laufen weiter.

## Vorbedingungen (vor jeder Zeile Code)

1. **KI:connect außerhalb des eigenen Rechners.** Darf der Schlüssel auf einem Server für die
   Gruppe genutzt werden, und antwortet der Dienst von außerhalb des Hochschulnetzes? Bei
   Nein endet Weg A hier, oder der Server muss im Hochschulnetz stehen.
2. **Datenschutz.** Team-Daten (Name, Skills, Stunden, Abwesenheit) sind personenbezogen.
   Supabase-Projekt und Container in der EU (z. B. Frankfurt). Die Einwilligungen nennen dann
   neben dem KI-Dienst auch den Speicherort. Löschfrist festlegen. **Entscheidung.**
3. **Kostenfreie Stufen prüfen.** Grenzen und Pausenregeln von Supabase und dem Hoster
   ändern sich; vor der Wahl nachlesen und hier mit Datum eintragen. Bekannt ist, dass
   kostenfreie Supabase-Projekte bei Inaktivität pausieren können.

## Was heute in Dateien liegt

| Datei | Modul, Funktionen | Inhalt | Ziel |
|---|---|---|---|
| `data/vorhaben.json` | `lifecycle.load/save/save_if_current` | Auftrag, Anforderungen, Entwurf, Testplan, Backlog | Tabelle `vorhaben` |
| `data/projekt.json` | `tracking.load/save/require_current/save_if_current` | übernommener Plan, Fortschritt, Tests, Abnahme, Betrieb | Tabelle `projekte` |
| `data/team.json` | `workbench.load_team/save_team` | Team | Tabelle `teams` |
| `logs/run-*.json` | `agent` (schreibt), `workbench.saved_runs/load_run`, `tracking` Z. 1580 (liest) | Protokoll jedes Agentenlaufs | Tabelle `agent_runs` |
| `logs/runs.csv` | `workbench.append_run/read_runs` | eine Zeile je Export | Tabelle `exporte` |
| `data/archiv/<Datum>/` | `closing.start_next_run` | abgeschlossene Durchläufe | Tabelle `archiv` |

Die Seiten rufen diese Funktionen an 33 Stellen auf (`planung` 13, `abschluss` 6,
`kontrolle` 5, `testlauf` 4, `durchfuehrung` 2, `ui` 3). Nur `views/abschluss.py` baut einen
Pfad selbst (`DATA_DIR / "archiv"`).

Gleichzeitigkeit heute: `tracking.PROJECT_WRITE_LOCK` und `lifecycle.WRITE_LOCK` gelten nur
innerhalb eines Prozesses; `save_if_current` vergleicht den alten mit dem gespeicherten Stand.

## Entwurf

### Speicher hinter einer Naht

Ein Modul `store.py` mit den heutigen Funktionen als Schnittstelle (laden, speichern, nur
speichern wenn unverändert, Lauf protokollieren, Läufe lesen, Export anhängen, archivieren).
Zwei Umsetzungen:

- **Dateien** (Standard, lokal, Tests): der heutige Code, unverändert verschoben.
- **Postgres**, aktiv wenn `DATABASE_URL` gesetzt ist.

Die Pydantic-Modelle bleiben die Quelle; gespeichert wird je Dokument das ganze Modell als
`jsonb`, wie heute als Datei. Keine Normalisierung in viele Tabellen: Die Rechnungen
(`working_shift`, `evaluate`, Prüfungen) bleiben in Python (AGENTS.md: eine Quelle je
Rechengröße), die Datenbank speichert nur.

### Tabellen (Skizze)

```sql
create table arbeitsbereiche (            -- eine Gruppe, ein Projekt zur Zeit
  id   bigint generated always as identity primary key,
  name text not null
);

create table mitglieder (                 -- wer sich anmelden darf
  email            text primary key,
  arbeitsbereich_id bigint not null references arbeitsbereiche (id)
);
create index on mitglieder (arbeitsbereich_id);

create table vorhaben (                   -- gleiches Muster für projekte und teams
  arbeitsbereich_id bigint primary key references arbeitsbereiche (id),
  daten   jsonb not null,
  version bigint not null default 1,
  geaendert timestamptz not null default now()
);

create table agent_runs (
  id bigint generated always as identity primary key,
  arbeitsbereich_id bigint not null references arbeitsbereiche (id),
  art text not null,                      -- run, status, control, charter, ...
  gestartet timestamptz not null default now(),
  protokoll jsonb not null
);
create index on agent_runs (arbeitsbereich_id, art, gestartet desc);

create table exporte (
  id bigint generated always as identity primary key,
  arbeitsbereich_id bigint not null references arbeitsbereiche (id),
  zeit timestamptz not null default now(),
  zeile jsonb not null
);
create index on exporte (arbeitsbereich_id, zeit);

create table archiv (
  id bigint generated always as identity primary key,
  arbeitsbereich_id bigint not null references arbeitsbereiche (id),
  archiviert timestamptz not null default now(),
  vorhaben jsonb, projekt jsonb
);
create index on archiv (arbeitsbereich_id);

-- Nur der Server greift zu. Die öffentliche Data API von Supabase sieht nichts:
alter table arbeitsbereiche enable row level security;  -- ebenso für jede Tabelle oben,
-- ohne Policy für anon und authenticated.
```

### Gleichzeitigkeit

`save_if_current` wird zu einem bedingten Schreiben mit der Spalte `version`:

```sql
update projekte set daten = $1, version = version + 1, geaendert = now()
where arbeitsbereich_id = $2 and version = $3;   -- 0 Zeilen: inzwischen geändert
```

Das ersetzt die Prozess-Sperren und gilt auch, wenn zwei Personen in zwei Browsern arbeiten.
Die Meldung „wurde inzwischen geändert“ bleibt dieselbe. `start_next_run` wird eine
Transaktion: in `archiv` einfügen, `projekte` löschen, `vorhaben` auf den Backlog setzen.
Nichts wird halb archiviert (heute: Dateien umbenennen und bei Fehler zurück).

### Verbindung

Python verbindet sich mit `psycopg` über den Pooler von Supabase im Transaktionsmodus,
deshalb ohne vorbereitete Anweisungen (`prepare_threshold=None`). Ein Verbindungspool im
Prozess, Transaktionen kurz: Agentenläufe halten keine Verbindung offen, gespeichert wird
erst nach dem Lauf. Neue Abhängigkeit: `psycopg[binary,pool]`.

### Anmeldung und Arbeitsbereich

- Anmeldung mit `st.login` (OIDC). **Entscheidung:** Anbieter (Hochschul-SSO, falls
  verfügbar; sonst Microsoft oder Google).
- Nach der Anmeldung sucht die Seite die E-Mail in `mitglieder`. Unbekannt: kein Zugang.
  Bekannt: alle Abfragen mit dieser `arbeitsbereich_id`.
- **Entscheidung:** zunächst ein Arbeitsbereich für die Gruppe, oder einer je Person/Team.

### Schlüssel und Kontingent

- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `PM_AGENT_MODEL`, `DATABASE_URL` und die
  OIDC-Werte nur als Secrets des Hosters; nie im Repository, nie im Browser.
- Vor jedem Agentenlauf zählt die Seite die Läufe des Tages in `agent_runs`. Über der Grenze
  (`PM_AGENT_DAILY_LIMIT`) bleibt der Knopf aus, mit Grund. **Entscheidung:** Grenze.
- Ein Lauf je Arbeitsbereich zur Zeit.

### Netzbetrieb erkennen

Eine Einstellung (`PM_HOSTED=1`) schaltet ab, was nur lokal Sinn hat: KI-Lab-Start
(`lab_server`), Pfadangaben wie „data/projekt.json“ in Meldungen, `--server.address
localhost`. `test_launch.py` prüft weiter den lokalen Start.

### Hosting

Ein Container (`Dockerfile`: `uv sync --locked`, `streamlit run app.py --server.address
0.0.0.0`), EU-Region, dauerhaft laufend. **Entscheidung:** Hoster (Kandidaten: Hugging Face
Spaces, Render, ein Server der Hochschule; Bedingungen unter Vorbedingung 3).

## Schritte als PRs (je unter etwa 800 Zeilen)

1. **Naht ohne Verhaltensänderung.** `store.py` mit Datei-Umsetzung; alle 33 Aufrufe und
   `abschluss.py` gehen darüber. Quellregel in `test_source_rules.py`: kein `read_text`,
   `write_text`, `open(` oder `DATA_DIR` außerhalb von `store.py`. Alle Tests grün,
   `data/` unverändert.
2. **Postgres-Umsetzung.** SQL-Migration unter `supabase/migrations/`, `store` für Postgres,
   versioniertes Schreiben, Archiv als Transaktion. Ein gemeinsamer Vertragstest für beide
   Umsetzungen; gegen Postgres läuft er nur mit `TEST_DATABASE_URL` (lokal über Supabase CLI
   oder Docker), in der CI als eigener Job mit einem Postgres-Dienst. Fälle: altes gültiges
   Dokument, beschädigtes Dokument, zwei gleichzeitige Speicherungen, Abbruch mitten im
   Archivieren.
3. **Anmeldung, Arbeitsbereich, Kontingent, `PM_HOSTED`.** AppTest-Fälle: ohne Anmeldung kein
   Inhalt, fremde E-Mail abgewiesen, Grenze erreicht, KI-Lab im Netz nur als Hinweis.
   Einwilligungstexte nennen den Speicherort (Quellregel wie bei `ui.ai_service`).
4. **Bereitstellung.** `Dockerfile`, Anleitung in der README, Secrets-Liste. Prüfung im
   Browser auf der bereitgestellten Seite: Anmeldung, ein Durchlauf mit Ersatzdaten, 375 px.
   Ein echter Agentenlauf nur auf Wort der Projektleitung.
5. **Dokumente.** `teilnahmeinformation.md`, Startseite, beide READMEs, `CLAUDE.md`
   (Abschnitt „Betrieb“) nachziehen.

Daten von `data/` werden nicht übernommen (es ist das erfundene Beispielprojekt). Wer ein
lokales Projekt mitnehmen will: ein kleines Einspielskript in Schritt 2, nur auf Wunsch.

## Risiken

| Risiko | Folge | Gegenmaßnahme |
|---|---|---|
| KI:connect nur im Hochschulnetz | Agenten antworten nicht | Vorbedingung 1 klären, sonst Server im Hochschulnetz |
| Kostenfreies Projekt pausiert | Seite ohne Daten bis zum Aufwecken | Grenzen prüfen; Meldung statt Absturz (wie heute bei beschädigter Datei) |
| Neustart des Containers während eines Laufs | Lauf verloren, Daten unverändert | gespeichert wird erst nach dem Lauf; Lauf neu starten |
| Mehrere Prozesse des Hosters | Prozess-Sperren greifen nicht | versioniertes Schreiben (oben) statt Sperren |
| Verbindungen erschöpft | Fehler beim Laden | Pool klein, Pooler im Transaktionsmodus |

## Offene Entscheidungen (Zusammenfassung)

1. KI:connect im Netz erlaubt und erreichbar?
2. Hoster und Region.
3. Anmeldung: welcher Anbieter.
4. Ein Arbeitsbereich für die Gruppe oder mehrere.
5. Tagesgrenze für Agentenläufe.
6. Löschfrist und Text der Einwilligung.
