"""Checks for the single exploratory interaction specification and its audit outputs."""
import importlib.util
import json
from pathlib import Path
import unittest
import numpy as np
import pandas as pd
from innovation import add_interaction, confirmation, CHALLENGER_FEATURES, CASE_WINDOWS

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('innovation_test_engine',ROOT/'research'/'build_model.py')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)

class InnovationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.snapshot=json.loads((ROOT/'data'/'snapshot.json').read_text())
  cls.innovation=cls.snapshot['innovation']
  cls.panel=add_interaction(pd.read_csv(ROOT/'public'/'data'/'panel.csv',index_col=0,parse_dates=True))
  cls.audit=pd.read_csv(ROOT/'public'/'data'/'alarm-audit.csv',parse_dates=['date','featureDate'])
 def test_one_fixed_signed_interaction(self):
  inputs=pd.DataFrame({'slope':[-2.,-2.,1.,0.], 'credit':[-.5,.5,2.,-.3], 'labor':[0.,0.,0.,0.]})
  np.testing.assert_array_equal(add_interaction(inputs).interaction.to_numpy(),[-1.,1.,0.,0.])
  self.assertEqual(self.innovation['model']['featureOrder'],CHALLENGER_FEATURES)
  self.assertEqual(self.innovation['model']['penalty'],1.)
  self.assertIn('post-hoc',self.innovation['status'])
 def test_training_purge_and_fold_specific_scaling(self):
  for fold in self.innovation['folds']:
   refit=pd.Timestamp(fold['refit'])
   train=self.panel.loc[fold['trainStart']:fold['trainEnd']].dropna(subset=CHALLENGER_FEATURES+['target'])
   self.assertEqual(len(train),fold['n'])
   self.assertLess(train.index[-1]+pd.DateOffset(months=12),refit)
   self.assertEqual((refit-pd.Timestamp(fold['trainEnd'])).days>=365,True)
   np.testing.assert_allclose(train[CHALLENGER_FEATURES].mean(),fold['means'],atol=1e-8)
   np.testing.assert_allclose(train[CHALLENGER_FEATURES].std(ddof=0),fold['scales'],atol=1e-8)
 def test_current_parameters_and_headline_separation(self):
  candidate=self.innovation['model']; latest=self.innovation['latest']
  self.assertEqual(latest['originalProbability'],self.snapshot['latest']['probability'])
  values=np.array([latest['features'][key] for key in CHALLENGER_FEATURES])
  raw=values@candidate['rawCoefficients']+candidate['rawIntercept']
  standardized=((values-candidate['means'])/candidate['scales'])@candidate['coefficients']+candidate['intercept']
  self.assertAlmostEqual(raw,standardized,places=8)
  self.assertAlmostEqual(float(engine.sigmoid(raw)),latest['probability'],places=9)
  self.assertAlmostEqual(values[-1],max(-values[0],0)*values[1],places=10)
 def test_csv_and_history_recompute_same_clock_metrics(self):
  self.assertEqual(len(self.audit),len(self.innovation['history']))
  mature=self.audit.dropna(subset=['target'])
  evaluation=self.innovation['metrics']
  self.assertEqual(len(mature),evaluation['n'])
  self.assertEqual(evaluation['n'],self.snapshot['metrics']['n'])
  self.assertEqual(mature.date.iloc[0].strftime('%Y-%m-%d'),evaluation['start'])
  self.assertEqual(mature.date.iloc[-1].strftime('%Y-%m-%d'),evaluation['end'])
  for stored,column in [('challenger','challengerProbability'),('original','originalProbability'),('curveOnly','curveProbability'),('baseRate','baseline'),('blend','blendProbability')]:
   calculated=engine.metrics(mature.target,mature[column])
   for key in ['auc','brier','logLoss']:
    self.assertAlmostEqual(calculated[key],evaluation[stored][key],places=7)
  self.assertTrue(self.audit.loc[self.audit.date>pd.Timestamp(evaluation['end']),'target'].isna().all())
  for row in self.innovation['history']:
   self.assertAlmostEqual(row['blendProbability'],.5*row['originalProbability']+.5*row['baseline'],places=10)
   self.assertEqual(row['featureDate'],(pd.Timestamp(row['date'])-pd.DateOffset(months=2)).strftime('%Y-%m-%d'))
   self.assertEqual(row['forecastType'],'annual-walk-forward')
 def test_cases_are_fixed_subsets_and_claims_derived_from_rows(self):
  for case,expected in zip(self.innovation['cases'],CASE_WINDOWS):
   key,title,start,end=expected
   self.assertEqual(case['id'],key);self.assertEqual(case['start'],start);self.assertEqual(case['end'],end)
   rows=[r for r in self.innovation['history'] if start<=r['date']<=end]
   self.assertEqual(case['history'],rows)
   known=[r for r in rows if r['target'] is not None]
   self.assertEqual(case['summary']['positiveWindows'],sum(r['target'] for r in known))
   for label,column in [('peakOriginal','originalProbability'),('peakCurve','curveProbability'),('peakChallenger','challengerProbability')]:
    peak=max(rows,key=lambda r:r[column])
    self.assertEqual(case['summary'][label]['date'],peak['date'])
    self.assertEqual(case['summary'][label]['probability'],peak[column])
    self.assertEqual(case['summary'][label]['target'],peak['target'])
 def test_confirmation_is_policy_with_strict_credit_and_inclusive_labor(self):
  self.assertFalse(confirmation({'credit':0.,'labor':.4999}))
  self.assertTrue(confirmation({'credit':0.,'labor':.5}))
  self.assertTrue(confirmation({'credit':.00001,'labor':0.}))
  self.assertFalse(confirmation({'credit':-.1,'labor':0.}))
  for row in self.innovation['history']:
   self.assertEqual(row['confirmation'],row['credit']>0 or row['labor']>=.5)
 def test_regime_counts_partition_mature_sample(self):
  mature=self.audit.dropna(subset=['target']);regimes=self.innovation['regimes']
  self.assertEqual(sum(r['n'] for r in regimes),len(mature))
  self.assertEqual(sum(r['positiveWindows'] for r in regimes),int(mature.target.sum()))
  for regime in regimes:
   group=mature.loc[((mature.slope<0)==regime['inverted'])&((mature.credit>0)==regime['creditTight'])]
   self.assertEqual(regime['n'],len(group))
   if len(group):self.assertAlmostEqual(regime['observedRate'],group.target.mean(),places=10)
 def test_surface_is_conditional_fixed_labor_with_training_support(self):
  surface=self.innovation['surface'];model=self.innovation['model']
  self.assertEqual(len(surface['points']),25*25)
  train=pd.DataFrame(surface['trainingPoints'])
  for cell in [surface['points'][0],surface['points'][312],surface['points'][-1]]:
   inputs=np.array([cell['slope'],cell['credit'],surface['fixedLabor'],max(-cell['slope'],0)*cell['credit']])
   expected=float(engine.sigmoid(inputs@model['rawCoefficients']+model['rawIntercept']))
   self.assertAlmostEqual(cell['probability'],expected,places=9)
   distance2=((train.slope-cell['slope'])/train.slope.std(ddof=0))**2+((train.credit-cell['credit'])/train.credit.std(ddof=0))**2
   self.assertEqual(cell['supportN'],int((distance2<=surface['supportRadiusStd']**2).sum()))

if __name__=='__main__':unittest.main(verbosity=2)
