"""Operator-only commands. Keep data exports outside version control."""
import argparse
import json
import random
from pathlib import Path

from analysis import export_bundle, summarize
from lab import ROOT, Lab, Problem


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=str(ROOT / 'data' / 'lab.db'))
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
    analyze.add_argument('--ratings')
    analyze.add_argument('--out', required=True)
    sub.add_parser('status')
    args = parser.parse_args()
    lab = Lab(args.db)
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
            ratings = json.loads(Path(args.ratings).read_text(encoding='utf-8')) if args.ratings else None
            report = summarize(lab.raw(), ratings)
            write_json(Path(args.out), report)
            print(f'Analyse: {report["participants"]} formale Teilnehmende, {report["complete_pairs"]} vollständige Zeitpaare.')
        else:
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
