import type {WarningResult, WarningSlice} from './weight-types';

type Maybe = number | null;
type Flag = boolean | null;
export type CurveRule = 'shortLead' | 'bear' | 'sustained' | 'mixedTwoToOne';
export type CurveWindow = 'all' | 'rolling120';
type Policy = CurveRule | 'level' | 'quarter';
export type CurveReading = {
  featureDate: string; lagFeatureDate: string; refitDate: string;
  probability: Maybe; change3m: Maybe;
  shortStart: Maybe; shortStep1: Maybe; shortStep2: Maybe; shortEnd: Maybe;
  longStart: Maybe; longStep1: Maybe; longStep2: Maybe; longEnd: Maybe;
  shortChange: Maybe; longChange: Maybe; flattening: Maybe; startSlope: Maybe; endSlope: Maybe;
  driver: 'short-led' | 'long-led' | 'equal' | 'no-flattening' | 'unavailable';
  pattern: 'both-flatten' | 'short-only' | 'long-only' | 'long-rise-offset' | 'short-fall-offset' | 'no-flattening' | 'unavailable';
  shortRiseCount: Maybe;
  shortLead: Flag; bear: Flag; sustained: Flag;
  levelAlert: Flag; quarterAlert: Flag; shortLeadAlert: Flag; bearAlert: Flag; sustainedAlert: Flag; mixedTwoToOneAlert: Flag;
};
export type CurveRow = CurveReading & {
  date: string; commonMature: boolean; target: Maybe; onsetDate: string | null;
};
type Gate = {mayRetained: boolean; allNoAddedFalse: boolean; rolling120NoAddedFalse: boolean; maintainedHitsBoth: boolean; passed: boolean};
export type CurveLegsTrial = {
  latest: CurveReading & {
    issueDate: string; forecastStart: string; forecastEnd: string; available: boolean; reason: string | null;
    yieldPath: {date: string; shortYield: Maybe; longYield: Maybe}[];
  };
  caseEffects: Record<string, {curveEffect: number; shortEffect:number; longEffect:number} | null>;
  history: CurveRow[];
  gate: Record<CurveRule, Gate>;
  windows: Record<CurveWindow, {
    windowStart: string | null; windowEnd: string | null; n: number; completeEpisodes: number;
    quietExpansionN: number; preOnsetN: number;
    probabilityScores: {brier: Maybe; logLoss: Maybe; auc: Maybe};
    changes: Record<Exclude<Policy,'level'>, {quietDates: string[]; preOnsetDates: string[]}>;
    summary: Record<Policy, WarningSlice['summary']['candidate']>;
    episodes: {onsetDate: string; availableMonths: number; coverage: 'full' | 'partial' | 'unavailable'; methods: Record<Policy,WarningResult>}[];
  }>;
  prospective?: {receiptCount: number; maturedCount: number; excludedCount: number; pendingCount: number; latestReceipt: {issueDate: string} | null};
};
