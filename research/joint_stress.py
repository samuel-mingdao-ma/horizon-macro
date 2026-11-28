"""Reprice the frozen expansion forecast and its yield-confirmed pace alarm together."""

from collections import deque
from itertools import product
from math import exp, isclose, isfinite, log, log1p

from curve_stability import CASES, SPEC as PARENT, _lead, evaluate_cell
from forecast_ledger import month_offset
from joint_calendar import build_calendar_paths
from pace_trial import FLOOR, THRESHOLD, decisions

RADII = (0, 3, 5)
UNIT = 10**12
SPEC = dict(
    id='expansion-onset-joint-yield-stress-v1',
    parentId=PARENT['id'],
    radiiBp=list(RADII),
    bandBp=5,
    ratio=2,
    threshold=THRESHOLD,
    floor=FLOOR,
    method='Independently shock both monthly yield levels anywhere inside each radius at four consecutive feature dates. Use the same perturbed path for the forecast, pace, three-month yield changes and 5 bp / 2:1 confirmation.',
    scope='Freeze the as-issued expansion-model coefficients, historical prior and other predictors. Each issue reprices all four dates with its own fit. The two-month release lag and common mature expansion cohorts are unchanged.',
    precision='Use the original 12-decimal probability comparisons and inclusive 5 bp band. The middle path score is required for completeness. Only the first, third and last scores enter the pace rule.',
    interpretation='Probability-score endpoints allow a different perturbation per scored month. The persistent flattener and steepener apply the same opposite shocks to both rates throughout history. Alarm ranges allow issue-specific paths; the extra alarm compares the overlay and 30% level on exactly the same path. A positive unresolved count identifies conservative outer alarm bounds.',
)


def _log_odds(model, features):
    return float(model['intercept']) + sum(
        (features[name] - float(mean)) * float(coefficient) / float(scale)
        for name, mean, scale, coefficient in zip(
            model['featureOrder'], model['means'], model['scales'], model['coefficients']
        )
    )


def _risk(log_odds, prior):
    raw = 1 / (1 + exp(-log_odds)) if log_odds >= 0 else exp(log_odds) / (1 + exp(log_odds))
    return (raw + prior) / 2


def _bp(value):
    return None if value is None else round(value * UNIT) * 100 / UNIT


def _eligible(short, long):
    return (
        short is not None
        and long is not None
        and short > 0
        and short > long
        and long <= 5
        and long >= -max(5, short / 2)
    )


def _supplement(current, previous, start):
    return (
        current >= round(FLOOR * UNIT)
        and current > previous
        and current > start
        and 2 * current - start >= round(THRESHOLD * UNIT)
    )


