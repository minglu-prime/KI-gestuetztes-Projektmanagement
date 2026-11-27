"""Operator-only commands. Keep data exports outside version control."""
import argparse
import json
import random
import sys
from pathlib import Path

from analysis import export_bundle, summarize
from lab import ROOT, Lab, Problem


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load_ratings(paths):
    rows = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise Problem(f'Bewertungsdatei nicht gefunden: {path}') from None
        except (OSError, ValueError) as exc:
            raise Problem(f'Bewertungsdatei ungültig: {path} ({exc})') from None
        if not isinstance(data, list):
            raise Problem(f'Bewertungsdatei ungültig: {path} muss eine JSON-Liste enthalten.')
        rows.extend(data)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=str(ROOT / 'data' / 'lab.db'))
    parser.add_argument('--materials', default=None, metavar='DATEI',
                        help='privates Fallmaterial (sonst PM_LAB_MATERIALS, sonst cases.json)')
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('freeze')
    freeze.add_argument('--attestation', required=True)
    enroll = sub.add_parser('enroll')
    enroll.add_argument('--count', type=int, default=12)
    enroll.add_argument('--seed', type=int, default=20261030)
    enroll.add_argument('--start', type=int, default=1)
    enroll.add_argument('--port', type=int, default=8874)
    export = sub.add_parser('export')
    export.add_argument('--out', required=True)
    export.add_argument('--include-pilots', action='store_true')
    analyze = sub.add_parser('analyze')
    analyze.add_argument('--ratings', action='extend', nargs='+', metavar='DATEI',
                         help='Bewertungsdatei(en), z. B. R1/ratings.json R2/ratings.json (mehrfach nutzbar)')
    analyze.add_argument('--include-pilots', action='store_true',
                         help='Pilot-Sitzungen einschließen (z. B. für Raterkalibrierung)')
    analyze.add_argument('--out', required=True)
    delete = sub.add_parser('delete', help='Sitzung einer Teilnehmerkennung dauerhaft löschen')
    delete.add_argument('participant', metavar='KENNUNG', help='Teilnehmerkennung, z. B. P001 oder PILOT-…')
    delete.add_argument('--confirm', action='store_true', help='Dauerhaftes Löschen ausdrücklich bestätigen')
    sub.add_parser('status')
    args = parser.parse_args(argv)
    try:
        lab = Lab(args.db, materials=args.materials)
    except Problem as exc:  # missing or malformed case file: say why and stop
        parser.error(str(exc))
    try:
        if args.command == 'freeze':
            print(json.dumps(lab.freeze(args.attestation), ensure_ascii=False, indent=2))
        elif args.command == 'enroll':
            if not 1 <= args.count <= 100 or args.start < 1 or args.start + args.count > 1000:
                raise Problem('Ungültiger Kennungsbereich oder Anzahl.')
            rng = random.Random(args.seed)
            groups = []
            while len(groups) < args.count:
                block = [1, 2, 3, 4]
                rng.shuffle(block)
                groups.extend(block)
            existing = {s['participant'] for s in lab.raw()}
            ids = [f'P{i:03}' for i in range(args.start, args.start + args.count)]
            if existing.intersection(ids):
                raise Problem('Kennungen schon vorhanden; --start anpassen, vorhandene Einladungen verwenden.')
            invitations = []
            for participant, group in zip(ids, groups):
                created = lab.create(group=group, pilot=False, participant=participant)
                invitations.append({'participant':participant, 'group':group, 'seed':args.seed,
                    'url':f'http://127.0.0.1:{args.port}/#session={created["token"]}'})
            destination = lab.path.parent / f'invitations-{args.start:03}.json'
            write_json(destination, invitations)
            print(f'{len(invitations)} Einladungen: {destination}')
        elif args.command == 'export':
            destination = Path(args.out)
            if destination.exists():
                raise Problem('Exportziel existiert bereits. Neues Verzeichnis wählen.')
            bundle = export_bundle(lab.raw(), args.include_pilots)
            write_json(destination / 'private' / 'raw.json', bundle['raw'])
            write_json(destination / 'private' / 'key.json', bundle['key'])
            for rater in ('R1', 'R2'):
                write_json(destination / rater / 'answers.json', bundle['blinded'])
                write_json(destination / rater / 'ratings.json', [r for r in bundle['ratings_template'] if r['rater']==rater])
            print(f'{len(bundle["blinded"])} Ergebnisse exportiert. Nur R1 bzw. R2 an die Bewertenden geben.')
        elif args.command == 'analyze':
            ratings = load_ratings(args.ratings) if args.ratings else None
            report = summarize(lab.raw(), ratings, include_pilots=args.include_pilots)
            write_json(Path(args.out), report)
            scope = 'Teilnehmende (inkl. Piloten)' if args.include_pilots else 'formale Teilnehmende'
            not_started = len(report['not_started_participants'])
            extra = f' ({report["invited"]} eingeladen, {not_started} nicht gestartet)' if not_started else ''
            pairs_n = report['complete_pairs']
            qpairs_n = len(report['quality_pairs'])
            pairs_label = 'vollständiges Zeitpaar' if pairs_n == 1 else 'vollständige Zeitpaare'
            qpairs_label = 'Qualitätspaar' if qpairs_n == 1 else 'Qualitätspaare'
            print(
                f'Analyse: {report["participants"]} {scope}{extra}, '
                f'{pairs_n} {pairs_label}, {qpairs_n} {qpairs_label}.'
            )
            for warning in report['warnings']:
                print('Warnung: ' + warning, file=sys.stderr)
        elif args.command == 'delete':
            if not args.confirm:
                raise Problem(f'Löschen von {args.participant} nicht bestätigt. Mit --confirm erneut ausführen.')
            result = lab.delete(args.participant)
            print(
                f'Gelöscht: {result["deleted"]} ({result["sessions_removed"]} Sitzung(en) entfernt). '
                'Vorhandene Exporte und Einladungslisten bei Bedarf getrennt prüfen.'
            )
            if not result['compacted']:
                print(
                    'Warnung: Datenbankdatei konnte wegen aktivem Zugriff nicht verdichtet werden '
                    '(Server stoppen und Datenbank prüfen).',
                    file=sys.stderr,
                )
        elif args.command == 'status':
            records = lab.raw()
            print(json.dumps({'pilot_sessions':sum(s['pilot'] for s in records),
                              'formal_sessions':sum(not s['pilot'] for s in records),
                              'ai_configured':bool(lab.api_key and lab.model), 'config':lab.config()}, indent=2))
    except (Problem, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
    finally:
        lab.close()


if __name__ == '__main__':
    main()
