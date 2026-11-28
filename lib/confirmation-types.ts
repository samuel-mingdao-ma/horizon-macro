import type { WarningResult, WarningSlice } from './weight-types';

export type ConfirmationRule = 'pressure' | 'direction' | 'breadth';
export type ConfirmationWindow = 'all' | 'rolling120';
type Policy = ConfirmationRule | 'level' | 'quarter';
type Maybe = number | null;
export type ConfirmationReading = {
  featureDate: string;
  lagFeatureDate: string;
  probability: Maybe;
  change1m: Maybe;
  change3m: Maybe;
  permitGrowth6: Maybe;
  claimsGrowth12: Maybe;
  credit: Maybe;
  lagPermitGrowth6: Maybe;
  lagClaimsGrowth12: Maybe;
  lagCredit: Maybe;
  permitsNegative: boolean | null;
  claimsPositive: boolean | null;
  creditTightening: boolean | null;
  permitsSlowing: boolean | null;
  claimsRising: boolean | null;
  pressureVotes: Maybe;
  directionVotes: Maybe;
  levelAlert: boolean | null;
  quarterAlert: boolean | null;
  pressureAlert: boolean | null;
  directionAlert: boolean | null;
  breadthAlert: boolean | null;
};
export type ConfirmationRow = ConfirmationReading & {
  date: string; commonMature: boolean; issuePhase: string | null; target: Maybe; onsetDate: string | null;
};
export type ConfirmationPeriod = {
  windowStart: string | null; windowEnd: string | null;
  n: number; quietExpansionN: number; preOnsetN: number; completeEpisodes: number;
  probabilityScores: {brier: Maybe; logLoss: Maybe; auc: Maybe};
  changes: Record<Exclude<Policy, 'level'>, {quietDates: string[]; preOnsetDates: string[]}>;
  summary: Record<Policy, WarningSlice['summary']['candidate']>;
  episodes: {onsetDate: string; availableMonths: number; coverage: 'full' | 'partial' | 'unavailable'; methods: Record<Policy, WarningResult>}[];
};
export type ConfirmationTrial = {
  latest: ConfirmationReading & {issueDate: string; forecastStart: string; forecastEnd: string; available: boolean; reason: string | null};
  caseAttribution: Record<string, {
    startRisk: number; endRisk: number; change: number;
    effects: Record<'slope' | 'credit' | 'labor' | 'permitGrowth6', number>;
  } | null>;
  history: ConfirmationRow[];
  windows: Record<ConfirmationWindow, ConfirmationPeriod>;
  gate: Record<ConfirmationRule, {mayRetained: boolean; allNoAddedFalse: boolean; rolling120NoAddedFalse: boolean; maintainedHitsBoth: boolean; passed: boolean}>;
  prospective?: {receiptCount: number; maturedCount: number; excludedCount: number; pendingCount: number; latestReceipt: {issueDate: string} | null};
};