class Issue:
    def __init__(self, base, prior, beta, short, long, logits):
        self.base = base
        self.logits = logits
        self.prior = prior
        self.beta = beta
        self.short = short
        self.long = long
        self.cache = {}

    def risk(self, index, spread):
        key = (index, spread)
        if key not in self.cache:
            if self.base[index] is None or spread == 0:
                self.cache[key] = self.base[index]
            else:
                z = self.logits[index] + self.beta * spread / 100
                self.cache[key] = _risk(z, self.prior)
        return self.cache[key]

    def risk_range(self, i, lo, hi):
        if self.base[i] is None:
            return [None, None]
        values = [self.risk(i, lo), self.risk(i, hi)]
        if lo <= 0 <= hi and lo < hi:
            # Published zero can differ from a stored fit by its serialization precision.
            values.extend([self.base[i], _risk(self.logits[i], self.prior)])
        return [min(values), max(values)]

    def point(self, ends, previous):
        s0, l0, st, lt = ends
        return self.full_point([[s0, l0], [0, 0], list(previous), [st, lt]])

    def full_point(self, shocks):
        if len(shocks) != 4 or any(len(pair) != 2 or not all(isfinite(v) for v in pair) for pair in shocks):
            raise ValueError('Joint stress needs four monthly short/long yield shock pairs')
        (s0, l0), _, _, (st, lt) = shocks
        path = [self.risk(i, l - s) for i, (s, l) in enumerate(shocks)]
        flags = decisions(path)
        short = None if self.short is None else self.short + st - s0
        long = None if self.long is None else self.long + lt - l0
        level, quarter = flags['levelAlert'], flags['quarterAlert']
        alert = None if level is None else level or (quarter and _eligible(short, long))
        state = 'level' if level else 'extra' if alert else 'off'
        return state, dict(
            shocksBp=shocks,
            path=path,
            probability=path[-1],
            change1m=flags['change1m'],
            change3m=flags['change3m'],
            shortChangeBp=short,
            longChangeBp=long,
            levelAlert=level,
            quarterAlert=quarter,
            referenceAlert=alert,
        )

    def outer_states(self, ranges, radius):
        """Bounds over a continuous box. Preserve dependencies by checking witnesses and subdividing."""
        (s0, l0, st, lt) = ranges
        pmin, pmax = [round(p * UNIT) for p in self.risk_range(3, lt[0] - st[1], lt[1] - st[0])]
        threshold = round(THRESHOLD * UNIT)
        states = {'level'} if pmax >= threshold else set()
        if pmin >= threshold:
            return states
        if None in self.base or self.short is None or self.long is None:
            return states | {'off'}
        start_lo, start_hi = [round(p * UNIT) for p in self.risk_range(0, l0[0] - s0[1], l0[1] - s0[0])]
        prev_lo, prev_hi = [round(p * UNIT) for p in self.risk_range(2, -2 * radius, 2 * radius)]
        slo, shi = self.short + st[0] - s0[1], self.short + st[1] - s0[0]
        llo, lhi = self.long + lt[0] - l0[1], self.long + lt[1] - l0[0]
        lower = max(llo, -max(5, shi / 2))
        can_qualify = shi > 0 and lower <= min(5, lhi) and lower < shi
        all_qualify = slo > 0 and slo > lhi and lhi <= 5 and llo >= -max(5, slo / 2)
        if can_qualify and _supplement(min(pmax, threshold - 1), prev_lo, start_lo):
            states.add('extra')
        if not (all_qualify and _supplement(pmin, prev_hi, start_hi)):
            states.add('off')
        return states

    def stress(self, h, capture=False):
        risks = [self.risk_range(i, -2 * h, 2 * h) for i in range(4)]

        def change(i):
            if None in self.base[i:] or self.base[3] is None:
                return [None, None]
            return [(round(risks[3][j] * UNIT) - round(risks[i][1 - j] * UNIT)) / UNIT for j in (0, 1)]

        result = dict(probability=risks[3], change1m=change(2), change3m=change(0))
        if self.base[3] is None:
            result.update(level=[None, None], alert=[None, None], extra=[None, None], certified=True)
            if capture:
                result['witnesses'] = dict(on=None, off=None, extra=None, steepener=None)
            return result

        box = [(-h, h)] * 4
        outer = self.outer_states(box, h)
        seen = {}

        def inspect(ends, previous):
            state, point = self.point(ends, previous)
            seen.setdefault(state, point)

        inspect((0, 0, 0, 0), (0, 0))
        if seen.keys() != outer:
            # Try simple, sparse counterexamples first. The other monthly rate levels
            # enter the decision only via the last-month spread, monotonically.
            grid = list(product((0, -h, h), repeat=4))
            grid.sort(key=lambda point: (sum(x != 0 for x in point), sum(abs(x) for x in point)))
            for previous in ((0, 0), (-h, h), (h, -h)):
                for ends in grid:
                    inspect(ends, previous)
                    if seen.keys() == outer:
                        break
                if seen.keys() == outer:
                    break

        unresolved = set()
        for state in outer - seen.keys():
            # Joint constraints can meet in the interior even when the ternary grid
            # misses them. Cover the continuous box; keep inconclusive states as bounds.
            pending = deque([(box, 0)])
            visits = 0
            while pending and state not in seen:
                current, depth = pending.popleft()
                if state not in self.outer_states(current, h):
                    continue
                center = tuple((lo + hi) / 2 for lo, hi in current)
                for previous in ((-h, h), (h, -h)):
                    inspect(center, previous)
                visits += 1
                if state in seen:
                    break
                if visits >= 4096 or depth >= 36:
                    unresolved.add(state)
                    break
                axis = max(range(4), key=lambda i: current[i][1] - current[i][0])
                lo, hi = current[axis]
                for half in ((lo, center[axis]), (center[axis], hi)):
                    part = list(current)
                    part[axis] = half
                    pending.append((part, depth + 1))

        unresolved.difference_update(seen)
        possible = set(seen) | unresolved
        result.update(
            level=[possible == {'level'}, 'level' in possible],
            alert=['off' not in possible, bool(possible & {'extra', 'level'})],
            extra=[possible == {'extra'}, 'extra' in possible],
            certified=not unresolved,
        )
        if capture:
            _, steepener = self.full_point([[-h, h] for _ in self.base])
            result['witnesses'] = dict(
                on=seen.get('extra', seen.get('level')),
                off=seen.get('off'),
                extra=seen.get('extra'),
                steepener=steepener,
            )
        return result


