import type { WarningResult, WarningSlice } from './weight-types';

export type ExpansionWindow = 'all' | 'rolling120';
export type ExpansionMethod = 'benchmark' | 'candidate' | 'signalOnlyChange' | 'baseOnlyChange' | 'expansionPrior';
type Maybe = number | null;
type Pair = 'benchmark' | 'candidate';
type Scores = { brier: Maybe; auc: Maybe; logLoss: Maybe };
type Gate = { allPassed: boolean; rolling120Passed: boolean; passed: boolean };

export type ExpansionEpisode = {
  onsetDate: string;
  availableMonths: number;
  coverage: 'full' | 'partial' | 'unavailable';
  methods: Record<Pair, WarningResult>;
};

export type ExpansionRow = {
  date: string;
  issueRecession: Maybe;
  issuePhase: string | null;
  target: Maybe;
  monthsToOnset: Maybe;
  onsetDate: string | null;
  commonMature: boolean;
  expansionPriorProbability: Maybe;
  benchmarkProbability: Maybe;
  probability: Maybe;
};

export type ExpansionTrial = {
  latest: {
    issueDate: string; featureDate: string; forecastStart: string; forecastEnd: string;
    available: boolean; reason: string | null;
    probability: Maybe; benchmarkProbability: Maybe;
    rawExpansionProbability: Maybe; expansionPriorProbability: Maybe;
    trainingN: number; trainingPositives: number; trainingOnsets: number;
  };
  history: ExpansionRow[];
  metrics: Record<ExpansionWindow, {
    windowStart: string | null; windowEnd: string | null;
    expectedCalendarMonths: number; matureBenchmarkN: number; expansionN: number;
    recessionN: number; unknownPhaseN: number; incompleteHorizonN: number; missingBenchmarkMonths: number; missingCandidateMonths: number;
    n: number; positiveWindows: number; distinctOnsets: number;
    models: Record<ExpansionMethod, Scores>;
  }>;
  gate: Gate;
  warnings: {
    threshold: number;
    windows: Record<ExpansionWindow, {
      quietExpansionN: number; preOnsetN: number; completeEpisodes: number; partialEpisodes: number;
      episodes: ExpansionEpisode[];
      summary: Record<Pair, WarningSlice['summary']['candidate']>;
      expansionAtBothDates?: {n:number;recessionSignalMonths:number;unknownSignalMonths:number;benchmark:Maybe;candidate:Maybe};
      outcomeScores: Record<'quiet' | 'preOnset', {n:number; benchmark:{meanRisk:Maybe;brier:Maybe}; candidate:{meanRisk:Maybe;brier:Maybe}}>;
      comparison: WarningSlice['comparison'];
      alertChanges: { quietRemoved: number; quietAdded: number; preOnsetRemoved: number; preOnsetAdded: number };
    }>;
    gate: Gate; jointGate: Gate;
  };
  prospective?: {
    receiptCount: number; maturedCount: number; excludedCount: number; pendingCount: number;
    latestReceipt: { issueDate: string; predictions: Record<ExpansionMethod, number> } | null;
    metrics?: Partial<Record<ExpansionMethod, Scores | null>>;
  };
};
