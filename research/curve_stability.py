"""Sensitivity of the existing pace alarm to long-yield deadbands and bill/fall ratios."""

from curve_legs import SPEC as LEGS_SPEC, UNIT
from leading_trial import number
from pace_trial import CASE_DATE, CASE_ONSET


BANDS = (0, 2, 5, 10)
RATIOS = (1.5, 1.75, 2, 2.25, 2.5)
GRID = tuple((f'd{band}-r{ratio:g}', band, ratio) for band in BANDS for ratio in RATIOS)
STRESS_BP = 3
BP_UNIT = UNIT // 100
CONTROL = 'd0-r2'
REFERENCE = 'd5-r2'
CASES = (CASE_DATE, '2019-02-01')
SPEC = dict(
    id='expansion-onset-yield-deadband-sensitivity-v1', parentId=LEGS_SPEC['id'],
    bandsBp=list(BANDS), ratios=list(RATIOS), stressBp=STRESS_BP, referenceId=REFERENCE, originalId=CONTROL,
    scope='Keep every published expansion probability and 30% level alarm. Screen extra three-month pace alerts only.',
    rule='Require a bill rise and net flattening at the evaluated prices. Treat a ten-year change inside the inclusive symmetric band as zero. The effective ten-year yield must be flat or falling and the bill rise must be at least the specified ratio times the effective fall.',
    stress='Perturb each three-month ten-year change anywhere within plus or minus three basis points, holding bills, probabilities and parent alerts fixed. Guaranteed requires acceptance throughout the interval. Possible requires acceptance somewhere. This is a filter sensitivity bound that permits a different perturbation in each month.',
    test='Keep the May 2000 extra alert and at least eleven months of lead before the April 2001 onset. Preserve complete detections and add no quiet alert in either window. The stress test uses guaranteed leads and possible quiet alerts.',
    timing='The 2:1 rule was originally chosen after inspecting these cases. The tolerance grid and 5 bp, 2:1 reference were fixed for this sensitivity check on the same revised history. Both full and recent samples were previously inspected.',
    precision='Rates are percentages. One basis point is 0.01 percentage point. Compare integer yield units at 12-decimal precision and exact rational ratio boundaries. Raw net flattening is strictly positive even inside the flat band.',
    missing='Missing rate changes disable only the supplemental decision. An unavailable parent probability leaves all decisions unavailable.',
)


def _rate_units(value):
    value = number(value)
    return round(value * UNIT) if value is not None else None


def evaluate_cell(short_change, long_change, level, quarter, band_bp, ratio):
    """Return alarm decisions using the exact continuous interval of eligible long-rate changes."""
    if band_bp not in BANDS or ratio not in RATIOS:
        raise ValueError('Unregistered band or ratio')
    if not (level is None and quarter is None or type(level) is bool and type(quarter) is bool and (not level or quarter)):
        raise ValueError('Inconsistent level and parent pace alarms')
    s, l = _rate_units(short_change), _rate_units(long_change)
    actual = guaranteed = possible = minus = plus = False
    lower_bp = upper_bp = upper_inclusive = None
    if s is not None and s > 0:
        numerator, denominator = ratio.as_integer_ratio()
        band = band_bp * BP_UNIT
        # All interval endpoints share the denominator numerator; no ratios are rounded.
        low = -max(band * numerator, s * denominator)
        high = min(band, s) * numerator
        upper_inclusive = band < s  # Net flattening excludes L == S even if L lies inside the band.
        lower_bp, upper_bp = low / (numerator * BP_UNIT), high / (numerator * BP_UNIT)

        def below_ceiling(x):
            return x <= high if upper_inclusive else x < high

        if l is not None:
            centre = l * numerator
            radius = STRESS_BP * BP_UNIT * numerator
            left, right = centre - radius, centre + radius
            actual = centre >= low and below_ceiling(centre)
            minus = left >= low and below_ceiling(left)
            plus = right >= low and below_ceiling(right)
            guaranteed = minus and plus
            # The stress interval can overlap the pass region with both endpoints outside it.
            possible = right >= low and below_ceiling(left)

    def alarm(eligible):
        return None if level is None else level or (quarter and eligible)

    return dict(actual=alarm(actual), guaranteed=alarm(guaranteed), possible=alarm(possible),
                minus3=alarm(minus), plus3=alarm(plus), lowerBp=lower_bp, upperBp=upper_bp,
                upperInclusive=upper_inclusive)


def grid_results(short_change, long_change, level, quarter):
    return {key: evaluate_cell(short_change, long_change, level, quarter, band, ratio) for key, band, ratio in GRID}


def _grid(row):
    results = grid_results(row['shortChange'], row['longChange'], row['levelAlert'], row['quarterAlert'])
    if results[CONTROL]['actual'] is not row['mixedTwoToOneAlert']:
        raise ValueError('The zero-band 2:1 control does not match the published yield-leg alarm')
    return results


def _lead(onset, issue):
    if issue is None:
        return None
    return 12 * (int(onset[:4]) - int(issue[:4])) + int(onset[5:7]) - int(issue[5:7])


