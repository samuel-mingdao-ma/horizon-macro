/** Exact fixed-coupon bond valuation at a coupon date; nominal annual yield. */
export type BondOptions = {
  years?: number;
  couponPercent?: number;
  face?: number;
  frequency?: number;
};

export type BondRisk = {
  price: number;
  face: number;
  years: number;
  couponPercent: number;
  yieldPercent: number;
  frequency: number;
  macaulayDuration: number;
  modifiedDuration: number;
  convexity: number;
  dv01: number;
};

/** Yields/coupons in percent (5 means 5%); price and DV01 per face amount. */
export function bondRisk(yieldPercent: number, options: BondOptions = {}): BondRisk {
  const { years = 10, couponPercent = yieldPercent, face = 100, frequency = 2 } = options;
  const periods = years * frequency;
  if (![yieldPercent, years, couponPercent, face, frequency].every(Number.isFinite)
    || years <= 0 || face <= 0 || couponPercent < 0 || frequency <= 0
    || !Number.isInteger(frequency) || !Number.isInteger(periods)
    || 1 + yieldPercent / 100 / frequency <= 0) throw new RangeError('Invalid fixed-coupon bond inputs');
  const yieldDecimal = yieldPercent / 100;
  const discount = 1 + yieldDecimal / frequency;
  const coupon = face * (couponPercent / 100) / frequency;
  let price = 0;
  let timeWeighted = 0;
  let convexityWeighted = 0;
  for (let period = 1; period <= periods; period++) {
    const presentValue = (coupon + (period === periods ? face : 0)) / discount ** period;
    const time = period / frequency;
    price += presentValue;
    timeWeighted += time * presentValue;
    convexityWeighted += time * (time + 1 / frequency) * presentValue / discount ** 2;
  }
  const macaulayDuration = timeWeighted / price;
  const modifiedDuration = macaulayDuration / discount;
  return { price, face, years, couponPercent, yieldPercent, frequency, macaulayDuration, modifiedDuration,
    convexity: convexityWeighted / price, dv01: price * modifiedDuration * 0.0001 };
}

/** Fixed coupon is selected once at the base yield and held through the shock. */
export function repriceBond(baseYieldPercent: number, shockBasisPoints: number, options: BondOptions = {}) {
  if (!Number.isFinite(shockBasisPoints)) throw new RangeError('Shock must be a finite number of basis points');
  const fixed = { ...options, couponPercent: options.couponPercent ?? baseYieldPercent };
  const base = bondRisk(baseYieldPercent, fixed);
  const stressed = bondRisk(baseYieldPercent + shockBasisPoints / 100, fixed);
  const deltaYield = shockBasisPoints / 10_000;
  const exactReturn = stressed.price / base.price - 1;
  return { ...base, basePrice: base.price, stressedPrice: stressed.price, shockBasisPoints,
    priceChange: stressed.price - base.price, exactReturn,
    durationConvexityReturn: -base.modifiedDuration * deltaYield + 0.5 * base.convexity * deltaYield ** 2,
    pnlPer100k: exactReturn * 100_000 };
}

export type ModelFeatures = { slope: number; credit: number; labor: number };
export type ModelParameters = { featureOrder: string[]; means: number[]; scales: number[]; coefficients: number[]; intercept: number };
export type ScenarioShocks = { slopeBps?: number; creditUnits?: number; laborPp?: number };

/** Conditional model sensitivity, not a causal estimate or a forecast scenario. */
export function modelScenario(model: ModelParameters, baseFeatures: ModelFeatures, shocks: ScenarioShocks = {}) {
  const { slopeBps = 0, creditUnits = 0, laborPp = 0 } = shocks;
  if (![slopeBps, creditUnits, laborPp, ...Object.values(baseFeatures)].every(Number.isFinite)) throw new RangeError('Scenario inputs must be finite');
  const features: ModelFeatures = { slope: baseFeatures.slope + slopeBps / 100,
    credit: baseFeatures.credit + creditUnits, labor: Math.max(0, baseFeatures.labor + laborPp) };
  const contributions = model.featureOrder.map((key, index) => {
    const value = features[key as keyof ModelFeatures];
    const standardized = (value - model.means[index]) / model.scales[index];
    return { key, value, standardized, logOdds: standardized * model.coefficients[index] };
  });
  const logit = model.intercept + contributions.reduce((sum, term) => sum + term.logOdds, 0);
  const probability = logit >= 0 ? 1 / (1 + Math.exp(-logit)) : Math.exp(logit) / (1 + Math.exp(logit));
  return { probability, features, contributions, logit };
}
