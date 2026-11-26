export type LeadingProbabilities = {
  originalProbability: number | null;
  baselineProbability: number | null;
  existingBlendProbability: number | null;
  matchedThreeBlendProbability: number | null;
  permitsBlendProbability: number | null;
  claimsBlendProbability: number | null;
  rawProbability: number | null;
  probability: number | null;
};

export type LeadingSignals = {
  slope: number | null;
  credit: number | null;
  labor: number | null;
  permitGrowth6: number | null;
  claimsGrowth12: number | null;
};
export type LeadingMethod =
  | 'existingBlend'
  | 'matchedThreeBlend'
  | 'permitsBlend'
  | 'claimsBlend'
  | 'rawFive'
  | 'candidate';
export type LeadingWindow = 'all' | 'rolling120';
export type LeadingScore = { brier: number | null; logLoss: number | null; auc: number | null };
export type LeadingSlice = {
  start: string | null;
  end: string | null;
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  positiveWindows: number;
  incumbentN: number;
  missingCandidateMonths: number;
  models: Record<LeadingMethod, LeadingScore>;
};

export type LeadingObservation = LeadingSignals &
  LeadingProbabilities & {
    date: string;
    featureDate: string;
    target: number | null;
    recession: number | null;
    commonMature: boolean;
  };
export type LeadingIssue = LeadingProbabilities & {
  available: boolean;
  reason: string | null;
  issueDate: string;
  featureDate: string;
  forecastStart: string;
  forecastEnd: string;
  features: LeadingSignals;
};
export type LeadingReceipt = {
  issueDate: string;
  recordedAt: string;
  forecastStart: string;
  forecastEnd: string;
  hash: string;
  predictions: Record<string, number>;
};
export type LeadEpisodeRow = LeadingSignals &
  Pick<
    LeadingProbabilities,
    | 'originalProbability'
    | 'baselineProbability'
    | 'existingBlendProbability'
    | 'permitsBlendProbability'
    | 'probability'
  > & {
    date: string;
    featureDate: string;
    monthsToOnset: number;
  };
export type LeadEpisode = { onsetDate: string; rows: LeadEpisodeRow[] };
export type LeadGroup = {
  n: number;
  positiveWindows: number;
  observedRate: number | null;
  incumbentMean: number | null;
  candidateMean: number | null;
  rawMean: number | null;
  baseMean: number | null;
  incumbentBrier: number | null;
  candidateBrier: number | null;
  permitsBrier: number | null;
  permitsMean: number | null;
  blendMinusRaw: number | null;
  meanInputs: LeadingSignals;
  incumbentBelowRawN: number;
  laborBelowHalfN: number;
  creditNonpositiveN: number;
};
export type LeadBand = LeadGroup & { lower: number; upper: number };
export type LeadGroupKey =
  | 'pre1to3'
  | 'pre4to6'
  | 'pre7to12'
  | 'preOnset'
  | 'recessionIssued'
  | 'quietExpansion'
  | 'allExpansion';
export type LeadDiagnosticWindow = {
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  unclassifiedN: number;
  episodeCount: number;
  groups: Record<LeadGroupKey, LeadGroup>;
  calibration: { incumbent: LeadBand[]; candidate: LeadBand[] };
};
export type LeadingTrial = {
  diagnostics?: {
    windows: Record<LeadingWindow, LeadDiagnosticWindow>;
    episodes: LeadEpisode[];
  };
  version: string;
  latest: LeadingIssue;
  history: LeadingObservation[];
  metrics: Record<LeadingWindow, LeadingSlice>;
  gate: { allPassed: boolean; rolling120Passed: boolean; passed: boolean };
  prospective?: {
    receiptCount: number;
    maturedCount: number;
    chainValid: boolean;
    latestReceipt: LeadingReceipt | null;
    metrics: Record<string, LeadingScore | null>;
  };
};