def _issue(origin, pace, legs, model, origins, live=False):
    date_key = 'issueDate' if live else 'date'
    date, refit = origin[date_key], origin['refitDate']
    if (
        any(
            p[date_key] != date
            or p['featureDate'] != origin['featureDate']
            or p['refitDate'] != refit
            or p['probability'] != origin['probability']
            for p in (pace, legs)
        )
        or origin['featureDate'] != month_offset(date, -2)
        or legs['lagFeatureDate'] != month_offset(date, -5)
    ):
        raise ValueError('Joint stress inputs must come from the same forecast and feature dates')
    prior = origin['expansionPriorProbability']
    base = [pace['lag3Probability'], pace['lag2Probability'], pace['lag1Probability'], pace['probability']]
    beta = None
    if any(p is not None for p in base):
        if (
            model is None
            or model['refitDate'] != refit
            or refit > date
            or prior is None
            or not isclose(model['trainingPrevalence'], prior, abs_tol=1e-10, rel_tol=0)
        ):
            raise ValueError('A repriced probability requires its own dated expansion fit and prior')
        idx = model['featureOrder'].index('slope')
        beta = float(model['coefficients'][idx]) / float(model['scales'][idx])
    logits = []
    for index, p in enumerate(base):
        z = None
        if p is not None:
            tick = month_offset(date, index - 3)
            feature_row = origin if index == 3 else origins[tick]
            if feature_row['featureDate'] != month_offset(tick, -2):
                raise ValueError('A path observation has the wrong release lag')
            z = _log_odds(model, feature_row)
            if not isfinite(z) or not isclose(_risk(z, prior), p, abs_tol=1e-9, rel_tol=0):
                raise ValueError('The frozen fit does not reproduce the dated path probability')
        logits.append(z)
    issue = Issue(base, prior, beta, _bp(legs['shortChange']), _bp(legs['longChange']), logits)
    capture = live or date in CASES
    fields = (
        ('forecastStart', 'forecastEnd', 'available', 'reason')
        if live
        else ('commonMature', 'issuePhase', 'target', 'onsetDate')
    )
    row = {
        date_key: date,
        **{k: origin[k] for k in ('featureDate', 'refitDate', 'probability', *fields)},
        **{k: pace[k] for k in ('change1m', 'change3m', 'levelAlert')},
    }
    reference = evaluate_cell(
        legs['shortChange'], legs['longChange'], pace['levelAlert'], pace['quarterAlert'], 5, 2
    )
    row['referenceAlert'] = reference['actual']
    row['radii'] = {str(h): issue.stress(h, capture) for h in RADII}
    zero = row['radii']['0']
    if zero['alert'] != [reference['actual']] * 2 or zero['level'] != [pace['levelAlert']] * 2:
        raise ValueError('Zero-shock alarm differs from the published control')
    return row, issue


def _scores(targets, probs):
    if not targets:
        return [None, None]
    n = len(targets)
    brier = sum((y - p) ** 2 for y, p in zip(targets, probs)) / n
    clipped = [max(1e-12, min(1 - 1e-12, p)) for p in probs]
    loss = -sum(log(p) if y else log1p(-p) for y, p in zip(targets, clipped)) / n
    return brier, loss


