export type InnovationFeatures = { slope: number; credit: number; labor: number; interaction: number };
export type InnovationMetrics = { auc: number | null; brier: number; logLoss: number };
export type InnovationModel = {
  featureOrder: ['slope', 'credit', 'labor', 'interaction']; means: number[]; scales: number[];
  coefficients: number[]; intercept: number; rawCoefficients: number[]; rawIntercept: number;
  penalty: number; trainedFrom: string; trainedThrough: string; lastTargetMonth: string; trainingN: number; refitDate: string;
};
export type InnovationHistoryRow = {
  date: string; featureDate: string; target: number | null; recession: number | null;
  slope: number; credit: number; labor: number; interaction: number;
  originalProbability: number; curveProbability: number; challengerProbability: number; baseline: number; blendProbability: number;
  confirmation: boolean; forecastType: 'annual-walk-forward';
};
export type InnovationCase = {
  id: '2007' | '2020' | '2023'; title: string; start: string; end: string; history: InnovationHistoryRow[];
  summary: { n: number; evaluatedN: number; positiveWindows: number; observedRate: number | null;
    meanOriginal: number; meanCurve: number; meanChallenger: number;
    peakOriginal: { date: string; probability: number; target: number | null };
    peakCurve: { date: string; probability: number; target: number | null };
    peakChallenger: { date: string; probability: number; target: number | null };
    curveAlerts: number; confirmedAlerts: number; unconfirmedAlerts: number };
};
export type InnovationSnapshot = {
  version: '1.0'; status: 'post-hoc exploratory research replay'; generatedAt: string; issueDate: string; featureDate: string;
  spec: { name: string; hypothesis: string; featureFormula: string; penalty: number; featureLagMonths: number;
    horizonMonths: number; eligibilityMonths: number; refitFrequency: string; designStatus: string;
    confirmationRule: string; defaultThreshold: number; caveats: string[] };
  model: InnovationModel;
  latest: { probability: number; originalProbability: number; curveProbability: number; baselineProbability: number; blendProbability: number;
    features: InnovationFeatures; confirmation: { state: 'confirmed' | 'unconfirmed' | 'below-threshold';
      creditTight: boolean; laborDeteriorating: boolean; curveAlarm: boolean; ruleSatisfied: boolean; threshold: number } };
  metrics: { n: number; start: string; end: string; positiveWindows: number; independentRecessions: number;
    challenger: InnovationMetrics; original: InnovationMetrics; curveOnly: InnovationMetrics; baseRate: InnovationMetrics; blend: InnovationMetrics };
  history: InnovationHistoryRow[]; cases: InnovationCase[];
  regimes: { id: string; inverted: boolean; creditTight: boolean; n: number; positiveWindows: number;
    observedRate: number | null; meanOriginal: number | null; meanChallenger: number | null }[];
  surface: { xFeature: 'slope'; yFeature: 'credit'; fixedLabor: number; gridSize: number; supportRadiusStd: number;
    supportDefinition: string; slopeValues: number[]; creditValues: number[];
    points: { slope: number; credit: number; probability: number; supportN: number }[];
    trainingPoints: { date: string; slope: number; credit: number; labor: number; target: number }[] };
  folds: { refit: string; trainStart: string; trainEnd: string; lastTargetMonth: string; n: number; means: number[]; scales: number[] }[];
};
