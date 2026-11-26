export type RatePathFeature = 'slope' | 'credit' | 'labor' | 'slopeChange6' | 'fedFundsChange12';
export type RatePathMethod =
  | 'original'
  | 'existingBlend'
  | 'base'
  | 'rawFive'
  | 'candidate'
  | 'recentPrior'
  | 'recentBlend';
export type RatePathFeatures = Record<RatePathFeature, number>;

export type RatePathScore = {
  auc: number | null;
  brier: number | null;
  logLoss: number | null;
};

export type RatePathCohort = {
  id: string;
  label: string;
  start: string | null;
  end: string | null;
  n: number;
  positiveWindows: number;
  models: Record<RatePathMethod, RatePathScore> & {
    candidateBase?: RatePathScore;
    matchedThree?: RatePathScore;
    matchedThreeBlend?: RatePathScore;
  };
  improvement?: Record<string, { brier: number | null; logLoss: number | null }>;
};

export type RatePathHistoryRow = RatePathFeatures & {
  date: string;
  featureDate: string;
  target: 0 | 1 | null;
  recession: number | null;
  originalProbability: number;
  existingBlendProbability: number;
  baselineProbability: number;
  candidateBaseProbability: number;
  rawProbability: number;
  probability: number;
  refitDate: string;
  trainingCutoff: string;
  trainEnd: string;
  lastTargetMonth: string;
  trainingN: number;
  recentPriorProbability: number | null;
  recentBlendProbability: number | null;
  recentPriorN: number;
  recentPriorStart: string;
  recentPriorEnd: string;
  recentPriorObservedStart?: string | null;
  recentPriorObservedEnd?: string | null;
  matchedThreeProbability?: number;
  matchedThreeBlendProbability?: number;
};

export type RatePathFrozenPredictions = {
  original: number;
  existingBlend: number;
  historicalBase: number;
  candidateRaw: number;
  candidateBlend: number;
  recentPrior: number;
  recentBlend: number;
};

export type RatePathReceipt = {
  recordedAt: string;
  issueDate: string;
  featureDate: string;
  forecastStart: string;
  forecastEnd: string;
  predictions: RatePathFrozenPredictions;
  hash: string;
  previousHash: string | null;
  baseRates: { original: number; candidate: number };
  [key: string]: unknown;
};

export type RatePathProspective = {
  protocolVersion: string;
  receiptCount: number;
  maturedCount: number;
  chainValid: boolean;
  latestReceipt: RatePathReceipt | null;
  receipts: RatePathReceipt[];
  outcomes: unknown[];
  metrics: Record<keyof RatePathFrozenPredictions, { n: number; brier: number; logLoss: number } | null>;
  pairedComparisons: unknown;
  evaluatedAt: string;
  downloadUrl: string;
  note: string;
};

export type RatePathSnapshot = {
  version: string;
  status: string;
  spec: {
    id: string;
    featureOrder: RatePathFeature[];
    recipe: string;
    [key: string]: unknown;
  };
  model: {
    featureOrder: RatePathFeature[];
    means: number[];
    scales: number[];
    coefficients: number[];
    intercept: number;
    trainedThrough?: string;
    trainingN?: number;
    [key: string]: unknown;
  };
  latest: {
    probability: number;
    fixed50Probability: number;
    rawProbability: number;
    originalProbability: number | null;
    originalBaseProbability?: number | null;
    existingBlendProbability: number | null;
    baselineProbability: number;
    candidateBaseProbability?: number;
    recentPriorProbability: number | null;
    recentBlendProbability: number | null;
    recentPriorN: number;
    recentPriorStart: string;
    recentPriorEnd: string;
    recentPriorObservedStart?: string | null;
    recentPriorObservedEnd?: string | null;
    features: RatePathFeatures;
    issueDate: string;
    featureDate: string;
    forecastStart: string;
    forecastEnd: string;
    trainingN: number;
    trainedThrough: string;
  };
  metrics: {
    all: RatePathCohort;
    recent: RatePathCohort;
    decades: RatePathCohort[];
  };
  history: RatePathHistoryRow[];
  folds: unknown[];
  coverage: Record<string, unknown>;
  prospective?: RatePathProspective;
};