def _window(reference, history, issues):
    paired = [
        r
        for r in history
        if r['commonMature'] and reference['windowStart'] <= r['date'] <= reference['windowEnd']
    ]
    quiet = [r for r in paired if r['target'] == 0]
    targets = [r['target'] for r in paired]
    if (
        len(paired) != reference['n']
        or len(quiet) != reference['quietExpansionN']
        or not all(r['issuePhase'] == ('pre-onset' if r['target'] else 'expansion-no-recession') for r in paired)
    ):
        raise ValueError('Stress replay requires the original mature expansion cohort')
    result = {k: reference[k] for k in ('windowStart', 'windowEnd', 'n', 'quietExpansionN', 'preOnsetN')}
    scores = reference['probabilityScores']
    result.update(
        originalQuiet=reference['summary']['level']['quietAlerts'],
        originalBrier=scores['brier'],
        originalLogLoss=scores['logLoss'],
        radii={},
    )
    for h in RADII:
        key = str(h)
        band = [r['radii'][key] for r in paired]
        intervals = [b['probability'] for b in band]
        best_risks = [hi if y else lo for y, (lo, hi) in zip(targets, intervals)]
        worst_risks = [lo if y else hi for y, (lo, hi) in zip(targets, intervals)]
        score_bounds = [_scores(targets, best_risks), _scores(targets, worst_risks)]
        coherent = [
            _scores(targets, [issues[r['date']].risk(3, spread) for r in paired]) for spread in (-2 * h, 2 * h)
        ]
        out = dict(
            brier=[s[0] for s in score_bounds],
            logLoss=[s[1] for s in score_bounds],
            coherentBrier=[s[0] for s in coherent],
            coherentLogLoss=[s[1] for s in coherent],
            unresolvedN=sum(not b['certified'] for b in band),
            episodes=[],
        )
        for method in ('level', 'alert', 'extra'):
            out[method + 'Quiet'] = [sum(r['radii'][key][method][i] for r in quiet) for i in (0, 1)]
        out['extraQuietDates'] = [r['date'] for r in quiet if r['radii'][key]['extra'][1]]
        for episode in reference['episodes']:
            onset = episode['onsetDate']
            rows = [r for r in paired if r['onsetDate'] == onset and r['target'] == 1]
            entry = dict(
                onsetDate=onset,
                coverage=episode['coverage'],
                originalLevelLead=episode['methods']['level']['leadMonths'],
            )
            for method in ('level', 'alert'):
                entry[method + 'Lead'] = [
                    _lead(onset, next((r['date'] for r in rows if r['radii'][key][method][j]), None))
                    for j in (0, 1)
                ]
            out['episodes'].append(entry)
        result['radii'][key] = out
    zero = result['radii']['0']
    if zero['levelQuiet'] != [result['originalQuiet']] * 2 or any(
        not isclose(zero[k][0], scores[k], abs_tol=1e-10, rel_tol=0) for k in ('brier', 'logLoss') if paired
    ):
        raise ValueError('The zero-shock sample or scores do not reproduce the expansion baseline')
    return result


def build_joint_stress_trial(expansion, momentum, curve_legs):
    models = {f['refitDate']: f.get('models', {}).get('candidate') for f in expansion['folds']}
    dates = [r['date'] for r in expansion['history']]
    if dates != sorted(set(dates)) or any(
        [r['date'] for r in parent['history']] != dates for parent in (momentum, curve_legs)
    ):
        raise ValueError('Stress replay requires identical calendar origins across all three inputs')
    origins = {row['date']: row for row in expansion['history']}
    rows, issues, cases = [], {}, {}
    for origin, pace, legs in zip(expansion['history'], momentum['history'], curve_legs['history']):
        row, issue = _issue(origin, pace, legs, models[origin['refitDate']], origins)
        date = row['date']
        issues[date] = issue
        if date in CASES:
            cases[date] = row
            row = {
                **row,
                'radii': {k: {f: v for f, v in b.items() if f != 'witnesses'} for k, b in row['radii'].items()},
            }
        rows.append(row)
    latest, _ = _issue(
        expansion['latest'],
        momentum['latest'],
        curve_legs['latest'],
        expansion['currentModel'],
        origins,
        live=True,
    )
    windows = {k: _window(curve_legs['windows'][k], rows, issues) for k in ('all', 'rolling120')}
    return dict(
        spec=SPEC,
        latest=latest,
        windows=windows,
        cases=cases,
        history=rows,
        calendarPaths=build_calendar_paths(rows, issues, windows),
    )


def joint_stress_csv_rows(trial):
    for row in trial['history']:
        for radius, band in row['radii'].items():
            flat = {k: v for k, v in row.items() if k != 'radii'}
            flat['radiusBp'] = int(radius)
            for k in ('probability', 'change1m', 'change3m', 'level', 'alert', 'extra'):
                suffixes = (
                    ('Min', 'Max') if k in ('probability', 'change1m', 'change3m') else ('Guaranteed', 'Possible')
                )
                flat.update({k + suffix: v for suffix, v in zip(suffixes, band[k])})
            yield {**flat, 'certified': band['certified']}
