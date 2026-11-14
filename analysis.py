"""Anonymous rating packets and descriptive paired analysis; no invented observations."""
import statistics

CAPS = {'dependencies': 20, 'resources': 15, 'milestones': 15,
        'risk_identification': 20, 'prioritization': 15, 'measures': 15}


def export_bundle(records, include_pilots=False):
    selected = [s for s in records if include_pilots or not s['pilot']]
    blinded, key, templates = [], [], []
    for s in selected:
        for r in s['rounds']:
            if r['status'] not in ('submitted', 'timed_out'):
                continue
            rid = r['rating_id']
            blinded.append({'rating_id': rid, 'case_id': r['case_id'], **r['final']})
            key.append({'rating_id': rid, 'participant': s['participant'], 'condition': r['condition'],
                        'case_id': r['case_id'], 'group': s['group'], 'status': r['status']})
            for rater in ('R1', 'R2'):
                templates.append({'rating_id': rid, 'rater': rater, **{k: None for k in CAPS},
                                  'severe_errors': None, 'notes': ''})
    return {'raw': selected, 'blinded': sorted(blinded, key=lambda r:r['rating_id']),
            'key': key, 'ratings_template': sorted(templates, key=lambda r:(r['rater'], r['rating_id']))}


def summarize(records, ratings=None):
    records = [s for s in records if not s['pilot']]
    seen, grades = set(), {}
    valid_ids = {r['rating_id'] for s in records for r in s['rounds']
                 if r['status'] in ('submitted', 'timed_out')}
    for row in ratings or []:
        key = (row['rating_id'], row['rater'])
        if key in seen:
            raise ValueError('Doppelte Bewertung: ' + str(key))
        seen.add(key)
        if row['rating_id'] not in valid_ids or row['rater'] not in ('R1', 'R2'):
            raise ValueError('Unbekannte Bewertungs-ID oder Rater: ' + str(key))
        values = [row.get(k) for k in CAPS]
        if all(v is None for v in values) and row.get('severe_errors') is None:
            continue
        if any(type(row.get(k)) not in (int, float) or not 0 <= row[k] <= cap for k, cap in CAPS.items()):
            raise ValueError('Unvollständige/ungültige Bewertung: ' + str(key))
        errors = row.get('severe_errors')
        if type(errors) is not int or errors < 0:
            raise ValueError('Fehlerzahl muss eine nichtnegative ganze Zahl sein.')
        grades.setdefault(row['rating_id'], []).append({
            'total':sum(values), 'plan':sum(row[k] for k in ('dependencies','resources','milestones')),
            'risk':sum(row[k] for k in ('risk_identification','prioritization','measures')), 'errors':errors})
    pairs, quality, incomplete, disagreements = [], [], [], []
    observations, timeouts, ai_failures = [], 0, 0
    for rid, entries in grades.items():
        if len(entries) == 2:
            disagreements.append({'rating_id':rid, 'absolute_total_gap':abs(entries[0]['total'] - entries[1]['total'])})
    for s in records:
        by_mode = {r['condition']:r for r in s['rounds']}
        for position, r in enumerate(s['rounds'], 1):
            timeouts += r['status'] == 'timed_out'
            ai_failures += sum(c['status'] != 'completed' for c in r['ai_calls'])
            observations.append({'participant':s['participant'], 'group':s['group'], 'position':position,
                'case_id':r['case_id'], 'condition':r['condition'], 'status':r['status'],
                'seconds':r['ended_at'] - r['started_at'] if r['ended_at'] is not None else None})
        if set(by_mode) != {'manual','ai'} or any(r['status'] != 'submitted' for r in by_mode.values()):
            incomplete.append(s['participant'])
        else:
            elapsed = {k:r['ended_at'] - r['started_at'] for k,r in by_mode.items()}
            pairs.append({'participant':s['participant'], 'group':s['group'],
                'manual_seconds':elapsed['manual'], 'ai_seconds':elapsed['ai'],
                'time_delta_ai_minus_manual':elapsed['ai'] - elapsed['manual']})
        means = {}
        for mode, r in by_mode.items():
            entries = grades.get(r['rating_id'], [])
            if len(entries) == 2:
                means[mode] = {k:statistics.mean(g[k] for g in entries) for k in ('total','plan','risk','errors')}
        if set(means) == {'manual', 'ai'}:
            quality.append({'participant':s['participant'], 'group':s['group'],
                'includes_timeout':any(r['status']=='timed_out' for r in s['rounds']),
                'manual':means['manual'], 'ai':means['ai'],
                'delta_ai_minus_manual':{k:means['ai'][k]-means['manual'][k] for k in means['ai']}})
    return {'participants':len(records), 'complete_pairs':len(pairs), 'pairs':pairs,
            'median_time_delta': statistics.median(p['time_delta_ai_minus_manual'] for p in pairs) if pairs else None,
            'timeouts':timeouts, 'ai_failed_or_unfinished_calls':ai_failures,
            'incomplete_participants':incomplete, 'quality_pairs':quality, 'rater_disagreements':disagreements,
            'observations':observations,
            'interpretation':'Deskriptiv, keine Signifikanz- oder Kausalaussage. Zeitvergleich nur für vollständig abgegebene Paare; Ausfälle separat berichten. Qualität benötigt zwei vollständige unabhängige Bewertungen.'}