def _window(reference, history):
    paired = [r for r in history if r['commonMature'] and reference['windowStart'] <= r['date'] <= reference['windowEnd']]
    quiet = [r for r in paired if r['target'] == 0 and r['issuePhase'] == 'expansion-no-recession']
    pre = [r for r in paired if r['target'] == 1 and r['issuePhase'] == 'pre-onset']
    level = reference['summary']['level']
    if (len(paired) != reference['n'] or len(quiet) != reference['quietExpansionN'] or len(pre) != reference['preOnsetN']
            or len(pre) + len(quiet) != len(paired) or any(r['levelAlert'] is None for r in paired)
            or sum(r['levelAlert'] for r in quiet) != level['quietAlerts']
            or sum(r['levelAlert'] for r in pre) != level['preOnsetAlerts']):
        raise ValueError('The stability grid requires the same mature expansion origins as its control')
    episodes = []
    by_onset = {}
    for ep in reference['episodes']:
        onset = ep['onsetDate']
        dates = [r for r in pre if r['onsetDate'] == onset]
        first = next((r['date'] for r in dates if r['levelAlert']), None)
        if (len(dates) != ep['availableMonths'] or first != ep['methods']['level']['firstAlertDate']
                or _lead(onset, first) != ep['methods']['level']['leadMonths']):
            raise ValueError('Mismatched level timing or coverage before a recession onset')
        episodes.append(dict(onsetDate=onset, coverage=ep['coverage'], availableMonths=len(dates),
                             levelLead=_lead(onset, first), levelFirstDate=first))
        by_onset[onset] = dates
    fields = ('windowStart', 'windowEnd', 'n', 'quietExpansionN', 'preOnsetN', 'probabilityScores', 'completeEpisodes')
    return dict(**{k: reference[k] for k in fields}, levelQuiet=level['quietAlerts'], levelPre=level['preOnsetAlerts'],
                levelHits=level['completeHits'], episodes=episodes), quiet, pre, by_onset


def _cell_window(key, data, results):
    _, quiet, pre, by_onset = data
    window = {}
    for mode in ('actual', 'guaranteed', 'possible'):
        for phase, rows in (('Quiet', quiet), ('Pre', pre)):
            window[mode + phase + 'Dates'] = [
                r['date'] for r in rows if not r['levelAlert'] and results[r['date']][key][mode]
            ]
    episodes = []
    for onset, rows in by_onset.items():
        ep = dict(onsetDate=onset)
        for mode in ('actual', 'guaranteed', 'possible'):
            first = next((r['date'] for r in rows if results[r['date']][key][mode]), None)
            ep[mode + 'FirstDate'], ep[mode + 'Lead'] = first, _lead(onset, first)
        episodes.append(ep)
    window['episodes'] = episodes
    return window


def _passes(windows, totals, case, may, stressed):
    mode = 'guaranteed' if stressed else 'actual'
    quiet_mode = 'possible' if stressed else 'actual'
    full_episode = next((ep for ep in totals['all']['episodes'] if ep['onsetDate'] == CASE_ONSET), None)
    if (not may or not may['commonMature'] or may['onsetDate'] != CASE_ONSET or may['target'] != 1
            or may['levelAlert'] or not may['quarterAlert'] or not case or not case[mode]
            or not full_episode or full_episode['coverage'] != 'full'):
        return False
    for name, w in windows.items():
        total = totals[name]
        if not total['completeEpisodes'] or not total['quietExpansionN'] or w[quiet_mode + 'QuietDates']:
            return False
        for control, ep in zip(total['episodes'], w['episodes']):
            lead = ep[mode + 'Lead'] or 0
            if control['coverage'] == 'full' and lead < (control['levelLead'] or 0):
                return False
            if name == 'all' and ep['onsetDate'] == CASE_ONSET and (lead < 11 or lead <= (control['levelLead'] or 0)):
                return False
    return True


def build_curve_stability_trial(curve_legs):
    fields = ('featureDate', 'lagFeatureDate', 'probability', 'shortChange', 'longChange',
              'levelAlert', 'quarterAlert', 'mixedTwoToOneAlert')
    labels = ('date', 'commonMature', 'issuePhase', 'target', 'onsetDate')
    history = [{k: r[k] for k in (*labels, *fields)} for r in curve_legs['history']]
    dates = [r['date'] for r in history]
    if dates != sorted(set(dates)):
        raise ValueError('The grid requires sorted, unique issue dates')
    results = {r['date']: _grid(r) for r in history}
    parent = curve_legs['latest']
    latest = {k: parent[k] for k in ('issueDate', 'available', 'reason', 'forecastStart', 'forecastEnd', 'refitDate', *fields)}
    latest['results'] = _grid(parent)
    cohorts = {k: _window(curve_legs['windows'][k], history) for k in ('all', 'rolling120')}
    totals = {k: value[0] for k, value in cohorts.items()}
    may = next((row for row in history if row['date'] == CASE_DATE), None)
    cells = []
    for key, band, ratio in GRID:
        windows = {k: _cell_window(key, group, results) for k, group in cohorts.items()}
        cases = {date: results.get(date, {}).get(key) for date in CASES}
        cells.append(dict(id=key, bandBp=band, ratio=ratio, windows=windows, cases=cases,
                          pointPassed=_passes(windows, totals, cases[CASE_DATE], may, False),
                          stressPassed=_passes(windows, totals, cases[CASE_DATE], may, True)))
    return dict(spec=SPEC, latest=latest, history=history, windows=totals, cells=cells)


def stability_csv_rows(trial):
    for row in trial['history']:
        results = _grid(row)
        for key, band, ratio in GRID:
            yield dict(date=row['date'], cellId=key, bandBp=band, ratio=ratio, **{k: v for k, v in row.items() if k != 'date'},
                       **results[key])
