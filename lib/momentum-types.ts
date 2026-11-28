import type { WarningResult, WarningSlice } from './weight-types';

export type MomentumWindow = 'all' | 'rolling120';
export type PaceRule = 'quarter' | 'month';
type Policy = 'level' | PaceRule;
type Maybe = number | null;

type Reading = {
  featureDate: string;
  refitDate: string;
  probability: Maybe;
  lag1Probability: Maybe;
  lag2Probability: Maybe;
  lag3Probability: Maybe;
  change1m: Maybe;
  change3m: Maybe;
  paceAvailable: boolean;
  levelAlert: boolean | null;
  quarterAlert: boolean | null;
  monthAlert: boolean | null;
};

export type MomentumRow = Reading & {
  date: string;
  commonMature: boolean;
  issuePhase: string | null;
  target: Maybe;
  onsetDate: string | null;
};

export type MomentumEpisode = {
  onsetDate: string;
  availableMonths: number;
  coverage: 'full' | 'partial' | 'unavailable';
  methods: Record<Policy, WarningResult>;
};

type Comparison = WarningSlice['comparison'] & { maintainedHits: boolean };
type WindowResult = {
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  quietExpansionN: number;
  preOnsetN: number;
  completeEpisodes: number;
  paceAvailableN: number;
  caseComparison: {date: string; available: boolean; matches: {date: string; probability: number; change1m: number; change3m: number}[]};
  episodes: MomentumEpisode[];
  summary: Record<Policy, WarningSlice['summary']['candidate']>;
  quarterComparison: Comparison;
  monthComparison: Comparison;
  probabilityScores: {brier: Maybe; logLoss: Maybe; auc: Maybe};
  changes: Record<PaceRule, {quietDates: string[]; preOnsetDates: string[]}>;
};

export type MomentumTrial = {
  latest: Reading & {
    issueDate: string;
    forecastStart: string;
    forecastEnd: string;
    available: boolean;
    reason: string | null;
    path: {date: string; featureDate: string; probability: Maybe}[];
  };
  history: MomentumRow[];
  windows: Record<MomentumWindow, WindowResult>;
  gate: Record<PaceRule, {
    allNoAddedFalse: boolean; rolling120NoAddedFalse: boolean; earlierAny: boolean;
    earlierBoth: boolean; maintainedHitsBoth: boolean; passed: boolean;
  }>;
  prospective?: {
    receiptCount: number; maturedCount: number; excludedCount: number; pendingCount: number;
    latestReceipt: {issueDate: string; recordedAt: string} | null;
  };
};
