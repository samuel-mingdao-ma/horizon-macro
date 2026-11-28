"""Decompose three-month yield-curve movements and test fixed confirmations of the pace alert."""

from math import isclose

from confirmation_trial import CASE_DATES, OUTCOME_FIELDS, case_attribution
from forecast_ledger import month_offset
from leading_trial import month_frame, number
from pace_trial import CASE_DATE, CASE_ONSET, SPEC as PACE_SPEC
from weight_warning import warning_windows


PRE_REPLAY = ('shortLead', 'bear', 'sustained')
RULES = (*PRE_REPLAY, 'mixedTwoToOne')
ALERTS = {method: method + 'Alert' for method in ('level', 'quarter', *RULES)}
UNIT = 10**12
SPEC = dict(
    id='expansion-onset-yield-curve-legs-v1', parentId=PACE_SPEC['id'],
    threshold=PACE_SPEC['warningThreshold'], featureLagMonths=2, lookbackMonths=3,
    shortSeries='TB3MS', longSeries='GS10', preReplayRules=list(PRE_REPLAY), postHocRules=['mixedTwoToOne'],
    decomposition='Flatness change equals the rise in the three-month bill yield minus the rise in the ten-year yield. Positive values mean flattening. Preserve negative offsetting legs.',
    shortLead='Net flattening with a positive bill rise that strictly exceeds the negative of the ten-year yield change.',
    bear='Short-led flattening with the ten-year yield flat or rising.',
    sustained='Short-led flattening with a strictly rising bill yield in each of the three consecutive monthly steps.',
    mixedTwoToOne='Post-hoc shadow rule. Require positive flattening, a rising bill, a flat or falling ten-year yield, and a bill rise at least twice the size of the long-yield fall. Equality qualifies.',
    design='The first three rules were fixed before this replay. The fourth was specified after reviewing the known cases and extra quiet months. Its historical fit can be evaluated but prospective validation starts at first capture.',
    scope='Apply these rules only to the extra three-month pace warning below 30%. Keep every level warning and use the same conditional probability.',
    clock='Use four exact monthly average observations. The last observation precedes the issue month by two months.',
    precision='Round observed yields to twelve decimal places and compare changes in integer units. A tie does not qualify as short-led.',
    missing='The first two filters require both yield endpoints. The sustained filter also requires the two intervening bill observations. Missing required data block only supplemental alerts.',
    test='Require the May 2000 warning, at least eleven months of lead and an advance over the level alarm for 2001, preserved complete detections and no additional quiet alerts in either sample.',
)


def _units(y):
    value = number(y)
    return round(value * UNIT) if value is not None else None


def _amount(units):
    return units / UNIT if units is not None else None


def _change(start, end):
    return None if start is None or end is None else end - start


def leg_evidence(path):
    """Use exact calendar endpoints; preserve each rate's change when only the other is missing."""
    if len(path) != 4 or not path[-1]['date'].endswith('-01') or any(
        point['date'] != month_offset(path[-1]['date'], i - 3) for i, point in enumerate(path)
    ):
        raise ValueError('Curve legs require four consecutive observation months in chronological order')
    short = [_units(p['shortYield']) for p in path]
    long = [_units(p['longYield']) for p in path]
    s, l = _change(short[0], short[-1]), _change(long[0], long[-1])
    f = _change(l, s)
    rise_count = None if None in short else sum(b > a for a, b in zip(short, short[1:]))
    if f is None:
        driver = pattern = 'unavailable'
    elif f <= 0:
        driver = pattern = 'no-flattening'
    else:
        driver = 'short-led' if s > -l else 'long-led' if s < -l else 'equal'
        if l > 0:
            pattern = 'long-rise-offset'
        elif s < 0:
            pattern = 'short-fall-offset'
        elif l == 0:
            pattern = 'short-only'
        elif s == 0:
            pattern = 'long-only'
        else:
            pattern = 'both-flatten'
    short_led = None if f is None else f > 0 and s > 0 and s > -l
    return dict(
        shortStart=_amount(short[0]), shortStep1=_amount(short[1]), shortStep2=_amount(short[2]), shortEnd=_amount(short[3]),
        longStart=_amount(long[0]), longStep1=_amount(long[1]), longStep2=_amount(long[2]), longEnd=_amount(long[3]),
        shortChange=_amount(s), longChange=_amount(l), flattening=_amount(f),
        startSlope=_amount(_change(short[0], long[0])), endSlope=_amount(_change(short[-1], long[-1])),
        driver=driver, pattern=pattern, shortRiseCount=rise_count, shortLead=short_led,
        bear=None if short_led is None else short_led and l >= 0,
        sustained=None if short_led is None or rise_count is None else short_led and rise_count == 3,
        mixedTwoToOne=None if f is None else f > 0 and s > 0 and l <= 0 and s >= -2 * l,
    )


def leg_decisions(level, quarter, evidence):
    if not (level is None and quarter is None or type(level) is bool and type(quarter) is bool and (not level or quarter)):
        raise ValueError('Inconsistent level and pace alarms')
    return {ALERTS[k]: None if level is None else level or (quarter and evidence[k] is True) for k in RULES}


def _yield_series(raw, key):
    frame = month_frame(raw[key].to_frame(name=key), key)
    return {d.strftime('%Y-%m-%d'): _amount(_units(v)) for d, v in frame[key].items()}


