"""Sample paired historical Treasury perturbations and score entire counterfactual calendars."""

from contextlib import contextmanager
import csv
from dataclasses import dataclass
from math import isclose, sqrt
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from forecast_ledger import month_offset
from joint_stress import SPEC as JOINT_SPEC, UNIT, _issue
from path_calibration import draw_shocks

SEED = 5342001
DRAWS = 20_000
BLOCK = 6
MAY = '2000-05-01'
FEB = '2019-02-01'
ONSET = '2001-04-01'
PERIODS = ('all', 'rolling120')
VARIANTS = (
    ('empirical', 'Historical blocks', None, BLOCK),
    ('cap3', 'Capped at ±3 bp', 3, BLOCK),
    ('cap5', 'Capped at ±5 bp', 5, BLOCK),
    ('iid', 'Independent months', None, 1),
)
SPEC = dict(
    id='expansion-onset-empirical-paths-v1',
    parentId=JOINT_SPEC['id'],
    primary='empirical',
    seed=SEED,
    draws=DRAWS,
    blockMonths=BLOCK,
    bandBp=5,
    ratio=2,
    threshold=0.3,
    onsetDate=ONSET,
    mayDate=MAY,
    febDate=FEB,
    comparison='Hold fitted coefficients, other inputs and prior fixed at each issue. Reuse each copied pair of rates in every forecast that references that observation month.',
    lead='Require the May 2000 warning, at least 11 months of lead, and at least one more month than the 30% alarm on the same path.',
    scores='Compare Brier in both mature expansion cohorts against their unchanged-yield scores. A separate stricter joint test also requires nonincreasing log loss in both cohorts.',
    quiet='In each window, require no more quiet alert months than both the observed 30% alarm and the 30% alarm on the same path. Also report the joint result with either comparator alone.',
    intervals='95% Wilson intervals measure finite simulation uncertainty with the historical donor series and block specification held fixed.',
)
CSV_FIELDS = (
    'date',
    'scenario',
    'draw',
    'lead2001',
    'levelLead2001',
    'mayAlert',
    'febAlert',
    'mayExtra',
    'febExtra',
    'allBrierDelta',
    'recentBrierDelta',
    'allLogLossDelta',
    'recentLogLossDelta',
    'allRuleQuiet',
    'recentRuleQuiet',
    'allLevelQuiet',
    'recentLevelQuiet',
    'lead',
    'brierBoth',
    'logLossBoth',
    'quietMatched',
    'quietObserved',
    'jointMatched',
    'jointObserved',
    'joint',
    'jointStrict',
)


def wilson(passed, n):
    """Two-sided 95% Wilson interval for independent Monte Carlo replications."""
    if not 0 <= passed <= n or n < 1:
        raise ValueError('Simulation counts must lie between zero and a positive draw count')
    z = 1.959963984540054
    fraction = passed / n
    denom = 1 + z * z / n
    center = (fraction + z * z / (2 * n)) / denom
    half = z * sqrt(fraction * (1 - fraction) / n + z * z / (4 * n * n)) / denom
    return dict(
        passed=int(passed),
        n=int(n),
        rate=fraction,
        interval=[0 if passed == 0 else max(0, center - half), 1 if passed == n else min(1, center + half)],
    )


def _quantiles(values):
    # Observed order statistics keep counts integral and tie quantiles to actual draws.
    return [float(x) for x in np.quantile(values, [0.05, 0.5, 0.95], method='nearest')]


def _months(start, end):
    dates = []
    while start <= end:
        dates.append(start)
        start = month_offset(start, 1)
    return dates


def _lead_months(date):
    return 12 * (int(ONSET[:4]) - int(date[:4])) + int(ONSET[5:7]) - int(date[5:7])


@dataclass
class ReplayIssue:
    date: str
    model: object
    positions: np.ndarray
    target: int | None
    periods: tuple
    onset_lead: int


