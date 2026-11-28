export type SimulationPeriod = 'all' | 'rolling120';
export type Quantiles = [number, number, number];
export type PassRate = {passed: number; n: number; rate: number; interval: [number, number]};
export type CalendarShift = {date: string; shortBp: number; longBp: number};

export type SimulatedWindow = {
  brier: Quantiles;
  logLoss: Quantiles;
  brierDelta: Quantiles;
  logLossDelta: Quantiles;
  levelQuiet: Quantiles;
  ruleQuiet: Quantiles;
  extraQuiet: Quantiles;
};
export type SimulationBaseline = {
  n: number; quietN: number; windowStart: string; windowEnd: string; brier: number; logLoss: number; quietAlerts: number
};
type ExampleScore = {brier: number; logLoss: number; levelQuiet: number; ruleQuiet: number};
export type SimulationExample = {
  draw: number;
  passed: boolean;
  lead2001: number | null;
  levelLead2001: number | null;
  mayAlert: boolean;
  febAlert: boolean;
  all: ExampleScore;
  rolling120: ExampleScore;
  mayPath: CalendarShift[];
  febPath: CalendarShift[];
};

export type SimulationScenario = {
  id: string;
  label: string;
  capBp: number | null;
  blockMonths: number;
  draws: number;
  gates: Record<string,PassRate>;
  windows: Record<SimulationPeriod,SimulatedWindow>;
  funnel: {gate: string; count: number}[];
  examples: SimulationExample[];
  latest: {probability: Quantiles; change3m: Quantiles; warning: PassRate} | null;
  leadHistogram: {lead: number | null; count: number}[];
};

export type CalibrationStats = {
  cutoff: string; start: string | null; end: string | null; n: number;
  shortMedianAbsBp: number | null; longMedianAbsBp: number | null;
  shortSdBp: number | null; longSdBp: number | null;
  shortMeanBp: number | null; longMeanBp: number | null;
  shortP90AbsBp: number | null; longP90AbsBp: number | null;
  correlation: number | null; shortLag1: number | null; longLag1: number | null;
  within3: number | null; within5: number | null;
};

export type PathSimulationTrial = {
  spec: {id: string; seed: number; draws: number; primary: string};
  baseline: Record<SimulationPeriod,SimulationBaseline> & {levelLead2001: number | null; ruleLead2001: number | null};
  scenarios: SimulationScenario[];
  latest: {issueDate: string; featureDate: string; forecastStart: string; forecastEnd: string; probability: number | null; available: boolean; refitDate: string};
  calibration: Record<'first'|'may2000'|'latest',CalibrationStats> & {
    source: {mode: string; series: string[]; urls: string[]; dailyStart: string; dailyEnd: string; pairedDays: number; donorStart: string; donorEnd: string; donorMonths: number; method: string};
  };
};
