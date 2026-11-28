export type JointPeriod = 'all' | 'rolling120';
export type JointRadius = '0' | '3' | '5';
export type JointBounds = [number | null, number | null];
export type JointFlags = [boolean | null, boolean | null];

export type JointWitness = {
  shocksBp: [number, number][];
  path: (number | null)[];
  probability: number | null;
  change1m: number | null;
  change3m: number | null;
  shortChangeBp: number | null;
  longChangeBp: number | null;
  levelAlert: boolean | null;
  quarterAlert: boolean | null;
  referenceAlert: boolean | null;
};

export type JointReading = {
  probability: JointBounds;
  change1m: JointBounds;
  change3m: JointBounds;
  level: JointFlags;
  alert: JointFlags;
  extra: JointFlags;
  certified: boolean;
  witnesses?: Record<'on' | 'off' | 'extra' | 'steepener', JointWitness | null>;
};

export type JointIssue = {
  date?: string;
  issueDate?: string;
  featureDate: string;
  refitDate: string;
  probability: number | null;
  change1m: number | null;
  change3m: number | null;
  levelAlert: boolean | null;
  referenceAlert: boolean | null;
  radii: Record<JointRadius, JointReading>;
};

export type JointWindowResult = {
  brier: JointBounds;
  logLoss: JointBounds;
  coherentBrier: JointBounds;
  coherentLogLoss: JointBounds;
  levelQuiet: JointBounds;
  alertQuiet: JointBounds;
  extraQuiet: JointBounds;
  extraQuietDates: string[];
  unresolvedN: number;
  episodes: {
    onsetDate: string;
    coverage: string;
    originalLevelLead: number | null;
    levelLead: JointBounds;
    alertLead: JointBounds;
  }[];
};

export type JointWindow = {
  windowStart: string | null;
  windowEnd: string | null;
  n: number;
  quietExpansionN: number;
  preOnsetN: number;
  originalQuiet: number;
  originalBrier: number | null;
  originalLogLoss: number | null;
  radii: Record<JointRadius, JointWindowResult>;
};

export type JointCalendarPath = {
  id: string;
  date: string;
  radiusBp: number;
  shocks: {date: string; shortBp: number; longBp: number}[];
  caseRisk: number | null;
  caseLevelAlert: boolean | null;
  caseAlert: boolean | null;
  lead2001: number | null;
  windows: Record<JointPeriod, {levelQuiet: number; alertQuiet: number; brier: number | null; logLoss: number | null}>;
};

export type JointStressTrial = {
  calendarPaths?: Partial<Record<'february2019' | 'may2000', JointCalendarPath | null>>;
  cases: Record<string, JointIssue | null>;
  latest: JointIssue & {
    issueDate: string;
    forecastStart: string;
    forecastEnd: string;
    available: boolean;
    reason: string | null;
  };
  history: JointIssue[];
  windows: Record<JointPeriod, JointWindow>;
};