def _prepare(expansion, momentum, legs):
    origins = {r['date']: r for r in expansion['history']}
    dates = list(origins)
    if (
        dates != sorted(dates)
        or len(dates) != len(expansion['history'])
        or any(dates != [r['date'] for r in p['history']] for p in (momentum, legs))
    ):
        raise ValueError('Treasury path simulation requires identical ordered forecast issues')
    live = expansion['latest']
    calendar = _months(
        month_offset(dates[0], -5), max(expansion['history'][-1]['featureDate'], live['featureDate'])
    )
    by_month = {d: i for i, d in enumerate(calendar)}
    models = {f['refitDate']: f.get('models', {}).get('candidate') for f in expansion['folds']}
    baseline = {
        k: dict(
            n=w['n'],
            quietN=w['quietExpansionN'],
            windowStart=w['windowStart'],
            windowEnd=w['windowEnd'],
            brier=w['probabilityScores']['brier'],
            logLoss=w['probabilityScores']['logLoss'],
            quietAlerts=w['summary']['level']['quietAlerts'],
        )
        for k, w in legs['windows'].items()
        if k in PERIODS
    }
    if any(not baseline[k]['n'] for k in PERIODS):
        raise ValueError('Both mature expansion cohorts are required')
    issues = []
    observed_leads = {'levelLead2001': 0, 'ruleLead2001': 0}
    seen = {k: [] for k in PERIODS}
    for origin, pace, curve in zip(expansion['history'], momentum['history'], legs['history']):
        date = origin['date']
        periods = tuple(
            k
            for k, w in baseline.items()
            if origin['commonMature'] and w['windowStart'] <= date <= w['windowEnd']
        )
        if not periods and date not in (MAY, FEB):
            continue
        r, model = _issue(origin, pace, curve, models[origin['refitDate']], origins)
        if date in (MAY, FEB) and (
            'all' not in periods
            or (date == MAY and (origin['target'] != 1 or origin['onsetDate'] != ONSET))
            or (date == FEB and origin['target'] != 0)
        ):
            raise ValueError(
                'Named cases require a mature May 2000 pre-onset issue and a quiet February 2019 issue'
            )
        y = int(origin['target']) if periods else None
        if y not in (0, 1) or r['probability'] is None:
            raise ValueError(
                'A scored expansion month needs a mature binary outcome and an observed probability'
            )
        for name in periods:
            seen[name].append((y, model.base[-1], r['levelAlert']))
        lead = _lead_months(date) if 'all' in periods and origin['onsetDate'] == ONSET and y == 1 else 0
        if lead:
            for key, flag in [('levelLead2001', r['levelAlert']), ('ruleLead2001', r['referenceAlert'])]:
                if flag:
                    observed_leads[key] = max(observed_leads[key], lead)
        pos = [by_month[month_offset(date, offset)] for offset in (-5, -4, -3, -2)]
        issues.append(ReplayIssue(date, model, np.array(pos), y, periods, lead))
    if not {MAY, FEB} <= {issue.date for issue in issues}:
        raise ValueError('Both named case issues must exist in the historical replay')
    for name in PERIODS:
        w = baseline[name]
        score_rows = seen[name]
        observed = sum((p - y) ** 2 for y, p, _ in score_rows) / len(score_rows)
        if (
            len(score_rows) != w['n']
            or sum(y == 0 for y, _, _ in score_rows) != w['quietN']
            or sum(y == 0 and a for y, _, a in score_rows) != w['quietAlerts']
            or not isclose(observed, w['brier'], rel_tol=0, abs_tol=1e-10)
        ):
            raise ValueError('Observed path does not reproduce the published expansion cohort')
    baseline.update({key: value or None for key, value in observed_leads.items()})
    _, model = _issue(live, momentum['latest'], legs['latest'], expansion['currentModel'], origins, live=True)
    pos = [by_month[month_offset(live['issueDate'], lag)] for lag in (-5, -4, -3, -2)]
    return calendar, issues, ReplayIssue(live['issueDate'], model, np.array(pos), None, (), 0), baseline


def _price(model, index, move):
    """Reprice each draw at its own shock, preserving the exact published control at zero."""
    z = model.logits[index] + model.beta * move / 100
    signal = 1 / (1 + np.exp(-np.clip(z, -700, 700)))
    return np.where(move == 0, model.base[index], (signal + model.prior) / 2)


def _evaluate(issue, shocks, need_change=False):
    """A draw's probabilities and both decisions share all four Treasury observations."""
    model = issue.model
    ends = shocks[issue.positions[-1]]
    start = shocks[issue.positions[0]]
    previous = shocks[issue.positions[2]]
    if model.base[-1] is None:
        return None
    current = _price(model, 3, ends[:, 1] - ends[:, 0])
    units = np.rint(current * UNIT)
    level = units >= 0.3 * UNIT
    if None in model.base:
        return current, level, level, None
    start_units = np.rint(_price(model, 0, start[:, 1] - start[:, 0]) * UNIT)
    change = (units - start_units) / UNIT if need_change else None
    if model.short is None or model.long is None:
        return current, level, level, change
    prev_units = np.rint(_price(model, 2, previous[:, 1] - previous[:, 0]) * UNIT)
    pace = (
        (units >= 0.2 * UNIT)
        & (units > prev_units)
        & (units > start_units)
        & (2 * units - start_units >= 0.3 * UNIT)
    )
    # 1e-12 percentage-point precision = 1e-10 bp. Use integer-valued units before
    # the inclusive band / ratio comparison, including on fractional donor boundaries.
    bp_units = UNIT / 100
    short = np.rint((model.short + ends[:, 0] - start[:, 0]) * bp_units)
    long = np.rint((model.long + ends[:, 1] - start[:, 1]) * bp_units)
    passes = (
        (short > 0) & (short > long) & (long <= 5 * bp_units) & ((long >= -5 * bp_units) | (short >= -2 * long))
    )
    return current, level, level | (pace & passes), change


