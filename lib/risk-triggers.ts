/** Conditional inverse-logistic research thresholds. No causal interpretation. */
export type TriggerModel = {
  featureOrder: string[];
  means?: number[]; scales?: number[]; coefficients?: number[]; intercept?: number;
  rawCoefficients?: number[]; rawIntercept?: number;
  refitDate?: string; trainedThrough?: string; trainingN?: number;
};
export type TriggerFeatures = { slope: number; credit: number; labor: number; interaction?: number };
export type TriggerTrainingPoint = { slope: number; credit: number; labor?: number; date?: string; target?: number };
export type CreditTriggerInput = {
  model: TriggerModel; features: TriggerFeatures; targetProbability?: number; slope?: number;
  trainingPoints?: TriggerTrainingPoint[]; supportRadiusStd?: number;
};
export type CreditTriggerResult = {
  targetProbability: number; currentP: number; requiredCredit: number | null; creditShift: number | null;
  relation: 'at-least' | 'at-most' | 'insensitive'; status: 'solved' | 'constant-at-target' | 'unreachable';
  /** Equality p=target has a finite solution; thresholdSatisfied separately reports current p>=target. */
  reachable: boolean; thresholdSatisfied: boolean; effectiveCreditCoefficient: number;
  features: TriggerFeatures; triggerFeatures: TriggerFeatures | null; modelDate: string | null;
  support: { available: boolean; currentN: number | null; targetN: number | null; radiusStd: number; trainingN: number;
    observedCreditMin: number | null; observedCreditMax: number | null; outsideObservedCreditRange: boolean | null; note: string };
};

type PreparedModel = { order: string[]; raw: number[]; intercept: number; interaction: boolean; slopeScale?: number; creditScale?: number };
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const close = (a: number, b: number) => Math.abs(a - b) <= 1e-8 * Math.max(1, Math.abs(a), Math.abs(b));

function prepareModel(model: TriggerModel): PreparedModel {
  const order = model.featureOrder;
  const keys = ['slope', 'credit', 'labor'];
  if (!Array.isArray(order) || ![3, 4].includes(order.length) || new Set(order).size !== order.length
    || !keys.every(key => order.includes(key)) || order.some(key => ![...keys, 'interaction'].includes(key))
    || (order.length === 4 && !order.includes('interaction'))) throw new RangeError('Unsupported or mismatched model feature order');
  const checkArray = (values: number[] | undefined, name: string): number[] => {
    if (!Array.isArray(values) || values.length !== order.length || !values.every(finite)) throw new RangeError(`Invalid model ${name} dimensions or values`);
    return values;
  };
  const hasStandard = model.means !== undefined || model.scales !== undefined || model.coefficients !== undefined || model.intercept !== undefined;
  const hasRaw = model.rawCoefficients !== undefined || model.rawIntercept !== undefined;
  if (!hasStandard && !hasRaw) throw new RangeError('Model parameters are missing');
  let derivedRaw: number[] | undefined, derivedIntercept: number | undefined;
  let slopeScale: number | undefined, creditScale: number | undefined;
  if (hasStandard) {
    const means = checkArray(model.means, 'means'), scales = checkArray(model.scales, 'scales'), coefficients = checkArray(model.coefficients, 'coefficients');
    if (!scales.every(scale => scale > 0) || !finite(model.intercept)) throw new RangeError('Invalid model scales or intercept');
    derivedRaw = coefficients.map((coefficient, i) => coefficient / scales[i]);
    derivedIntercept = model.intercept - derivedRaw.reduce((sum, coefficient, i) => sum + coefficient * means[i], 0);
    slopeScale = scales[order.indexOf('slope')];
    creditScale = scales[order.indexOf('credit')];
  }
  let raw = derivedRaw, intercept = derivedIntercept;
  if (hasRaw) {
    const supplied = checkArray(model.rawCoefficients, 'raw coefficients');
    if (!finite(model.rawIntercept)) throw new RangeError('Invalid raw model intercept');
    if (derivedRaw && (!supplied.every((value, i) => close(value, derivedRaw![i])) || !close(model.rawIntercept, derivedIntercept!))) throw new RangeError('Raw and standardized model parameters disagree');
    // Prefer standardized parameters when available, matching published scoring.
    raw = derivedRaw ?? supplied;
    intercept = derivedIntercept ?? model.rawIntercept;
  }
  if (!raw?.every(finite) || !finite(intercept)) throw new RangeError('Nonfinite derived model parameters');
  return { order, raw, intercept, interaction: order.includes('interaction'), slopeScale, creditScale };
}

function normalizedFeatures(features: TriggerFeatures, interaction: boolean, slope = features.slope): TriggerFeatures {
  if (![slope, features.credit, features.labor].every(finite) || features.labor < -1e-10) throw new RangeError('Features must be finite; the labor gap must be nonnegative');
  const result: TriggerFeatures = { slope, credit: features.credit, labor: Math.max(0, features.labor) };
  if (interaction) result.interaction = Math.max(-slope, 0) * result.credit;
  if (!Object.values(result).every(finite)) throw new RangeError('Derived interaction is nonfinite');
  return result;
}

