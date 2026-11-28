"""Anonymous rating packets and descriptive paired analysis; no invented observations."""
import statistics

CAPS = {'dependencies': 20, 'resources': 15, 'milestones': 15,
        'risk_identification': 20, 'prioritization': 15, 'measures': 15}
QUALITY_KEYS = ('total', 'plan', 'risk', 'errors')


def _started(session):
    """Whether a participant actually started (not merely an unused invitation)."""
    return session.get('consent_at') is not None or any(
        r.get('status') != 'ready' for r in session.get('rounds', [])
    )


def _stats(values):
    if not values:
        return None
    return {'n': len(values), 'median': statistics.median(values), 'min': min(values), 'max': max(values)}


def _quality_delta_stats(quality_pairs):
    if not quality_pairs:
        return None
    return {k: _stats([q['delta_ai_minus_manual'][k] for q in quality_pairs]) for k in QUALITY_KEYS}


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


def summarize(records, ratings=None, include_pilots=False):
    selected = [s for s in records if include_pilots or not s['pilot']]
    not_started = [s['participant'] for s in selected if not _started(s)]
    started = [s for s in selected if _started(s)]
    seen, grades = set(), {}
    valid_ids = {r['rating_id'] for s in started for r in s['rounds']
                 if r['status'] in ('submitted', 'timed_out')}
    for row in ratings or []:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get('rating_id'), str)
            or not isinstance(row.get('rater'), str)
        ):
            raise ValueError('Ungültige Bewertungszeile: rating_id und rater erforderlich.')
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
            'rater': row['rater'],
            'total': sum(values), 'plan': sum(row[k] for k in ('dependencies', 'resources', 'milestones')),
            'risk': sum(row[k] for k in ('risk_identification', 'prioritization', 'measures')), 'errors': errors,
            **{k: row[k] for k in CAPS}})
    pairs, quality, incomplete, disagreements, single_rater = [], [], [], [], []
    observations, timeouts, ai_failures = [], 0, 0
    round_means = {}
    for rid, entries in sorted(grades.items()):
        if len(entries) == 2:
            disagreements.append({'rating_id': rid, 'absolute_total_gap': abs(entries[0]['total'] - entries[1]['total'])})
            round_means[rid] = {k: statistics.mean(g[k] for g in entries) for k in (*QUALITY_KEYS, *CAPS)}
        elif len(entries) == 1:
            present = entries[0]['rater']
            single_rater.append({'rating_id': rid, 'rater': present, 'missing_rater': 'R2' if present == 'R1' else 'R1'})
    warnings = []
    if single_rater:
        raters_present = ', '.join(sorted({item['rater'] for item in single_rater}))
        warnings.append(
            f'{len(single_rater)} Antwort(en) haben nur eine Bewertung ({raters_present}); '
            'für quality_pairs und rater_disagreements sind beide Rater (R1 und R2) nötig.'
        )
    elif ratings is not None and valid_ids and not grades:
        warnings.append('Bewertungsdatei(en) enthalten keine ausgefüllten Bewertungen (0 Qualitätspaare).')

    cases = {}
    exp_groups = {'pm': {}, 'ai': {}}
    for s in started:
        exp = s.get('experience') or {}
        by_mode = {r['condition']: r for r in s['rounds']}
        for position, r in enumerate(s['rounds'], 1):
            timeouts += r['status'] == 'timed_out'
            ai_failures += sum(c['status'] != 'completed' for c in r['ai_calls'])
            elapsed_round = (
                r['ended_at'] - r['started_at']
                if r['ended_at'] is not None and r['started_at'] is not None
                else None
            )
            observations.append({'participant': s['participant'], 'group': s['group'], 'position': position,
                'case_id': r['case_id'], 'condition': r['condition'], 'status': r['status'],
                'seconds': elapsed_round})
            bucket = cases.setdefault(r['case_id'], {'submitted_rounds': 0, 'timeouts': 0, 'seconds': [], 'rated': []})
            if r['status'] == 'submitted':
                bucket['submitted_rounds'] += 1
                if elapsed_round is not None:
                    bucket['seconds'].append(elapsed_round)
            elif r['status'] == 'timed_out':
                bucket['timeouts'] += 1
            if r['rating_id'] in round_means:
                bucket['rated'].append(round_means[r['rating_id']])
        pair = None
        if set(by_mode) != {'manual', 'ai'} or any(r['status'] != 'submitted' for r in by_mode.values()):
            incomplete.append(s['participant'])
        else:
            elapsed = {k: r['ended_at'] - r['started_at'] for k, r in by_mode.items()}
            pair = {'participant': s['participant'], 'group': s['group'],
                'manual_seconds': elapsed['manual'], 'ai_seconds': elapsed['ai'],
                'time_delta_ai_minus_manual': elapsed['ai'] - elapsed['manual']}
            pairs.append(pair)
        means = {mode: round_means[r['rating_id']] for mode, r in by_mode.items() if r['rating_id'] in round_means}
        qpair = None
        if set(means) == {'manual', 'ai'}:
            qpair = {'participant': s['participant'], 'group': s['group'],
                'includes_timeout': any(r['status'] == 'timed_out' for r in s['rounds']),
                'manual': means['manual'], 'ai': means['ai'],
                'delta_ai_minus_manual': {k: means['ai'][k] - means['manual'][k] for k in means['ai']}}
            quality.append(qpair)
        for dim in ('pm', 'ai'):
            level = exp.get(dim)
            if level:
                slot = exp_groups[dim].setdefault(level, {'participants': 0, 'pairs': [], 'quality': []})
                slot['participants'] += 1
                if pair is not None:
                    slot['pairs'].append(pair)
                if qpair is not None:
                    slot['quality'].append(qpair)

    by_case = {
        case_id: {
            'submitted_rounds': data['submitted_rounds'],
            'timeouts': data['timeouts'],
            'seconds': _stats(data['seconds']),
            'rated_rounds': len(data['rated']),
            **{k: _stats([m[k] for m in data['rated']]) for k in QUALITY_KEYS},
        }
        for case_id, data in sorted(cases.items())
    }
    by_experience = {
        dim: {
            level: {
                'participants': slot['participants'],
                'complete_pairs': len(slot['pairs']),
                'time_delta_stats': _stats([p['time_delta_ai_minus_manual'] for p in slot['pairs']]),
                'quality_pairs': len(slot['quality']),
                'quality_delta_stats': _quality_delta_stats(slot['quality']),
            }
            for level, slot in sorted(levels.items())
        }
        for dim, levels in exp_groups.items()
    }
    # No dated snapshot (study rule of 21.11.2026): name every model that answered.
    models = sorted({c['model_returned'] for s in started for r in s['rounds'] for c in r['ai_calls']
                     if c['status'] == 'completed' and c.get('model_returned')})
    time_deltas = [p['time_delta_ai_minus_manual'] for p in pairs]
    return {'includes_pilots': bool(include_pilots),
            'invited': len(selected), 'participants': len(started),
            'not_started_participants': not_started,
            'complete_pairs': len(pairs), 'pairs': pairs,
            'models_returned': models, 'model_varies': len(models) > 1,
            'median_time_delta': statistics.median(time_deltas) if time_deltas else None,
            'time_delta_stats': _stats(time_deltas),
            'timeouts': timeouts, 'ai_failed_or_unfinished_calls': ai_failures,
            'incomplete_participants': incomplete, 'quality_pairs': quality,
            'quality_delta_stats': _quality_delta_stats(quality),
            'rater_disagreements': disagreements,
            'single_rater_ratings': single_rater,
            'warnings': warnings,
            'by_case': by_case, 'by_experience': by_experience,
            'observations': observations,
            'interpretation': 'Deskriptiv, keine Signifikanz- oder Kausalaussage. Zeitvergleich nur für vollständig abgegebene Paare; Ausfälle separat berichten. Qualität benötigt zwei vollständige unabhängige Bewertungen.'}
