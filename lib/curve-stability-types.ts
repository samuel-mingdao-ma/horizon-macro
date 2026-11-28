type Maybe = number | null;
type Flag = boolean | null;
export type StabilityPeriod = 'all' | 'rolling120';

export type StabilityResult = {
  actual: Flag; guaranteed: Flag; possible: Flag; minus3: Flag; plus3: Flag;
  lowerBp: Maybe; upperBp: Maybe; upperInclusive: boolean | null;
};
export type StabilityReading = {
  featureDate: string; lagFeatureDate: string; probability: Maybe;
  shortChange: Maybe; longChange: Maybe; levelAlert: Flag; quarterAlert: Flag; mixedTwoToOneAlert: Flag;
};
export type StabilityRow = StabilityReading & {
  date: string; commonMature: boolean; issuePhase: string | null; target: Maybe; onsetDate: string | null;
};
type Episode = {
  onsetDate: string; coverage: 'full' | 'partial' | 'unavailable'; availableMonths: number;
  levelLead: Maybe; levelFirstDate: string | null;
};
type Window = {
  windowStart: string | null; windowEnd: string | null; n: number; quietExpansionN: number; preOnsetN: number;
  levelQuiet: number; levelPre: number; levelHits: number; completeEpisodes: number; episodes: Episode[];
  probabilityScores: {brier: Maybe; logLoss: Maybe; auc: Maybe};
};
type CellWindow = {
  actualQuietDates: string[]; possibleQuietDates: string[]; guaranteedQuietDates: string[];
  actualPreDates: string[]; possiblePreDates: string[]; guaranteedPreDates: string[];
  episodes: {onsetDate: string; actualLead: Maybe; guaranteedLead: Maybe; possibleLead: Maybe;
    actualFirstDate: string | null; guaranteedFirstDate: string | null; possibleFirstDate: string | null}[];
};
export type StabilityCell = {
  id: string; bandBp: number; ratio: number; pointPassed: boolean; stressPassed: boolean;
  cases: Record<string,StabilityResult | null>; windows: Record<StabilityPeriod,CellWindow>;
};
export type CurveStabilityTrial = {
  spec: {bandsBp: number[]; ratios: number[]; stressBp: number; referenceId: string; originalId: string};
  latest: StabilityReading & {
    issueDate: string; refitDate: string; available: boolean; reason: string | null;
    forecastStart: string; forecastEnd: string; results: Record<string,StabilityResult>;
  };
  history: StabilityRow[]; windows: Record<StabilityPeriod,Window>; cells: StabilityCell[];
  prospective?: {receiptCount: number; maturedCount: number; excludedCount: number; pendingCount: number;
    latestReceipt: {issueDate: string} | null};
};