def _collect(issues, shocks, baseline):
    n = shocks.shape[1]
    stats = {
        k: dict(
            brierDelta=np.zeros(n),
            logLossDelta=np.zeros(n),
            ruleQuiet=np.zeros(n, dtype=int),
            levelQuiet=np.zeros(n, dtype=int),
        )
        for k in PERIODS
    }
    timing = dict(lead2001=np.zeros(n, dtype=int), levelLead2001=np.zeros(n, dtype=int))
    for issue in issues:
        p, level, alert, _ = _evaluate(issue, shocks)
        if issue.date in (MAY, FEB):
            prefix = 'may' if issue.date == MAY else 'feb'
            timing[prefix + 'Alert'] = alert
            timing[prefix + 'Extra'] = alert & ~level
        if issue.onset_lead:
            for field, flag in [('lead2001', alert), ('levelLead2001', level)]:
                timing[field] = np.maximum(timing[field], np.where(flag, issue.onset_lead, 0))
        y = issue.target
        observed = issue.model.base[-1]
        # Score deltas with respect to each issue's published probability. Exact
        # zeros therefore remain ties, even if the parent mean was JSON-rounded.
        delta = p - observed
        db = delta * (p + observed - 2 * y)
        dl = -np.log1p(delta / observed if y else -delta / (1 - observed))
        for name in issue.periods:
            w = stats[name]
            w['brierDelta'] += db
            w['logLossDelta'] += dl
            if y == 0:
                w['levelQuiet'] += level
                w['ruleQuiet'] += alert
    for name, w in stats.items():
        for field in ('brier', 'logLoss'):
            w[field + 'Delta'] /= baseline[name]['n']
            w[field] = baseline[name][field] + w[field + 'Delta']
        w['extraQuiet'] = w['ruleQuiet'] - w['levelQuiet']
    return stats, timing


def _gates(stats, timing, baseline):
    all_, recent = (stats[k] for k in PERIODS)
    gates = {k: timing[k] for k in ('mayAlert', 'febAlert', 'mayExtra', 'febExtra')}
    gates['lead'] = (
        timing['mayAlert'] & (timing['lead2001'] >= 11) & (timing['lead2001'] > timing['levelLead2001'])
    )
    gates['brierAll'] = all_['brierDelta'] <= 0
    gates['brierRecent'] = recent['brierDelta'] <= 0
    gates['brierBoth'] = gates['brierAll'] & gates['brierRecent']
    gates['logLossBoth'] = (all_['logLossDelta'] <= 0) & (recent['logLossDelta'] <= 0)
    observed = [stats[k]['ruleQuiet'] <= baseline[k]['quietAlerts'] for k in PERIODS]
    matched = [stats[k]['ruleQuiet'] <= stats[k]['levelQuiet'] for k in PERIODS]
    gates['quietAll'] = observed[0] & matched[0]
    gates['quietRecent'] = observed[1] & matched[1]
    gates['quietMatched'] = matched[0] & matched[1]
    gates['quietObserved'] = observed[0] & observed[1]
    gates['quietBoth'] = gates['quietObserved'] & gates['quietMatched']
    early_and_accurate = gates['lead'] & gates['brierBoth']
    gates['jointMatched'] = early_and_accurate & gates['quietMatched']
    gates['jointObserved'] = early_and_accurate & gates['quietObserved']
    gates['joint'] = early_and_accurate & gates['quietBoth']
    gates['jointStrict'] = gates['joint'] & gates['logLossBoth']
    return gates


def _examples(issues, shocks, gate, stats, timing, calendar):
    examples = []
    for passed in (True, False):
        found = np.flatnonzero(gate == passed)
        if not len(found):
            continue
        i = int(found[0])
        out = dict(
            draw=i + 1,
            passed=passed,
            **{k: (int(a[i]) or None) for k, a in timing.items() if k.endswith('2001')},
            **{k: bool(timing[k][i]) for k in ('mayAlert', 'febAlert', 'mayExtra', 'febExtra')},
        )
        for name in PERIODS:
            w = stats[name]
            out[name] = {
                k: (int(w[k][i]) if k.endswith('Quiet') else float(w[k][i]))
                for k in ('brier', 'logLoss', 'ruleQuiet', 'levelQuiet')
            }
        for case, key in [(MAY, 'mayPath'), (FEB, 'febPath')]:
            row = next(r for r in issues if r.date == case)
            out[key] = [
                dict(date=calendar[j], shortBp=float(shocks[j, i, 0]), longBp=float(shocks[j, i, 1]))
                for j in row.positions
            ]
        examples.append(out)
    return examples


