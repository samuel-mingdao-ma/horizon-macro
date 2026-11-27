export type WeightWindow = 'all' | 'rolling120';
export type WeightState = 'stress' | 'normal';
export type WeightMethod =
  | 'existingBlend'
  | 'fixedPermits'
  | 'pooledPermits'
  | 'originalDynamic'
  | 'candidate'
  | 'fixedRule';
export type WarningMethod = Exclude<WeightMethod, 'pooledPermits'>;
type Maybe = number | null;
export type WeightForecast = {
  state: WeightState | null;
  slope: Maybe;
  credit: Maybe;
  originalProbability: Maybe;
  baselineProbability: Maybe;
  rawPermitsProbability: Maybe;
  existingBlendProbability: Maybe;
  fixedPermitsProbability: Maybe;
  pooledPermitsProbability: Maybe;
  originalDynamicProbability: Maybe;
  probability: Maybe;
  permitsWeight: Maybe;
  pooledWeight: Maybe;
  originalWeight: Maybe;
  fixedRuleWeight: Maybe;
  fixedRuleProbability: Maybe;
  refitDate: string;
  trainingCutoff: string;
  trainingN: number;
  featureDate: string;
};
type WeightCell = { n: number; weight: Maybe };
export type WeightFit = {
  refitDate: string;
  trainEnd: string | null;
  trainingCutoff: string;
  lastTargetMonth: string | null;
  trainingN: number;
  warmup: boolean;
  permits: Record<'pool' | WeightState, WeightCell>;
};
type WeightScore = { brier: Maybe; logLoss: Maybe; auc: Maybe };
type WeightSlice = {
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  positiveWindows: number;
  incumbentN: number;
  missingCandidateMonths: number;
  models: Record<WeightMethod, WeightScore>;
};
type Gate = { allPassed: boolean; rolling120Passed: boolean; passed: boolean };
export type WarningResult = {
  firstAlertDate: string | null;
  leadMonths: Maybe;
  firstCrossDate: string | null;
  crossLeadMonths: Maybe;
  firstAlertKind: 'new-crossing' | 'already-high' | 'previous-unknown' | null;
  flaggedMonths: number;
  firstCrossUncertain: boolean;
};
export type WarningSlice = {
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  quietExpansionN: number;
  preOnsetN: number;
  recessionIssuedN: number;
  completeEpisodes: number;
  partialEpisodes: number;
  unavailableEpisodes: number;
  summary: Record<
    WarningMethod,
    {
      completeHits: number;
      meanLeadMonths: Maybe;
      quietAlerts: number;
      quietRate: Maybe;
      preOnsetAlerts: number;
      preOnsetRate: Maybe;
      completeCrossHits: number;
      meanCrossLeadMonths: Maybe;
    }
  >;
  episodes: {
    onsetDate: string;
    availableMonths: number;
    coverage: 'full' | 'partial' | 'unavailable';
    methods: Record<WarningMethod, WarningResult>;
  }[];
  comparison: {
    baselineAtCeiling: boolean;
    sufficient: boolean;
    earlier: number;
    tied: number;
    later: number;
    passes: boolean;
  };
};
export type WeightTrial = {
  latest: WeightForecast & {
    issueDate: string;
    forecastStart: string;
    forecastEnd: string;
    available: boolean;
    reason: string | null;
    fit: WeightFit;
  };
  history: (WeightForecast & { date: string; target: number | null; commonMature: boolean })[];
  metrics: Record<WeightWindow, WeightSlice>;
  gate: Gate & { versusFixedPermits: Gate };
  ruleGate: Gate & { versusFixedPermits: Gate };
  warnings?: { threshold: number; windows: Record<WeightWindow, WarningSlice>; gate: Gate; ruleGate: Gate };
  prospective?: {
    receiptCount: number;
    maturedCount: number;
    latestReceipt: { issueDate: string; recordedAt: string; predictions: Record<string, number> } | null;
    metrics?: Record<string, { n: number; brier: Maybe; logLoss: Maybe } | null>;
  };
};
