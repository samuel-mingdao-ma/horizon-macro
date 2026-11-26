export type FrozenLedgerModel = {
  featureOrder: string[]; means: number[]; scales: number[]; coefficients: number[]; intercept: number;
  rawCoefficients?: number[]; rawIntercept?: number; penalty?: number;
  trainedFrom?: string; trainedThrough?: string; lastTargetMonth?: string; trainingN?: number; refitDate?: string;
};
export type ReceiptPredictions = { baseline: number; challenger: number; historicalBase: number; blend: number };
export type ForecastReceipt = {
  protocolVersion: 'horizon-prospective-v1'; recordedAt: string; issueDate: string;
  forecastStart: string; forecastEnd: string; featureDate: string; sourceBuildGeneratedAt: string;
  features: { baseline: Record<string, number>; challenger: Record<string, number> };
  models: { baseline: FrozenLedgerModel; challenger: FrozenLedgerModel };
  predictions: ReceiptPredictions;
  sources: { id: string; lastDate: string; retrievedAt: string | null; transportStatus: string | null;
    providerRetrievedAt: string | null; verifiedProviderLastDate: string | null }[];
  codeCommit: string | null; codeSha256: Record<string, string>; protocolHash: string; recipeHash: string; recipe: Record<string, unknown>;
  modelHashes: { baseline: string; challenger: string }; previousHash: string | null; hash: string;
};
export type ForecastOutcome = {
  receiptHash: string; issueDate: string; status: 'pending' | 'matured'; knownMonths: number; requiredMonths: 12;
  target: 0 | 1 | null; sourceLastDate: string | null; sourceRetrievedAt: string | null; evaluatedAt: string;
};
export type ProspectiveMetrics = Record<keyof ReceiptPredictions, { n: number; brier: number; logLoss: number } | null>;
export type ProspectiveSummary = {
  protocolVersion: 'horizon-prospective-v1'; protocolRegisteredAt: string; receiptCount: number; maturedCount: number;
  chainValid: boolean; lastHash: string | null; latestReceipt: ForecastReceipt | null;
  receipts: ForecastReceipt[]; outcomes: ForecastOutcome[]; metrics: ProspectiveMetrics;
  appendedThisRun: boolean; evaluatedAt: string; downloadUrl: string; note: string;
};
