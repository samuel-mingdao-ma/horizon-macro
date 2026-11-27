import type { WarningResult } from './weight-types';

type Maybe = number | null;
export type CreditWindow = 'all' | 'rolling120';
export type CreditMethod = 'benchmark' | 'matchedLevel' | 'slowOnly' | 'shockOnly' | 'candidate';
export type CreditState = 'persistent' | 'sudden' | 'both' | 'neither' | 'unknown';

export type CreditSignals = {
  featureDate: string;
  credit: Maybe;
  creditSlow: Maybe;
  creditShock: Maybe;
  shockThreshold: Maybe;
  persistent: boolean | null;
  sudden: boolean | null;
  benchmarkProbability: Maybe;
  probability: Maybe;
};

type CreditMetrics = { brier: Maybe; logLoss: Maybe; auc: Maybe };
type AlertModel = 'benchmark' | 'candidate';
type Gate = { allPassed: boolean; rolling120Passed: boolean; passed: boolean };
export type CreditTrial = {
  latest: CreditSignals & {
    issueDate: string;
    forecastStart: string;
    forecastEnd: string;
    available: boolean;
    reason: string | null;
  };
  history: (CreditSignals & { date: string; issuePhase: string | null; commonMature: boolean; target: Maybe })[];
  metrics: Record<CreditWindow, {
    windowStart: string | null;
    windowEnd: string | null;
    n: number;
    positiveWindows: number;
    missingCandidateMonths: number;
    models: Record<CreditMethod, CreditMetrics>;
  }>;
  gate: Gate;
  warnings: {
    threshold: number;
    gate: Gate;
    jointGate: Gate;
    windows: Record<CreditWindow, {
      n: number;
      quietExpansionN: number;
      completeEpisodes: number;
      partialEpisodes: number;
      summary: Record<AlertModel, {
        quietAlerts: number;
        quietRate: Maybe;
        meanLeadMonths: Maybe;
        completeHits: number;
      }>;
      alertChanges: { quietRemoved: number; quietAdded: number; preOnsetRemoved: number; preOnsetAdded: number };
      comparison: { earlier: number; tied: number; later: number; sufficient: boolean; baselineAtCeiling: boolean };
      episodes: {
        onsetDate: string;
        coverage: 'full' | 'partial' | 'unavailable';
        availableMonths: number;
        methods: Record<AlertModel, WarningResult>;
      }[];
    }>;
    buckets: Record<CreditWindow, {
      state: CreditState;
      n: number;
      positives: number;
      preOnsetN: number;
      recessionIssuedPositiveN: number;
      quietN: number;
      benchmarkQuietAlerts: number;
      candidateQuietAlerts: number;
      benchmarkMean: Maybe;
      candidateMean: Maybe;
      observedRate: Maybe;
    }[]>;
  };
  prospective?: {
    receiptCount: number;
    maturedCount: number;
    latestReceipt: { issueDate: string; predictions: Record<CreditMethod, number> } | null;
    metrics?: Partial<Record<CreditMethod, CreditMetrics | null>>;
  };
};