def _issue(origin, pace, origins, series, *, live=False):
    key = 'issueDate' if live else 'date'
    issue = pace[key]
    if (origin[key] != issue or origin['featureDate'] != month_offset(issue, -2)
            or origin['featureDate'] != pace['featureDate'] or origin['refitDate'] != pace['refitDate']
            or origin['probability'] != pace['probability'] or (pace['probability'] is None) != (pace['levelAlert'] is None)):
        raise ValueError('Curve legs require the original same-issue conditional probability and input dates')
    path = []
    for lag in range(-3, 1):
        prior_issue = month_offset(issue, lag)
        date = month_offset(prior_issue, -2)
        short, long = series['TB3MS'].get(date), series['GS10'].get(date)
        published = origins.get(prior_issue) if lag else origin
        if published:
            if published['featureDate'] != date:
                raise ValueError('Mismatched observation month for the published slope')
            slope = number(published['slope'])
            if None not in (slope, short, long) and not isclose(long - short, slope, abs_tol=1e-9, rel_tol=0):
                raise ValueError('Dated yields disagree with the published slope')
        path.append(dict(date=date, shortYield=short, longYield=long))
    evidence = leg_evidence(path)
    fields = ('refitDate','featureDate','probability','change1m','change3m','levelAlert','quarterAlert')
    result = {key: issue, **{k: pace[k] for k in fields}, 'lagFeatureDate': path[0]['date'],
              **evidence, **leg_decisions(pace['levelAlert'], pace['quarterAlert'], evidence)}
    extras = ('forecastStart','forecastEnd','available','reason') if live else OUTCOME_FIELDS
    if any(origin[k] != pace[k] for k in extras):
        raise ValueError('Curve-leg replay has different issue coverage or outcomes')
    result.update({k: pace[k] for k in extras})
    if live:
        result['yieldPath'] = path
    return result


def _gates(windows, may):
    episode = next((e for e in windows['all']['episodes'] if e['onsetDate'] == CASE_ONSET and e['coverage'] == 'full'), None)
    paired = bool(episode and may and may['commonMature'] and may['target'] == 1 and may['onsetDate'] == CASE_ONSET
                  and may['quarterAlert'] and not may['levelAlert'])
    gates = {}
    for k in RULES:
        full, recent = [windows[w][k + 'Comparison'] for w in ('all', 'rolling120')]
        lead = (episode['methods'][k]['leadMonths'] or 0) if episode else 0
        retained = bool(paired and may[ALERTS[k]] and lead >= 11 and lead > (episode['methods']['level']['leadMonths'] or 0))
        hits = full['maintainedHits'] and recent['maintainedHits']
        gates[k] = dict(mayRetained=retained, allNoAddedFalse=full['noMoreFalseAlarms'],
                        rolling120NoAddedFalse=recent['noMoreFalseAlarms'], maintainedHitsBoth=hits,
                        passed=bool(retained and full['sufficient'] and recent['sufficient'] and hits
                                    and full['noMoreFalseAlarms'] and recent['noMoreFalseAlarms']))
    return gates


def _case_effects(legs, origins, paces, folds):
    models = {f['refitDate']: f.get('models', {}).get('candidate') for f in folds}
    effects = dict.fromkeys(CASE_DATES)
    for date in CASE_DATES:
        row = legs.get(date)
        if row is None or row['flattening'] is None or row['flattening'] <= 0:
            continue
        fit = models.get(row['refitDate'])
        case = case_attribution(origins.get(month_offset(date, -3)), origins[date], paces[date], fit)
        if case:
            curve = case['effects']['slope']
            effects[date] = dict(curveEffect=curve, shortEffect=curve * row['shortChange'] / row['flattening'],
                                 longEffect=-curve * row['longChange'] / row['flattening'])
    return effects


def build_curve_legs_trial(expansion, momentum, raw):
    origins = {r['date']: r for r in expansion['history']}
    paces = {r['date']: r for r in momentum['history']}
    dates = list(origins)
    if (len(origins) != len(expansion['history']) or len(paces) != len(momentum['history'])
            or dates != list(paces) or dates != sorted(dates)):
        raise ValueError('Curve legs require the same ordered issue months as the expansion and pace trials')
    series = {k: _yield_series(raw, k) for k in ('TB3MS', 'GS10')}
    history = [_issue(origins[d], paces[d], origins, series) for d in dates]
    latest = _issue(expansion['latest'], momentum['latest'], origins, series, live=True)
    windows = warning_windows(
        {'metrics': expansion['metrics'], 'history': history}, raw['USREC'], ALERTS,
        {k + 'Comparison': ('level', k) for k in RULES},
    )
    for key, w in windows.items():
        if w['n'] != w['quietExpansionN'] + w['preOnsetN']:
            raise ValueError('Curve-leg comparisons require mature expansion-origin forecasts')
        w['probabilityScores'] = dict(expansion['metrics'][key]['models']['candidate'])
        paired = [r for r in history if r['commonMature'] and w['windowStart'] <= r['date'] <= w['windowEnd']]
        w['changes'] = {}
        for method in ('quarter', *RULES):
            added = [r for r in paired if r[ALERTS[method]] and not r['levelAlert']]
            w['changes'][method] = dict(quietDates=[r['date'] for r in added if r['target'] == 0],
                                        preOnsetDates=[r['date'] for r in added if r['target'] == 1])
    legs = {r['date']: r for r in history}
    return dict(spec=SPEC, latest=latest, history=history, windows=windows, gate=_gates(windows, legs.get(CASE_DATE)),
                caseEffects=_case_effects(legs, origins, paces, expansion['folds']))
