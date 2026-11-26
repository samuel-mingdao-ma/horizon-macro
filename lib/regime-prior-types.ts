export type RegimeStateId = 'loose-low' | 'loose-elevated' | 'tight-low' | 'tight-elevated';
export type RegimePriorMethod =
  | 'original'
  | 'fixedBlend'
  | 'recentBlend'
  | 'expandingBlend'
  | 'dynamicPrior'
  | 'candidate';

export type RegimePriorCell = {
  id: RegimeStateId;
  creditTight: boolean;
  laborElevated: boolean;
  n: number;
  positiveWindows: number;
  rawRate: number | null;
  pooledRate: number | null;
  priorProbability: number | null;
  selected: boolean;
};

export type RegimePriorScore = { auc: number | null; brier: number | null; logLoss: number | null };
export type RegimePriorSlice = {
  id: string;
  label: string;
  start: string | null;
  end: string | null;
  n: number;
  positiveWindows: number;
  windowStart?: string | null;
  windowEnd?: string | null;
  expectedCalendarMonths?: number | null;
  observedMonths?: number;
  missingMonths?: number;
  brierDeltaVsIncumbent?: number | null;
  brierImprovement?: number | null;
  relativeBrierImprovement?: number | null;
  models: Record<RegimePriorMethod, RegimePriorScore> & { adaptive?: RegimePriorScore };
};

export type RegimePriorPredictions = {
  original: number;
  fixedBlend: number;
  recentPrior: number;
  dynamicPrior: number;
  candidate: number;
  recentBlend: number;
  adaptivePrior: number;
  adaptive: number;
};
export type RegimePriorReceipt = {
  recordedAt: string;
  issueDate: string;
  featureDate: string;
  forecastStart: string;
  forecastEnd: string;
  predictions: RegimePriorPredictions;
  hash: string;
  previousHash: string | null;
  [key: string]: unknown;
};
export type RegimePriorProspective = {
  protocolVersion: string;
  receiptCount: number;
  maturedCount: number;
  chainValid: boolean;
  latestReceipt: RegimePriorReceipt | null;
  receipts: RegimePriorReceipt[];
  metrics: Record<keyof RegimePriorPredictions, { n: number; brier: number; logLoss: number } | null>;
  outcomes: unknown[];
  pairedComparisons: unknown;
  downloadUrl: string;
  note: string;
  [key: string]: unknown;
};

export type RegimePriorSnapshot = {
  version: string;
  status: string;
  spec: {
    id: string;
    windowMonths: number;
    minimumObserved: number;
    pseudoMonths: number;
    rawWeight: number;
    priorWeight: number;
    creditThreshold: number;
    laborThreshold: number;
    recipe: string;
    precision?: number;
    [key: string]: unknown;
  };
  latest: {
    available?: boolean;
    probability: number | null;
    adaptiveProbability?: number | null;
    adaptivePriorProbability?: number | null;
    regimeWeight?: number | null;
    weightTrainingN?: number;
    weightTrainEnd?: string | null;
    weightLastTargetMonth?: string | null;
    originalProbability: number | null;
    dynamicPriorProbability: number | null;
    recentPriorProbability: number | null;
    recentBlendProbability: number | null;
    expandingPriorProbability: number | null;
    expandingBlendProbability: number | null;
    baselineProbability?: number;
    fixedBlendProbability: number | null;
    state: RegimeStateId | null;
    stateInputs?: { credit: number; labor: number } | null;
    features: { slope: number | null; credit: number | null; labor: number | null };
    issueDate: string;
    featureDate: string;
    forecastStart: string;
    forecastEnd: string;
    windowStart: string;
    windowEnd: string;
    trainingCutoff: string;
    trainingN: number;
    stateMap: RegimePriorCell[];
  };
  metrics: { all: RegimePriorSlice; rolling120: RegimePriorSlice };
  publicationGate: {
    criterion: string;
    allPassed: boolean;
    rolling120Passed: boolean;
    passed: boolean;
    decision: string;
    note: string;
  };
  adaptiveGate?: {
    criterion: string;
    allPassed: boolean;
    rolling120Passed: boolean;
    passed: boolean;
    decision: string;
    note: string;
  };
  history: RegimePriorHistoryRow[];
  folds: unknown[];
  coverage: Record<string, unknown>;
  prospective?: RegimePriorProspective;
};

export type RegimePriorHistoryRow = {
  date: string;
  target: 0 | 1 | null;
  probability: number | null;
  fixedBlendProbability: number | null;
  originalProbability: number | null;
  dynamicPriorProbability?: number | null;
  recentPriorProbability?: number | null;
  recentBlendProbability?: number | null;
  adaptiveProbability?: number | null;
  adaptivePriorProbability?: number | null;
  regimeWeight?: number | null;
  [key: string]: unknown;
};