function logitAt(model: PreparedModel, features: TriggerFeatures): number {
  const values = features as Record<string, number>;
  const z = model.intercept + model.raw.reduce((sum, coefficient, i) => sum + coefficient * values[model.order[i]], 0);
  if (!Number.isFinite(z)) throw new RangeError('Model logit is nonfinite at these features');
  return z;
}
function logistic(z: number): number {
  return z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
}

/** Recomputes interaction internally, so a stale supplied interaction is ignored. */
export function probabilityAtFeatures(model: TriggerModel, features: TriggerFeatures): number {
  const prepared = prepareModel(model);
  return logistic(logitAt(prepared, normalizedFeatures(features, prepared.interaction)));
}

/** Required raw NFCICREDIT index value to reach a chosen probability at fixed slope/labor. */
export function solveCreditTrigger(input: CreditTriggerInput): CreditTriggerResult {
  const { model, targetProbability = 0.30, trainingPoints, supportRadiusStd = 0.35 } = input;
  if (!finite(targetProbability) || targetProbability <= 0 || targetProbability >= 1) throw new RangeError('Target probability must lie strictly between zero and one');
  if (!finite(supportRadiusStd) || supportRadiusStd <= 0) throw new RangeError('Support radius must be positive and finite');
  const prepared = prepareModel(model);
  const features = normalizedFeatures(input.features, prepared.interaction, input.slope ?? input.features.slope);
  const coefficients = Object.fromEntries(prepared.order.map((key, i) => [key, prepared.raw[i]]));
  const effectiveCreditCoefficient = coefficients.credit + (coefficients.interaction ?? 0) * Math.max(-features.slope, 0);
  if (!finite(effectiveCreditCoefficient)) throw new RangeError('Effective credit coefficient is nonfinite');
  const currentLogit = logitAt(prepared, features), currentP = logistic(currentLogit);
  const targetLogit = Math.log(targetProbability) - Math.log1p(-targetProbability);
  const constantLogit = prepared.intercept + coefficients.slope * features.slope + coefficients.labor * features.labor;
  let requiredCredit: number | null = null, creditShift: number | null = null, triggerFeatures: TriggerFeatures | null = null;
  let relation: CreditTriggerResult['relation'] = 'insensitive';
  let status: CreditTriggerResult['status'] = 'unreachable';
  let reachable = false;
  if (effectiveCreditCoefficient === 0) {
    // All credit levels have the same probability; there is no unique threshold.
    if (Math.abs(currentLogit - targetLogit) <= 1e-12) { status = 'constant-at-target'; reachable = true; }
  } else {
    relation = effectiveCreditCoefficient > 0 ? 'at-least' : 'at-most';
    const solution = (targetLogit - constantLogit) / effectiveCreditCoefficient;
    const shift = solution - features.credit;
    if (Number.isFinite(solution) && Number.isFinite(shift)) {
      requiredCredit = solution; creditShift = shift;
      triggerFeatures = normalizedFeatures({ ...features, credit: solution }, prepared.interaction);
      status = 'solved'; reachable = true;
    }
  }
  if (trainingPoints !== undefined && (!Array.isArray(trainingPoints) || trainingPoints.some(point => !finite(point.slope) || !finite(point.credit) || (point.labor !== undefined && !finite(point.labor))))) throw new RangeError('Training support points must contain finite observations');
  const points = trainingPoints ?? [];
  const available = points.length > 0 && prepared.slopeScale !== undefined && prepared.creditScale !== undefined;
  const neighborCount = (credit: number) => points.filter(point => Math.hypot((point.slope - features.slope) / prepared.slopeScale!, (point.credit - credit) / prepared.creditScale!) <= supportRadiusStd + 1e-12).length;
  const observedCreditMin = points.length ? Math.min(...points.map(point => point.credit)) : null;
  const observedCreditMax = points.length ? Math.max(...points.map(point => point.credit)) : null;
  return {
    targetProbability, currentP, requiredCredit, creditShift, relation, status, reachable,
    thresholdSatisfied: currentLogit >= targetLogit, effectiveCreditCoefficient, features, triggerFeatures,
    modelDate: model.refitDate ?? model.trainedThrough ?? null,
    support: { available, currentN: available ? neighborCount(features.credit) : null,
      targetN: available && requiredCredit !== null ? neighborCount(requiredCredit) : null,
      radiusStd: supportRadiusStd, trainingN: points.length, observedCreditMin, observedCreditMax,
      outsideObservedCreditRange: requiredCredit !== null && observedCreditMin !== null && observedCreditMax !== null
        ? requiredCredit < observedCreditMin || requiredCredit > observedCreditMax : null,
      note: 'Counts are overlapping training months within the radius in training-standardized slope/credit space; labor proximity is ignored. The observed credit range is descriptive, not a confidence interval. These are conditional model thresholds, not causal forecasts.' }
  };
}
