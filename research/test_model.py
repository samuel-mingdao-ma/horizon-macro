"""Substantive model invariants: horizon alignment, purge, scoring and metrics."""
import importlib.util
import json
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('engine',ROOT/'research'/'build_model.py')
engine=importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

class ModelTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.snapshot=json.loads((ROOT/'data'/'snapshot.json').read_text())
  cls.panel=pd.read_csv(ROOT/'public'/'data'/'panel.csv',index_col=0,parse_dates=True)
  cls.pred=pd.read_csv(ROOT/'public'/'data'/'predictions.csv',index_col=0,parse_dates=True)
 def test_target_is_next_twelve_calendar_months(self):
  rec=pd.read_csv(ROOT/'research'/'raw'/'USREC.csv',index_col=0,parse_dates=True).USREC
  for date in [pd.Timestamp('1990-01-01'),pd.Timestamp('2000-07-01'),pd.Timestamp('2019-06-01'),pd.Timestamp('2024-01-01')]:
   expected=rec.loc[date+pd.DateOffset(months=1):date+pd.DateOffset(months=12)]
   self.assertEqual(len(expected),12)
   self.assertEqual(self.panel.loc[date,'target'],expected.max())
 def test_future_labels_remain_unavailable(self):
  self.assertTrue(self.pred.loc[self.pred.index>self.snapshot['metrics']['end'],'target'].isna().all())
 def test_train_targets_end_before_each_refit(self):
  for fold in self.snapshot['folds']:
   refit=pd.Timestamp(fold['refit'])
   last_target=pd.Timestamp(fold['trainEnd'])+pd.DateOffset(months=12)
   self.assertLess(last_target,refit)
   self.assertEqual(last_target,pd.Timestamp(fold['lastTargetMonth']))
 def test_two_month_feature_alignment(self):
  gs=pd.read_csv(ROOT/'research'/'raw'/'GS10.csv',index_col=0,parse_dates=True).GS10
  tb=pd.read_csv(ROOT/'research'/'raw'/'TB3MS.csv',index_col=0,parse_dates=True).TB3MS
  for issue in pd.to_datetime(['1990-01-01','2007-09-01','2020-04-01','2026-11-01']):
   if issue not in self.panel.index:continue
   feature=issue-pd.DateOffset(months=2)
   self.assertAlmostEqual(self.panel.loc[issue,'slope'],gs.loc[feature]-tb.loc[feature],places=7)
 def test_production_standardization_fitted_only_to_training(self):
  model=self.snapshot['model']
  train=self.panel.loc[model['trainedFrom']:model['trainedThrough']].dropna(subset=['slope','credit','labor','target'])
  self.assertEqual(len(train),model['trainingN'])
  np.testing.assert_allclose(train[engine.FEATURES].mean(),model['means'],atol=1e-8)
  np.testing.assert_allclose(train[engine.FEATURES].std(ddof=0),model['scales'],atol=1e-8)
 def test_raw_standardized_and_contribution_scoring_agree(self):
  model=self.snapshot['model'];latest=self.snapshot['latest']
  features=np.array([latest['features'][f] for f in model['featureOrder']])
  standardized=((features-np.array(model['means']))/np.array(model['scales']))@np.array(model['coefficients'])+model['intercept']
  raw=features@np.array(model['rawCoefficients'])+model['rawIntercept']
  contributions=sum(c['logOdds'] for c in latest['contributions'])+latest['modelIntercept']
  self.assertAlmostEqual(standardized,raw,places=9)
  self.assertAlmostEqual(standardized,contributions,places=9)
  self.assertAlmostEqual(float(engine.sigmoid(raw)),latest['probability'],places=9)
 def test_reported_metrics_recompute_from_download(self):
  mature=self.pred.dropna(subset=['target'])
  self.assertEqual(len(mature),self.snapshot['metrics']['n'])
  for label,column in [('model','probability'),('curveOnly','curveProbability'),('baseRate','baseline')]:
   recalculated=engine.metrics(mature.target,mature[column])
   for metric in ['brier','auc','logLoss']:
    self.assertAlmostEqual(recalculated[metric],self.snapshot['metrics'][label][metric],places=7)
 def test_credit_monthly_mean_matches_source(self):
  values=pd.read_csv(ROOT/'research'/'raw'/'NFCICREDIT.csv',index_col=0,parse_dates=True).NFCICREDIT
  feature=pd.Timestamp(self.snapshot['latest']['featureDate'])
  monthly=values.loc[(values.index>=feature)&(values.index<feature+pd.DateOffset(months=1))].mean()
  self.assertAlmostEqual(monthly,self.snapshot['latest']['features']['credit'],places=10)
 def test_exploratory_blend_is_unselected_equal_weight_diagnostic(self):
  history=self.snapshot['history']
  for row in history:
   self.assertAlmostEqual(row['blendProbability'],.5*row['probability']+.5*row['baseline'],places=10)
  expected=.5*self.pred.probability+.5*self.pred.baseline
  np.testing.assert_allclose(self.pred.blendProbability,expected,atol=1e-8)
  mature=self.pred.dropna(subset=['target'])
  result=engine.metrics(mature.target,mature.blendProbability)
  stored=self.snapshot['metrics']['exploratoryBlend']
  self.assertEqual(stored['status'],'post-hoc exploratory')
  self.assertEqual(stored['n'],self.snapshot['metrics']['n'])
  for key in ['auc','brier','logLoss']:
   self.assertAlmostEqual(result[key],stored[key],places=7)
 def test_newton_solution_has_small_penalized_gradient(self):
  model=self.snapshot['model']
  train=self.panel.loc[model['trainedFrom']:model['trainedThrough']].dropna(subset=engine.FEATURES+['target'])
  design=np.column_stack([np.ones(len(train)),(train[engine.FEATURES].to_numpy()-model['means'])/model['scales']])
  beta=np.r_[model['intercept'],model['coefficients']]
  gradient=design.T@(engine.sigmoid(design@beta)-train.target.to_numpy())+np.r_[0,np.array(model['coefficients'])*model['penalty']]
  self.assertLess(np.max(np.abs(gradient)),1e-5)
 def test_missing_unemployment_month_not_filled(self):
  rate=pd.read_csv(ROOT/'research'/'raw'/'UNRATE.csv',index_col=0,parse_dates=True).UNRATE
  if pd.Timestamp('2025-10-01') in rate.index and pd.isna(rate.loc['2025-10-01']):
   # October's three-calendar-month mean uses Aug+Sep, preserving the missing raw observation.
   smoothed=rate.rolling(3,min_periods=2).mean()
   expected=(rate.loc['2025-08-01']+rate.loc['2025-09-01'])/2
   self.assertAlmostEqual(smoothed.loc['2025-10-01'],expected)

if __name__=='__main__':unittest.main(verbosity=2)