@contextmanager
def _csv_writer(path):
    if path is None:
        yield None
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix='.path-sim-', mode='w', newline='', delete=False) as f:
        tmp = Path(f.name)
        try:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(CSV_FIELDS)
            yield writer
            f.flush()
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    tmp.chmod(0o644)
    tmp.replace(path)


def _write_draws(writer, date, scenario, timing, stats, gates):
    if writer is None:
        return
    all_, recent = (stats[k] for k in PERIODS)
    for i in range(len(gates['joint'])):
        writer.writerow(
            [
                date,
                scenario,
                i + 1,
                int(timing['lead2001'][i]) or '',
                int(timing['levelLead2001'][i]) or '',
                *(int(timing[k][i]) for k in ('mayAlert', 'febAlert', 'mayExtra', 'febExtra')),
                *(format(w[k][i], '.12g') for k in ('brierDelta', 'logLossDelta') for w in (all_, recent)),
                *(int(w[k][i]) for k in ('ruleQuiet', 'levelQuiet') for w in (all_, recent)),
                *(
                    int(gates[k][i])
                    for k in (
                        'lead',
                        'brierBoth',
                        'logLossBoth',
                        'quietMatched',
                        'quietObserved',
                        'jointMatched',
                        'jointObserved',
                        'joint',
                        'jointStrict',
                    )
                ),
            ]
        )


def _scenario(sid, label, cap, block, shocks, calendar, issues, latest, baseline, writer):
    n = shocks.shape[1]
    stats, timing = _collect(issues, shocks, baseline)
    flags = _gates(stats, timing, baseline)
    gates = {k: wilson(int(a.sum()), n) for k, a in flags.items()}
    stages = [('allPaths', n)]
    cumulative = np.ones(n, dtype=bool)
    for key in ('lead', 'brierBoth', 'quietBoth', 'jointStrict'):
        cumulative &= flags[key]
        stages.append((key, int(cumulative.sum())))
    live = _evaluate(latest, shocks, need_change=True)
    now = (
        None
        if live is None
        else dict(
            probability=_quantiles(live[0]),
            change3m=_quantiles(live[3]) if live[3] is not None else [None] * 3,
            warning=wilson(int(live[2].sum()), n),
        )
    )
    hist = [
        dict(lead=int(lead) or None, count=int(count))
        for lead, count in zip(*np.unique(timing['lead2001'], return_counts=True))
    ]
    _write_draws(writer, latest.date, sid, timing, stats, flags)
    return dict(
        id=sid,
        label=label,
        capBp=cap,
        blockMonths=block,
        draws=n,
        gates=gates,
        windows={k: {f: _quantiles(v) for f, v in w.items()} for k, w in stats.items()},
        funnel=[dict(gate=k, count=c) for k, c in stages],
        leadHistogram=hist,
        latest=now,
        examples=_examples(issues, shocks, flags['joint'], stats, timing, calendar),
    )


def build_path_simulation(expansion, momentum, legs, calibration, *, csv_path=None, draws=DRAWS, seed=SEED):
    """Write optional per-draw evidence during the replay; the site payload stays compact."""
    if draws < 1:
        raise ValueError('Simulation needs a positive number of paths')
    calendar, issues, live, baseline = _prepare(expansion, momentum, legs)
    latest = expansion['latest']
    overall = {
        key: latest[key]
        for key in (
            'issueDate',
            'featureDate',
            'refitDate',
            'forecastStart',
            'forecastEnd',
            'available',
            'probability',
        )
    }
    source = dict(
        source=calibration.provenance,
        first=calibration.summary(calendar[0]),
        may2000=calibration.summary(month_offset(MAY, -2)),
        latest=calibration.summary(latest['featureDate']),
    )
    scenarios = []
    raw = None
    previous_block = None
    with _csv_writer(csv_path) as writer:
        for sid, label, cap, block in VARIANTS:
            if block != previous_block:
                raw = None
                raw = draw_shocks(calibration, calendar, draws, seed, block)
                if raw.shape != (len(calendar), draws, 2) or not np.isfinite(raw).all():
                    raise ValueError('Calendar simulation requires a finite short/long pair per month and draw')
                previous_block = block
            # Clipping preserves the position of all shared calendar observations
            # and pairs every sensitivity with exactly the same uncapped base draw.
            if cap is None:
                paths = raw
            else:
                paths = np.clip(raw, -cap, cap)
            scenarios.append(_scenario(sid, label, cap, block, paths, calendar, issues, live, baseline, writer))
            del paths
    return dict(
        spec={
            **SPEC,
            'seed': seed,
            'draws': draws,
            'observationStart': calendar[0],
            'observationEnd': calendar[-1],
        },
        calibration=source,
        latest=overall,
        baseline=baseline,
        scenarios=scenarios,
    )
