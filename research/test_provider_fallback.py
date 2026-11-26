"""Offline provider and future-clock regressions; synthetic dates are test fixtures only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'research'))
import provider_fallback as providers

class ProviderFallbackTests(unittest.TestCase):
 def test_fred_md_excludes_transform_codes_and_preserves_level_values(self):
  header='sasdate,'+','.join(providers.MD_SERIES)+'\n'
  codes='Transform:,'+','.join(['2']*len(providers.MD_SERIES))+'\n'
  first='09/01/2026,4.99,3.94,4.2,336.298,3.75,4.37,4.80\n'
  second='10/01/2026,5.13,4.05,,337.476,3.88,4.46,4.93\n'
  result=providers.parse_md_csv(header+codes+first+second)
  self.assertEqual(list(result),providers.MD_SERIES)
  self.assertEqual(len(result['GS10']),2)
  self.assertEqual(result['GS10'].iloc[0],4.99)
  self.assertEqual(result['CPIAUCSL'].iloc[1],337.476)
  self.assertTrue(pd.isna(result['UNRATE'].iloc[1]))
 def test_credit_parser_uses_credit_not_composite_or_renormalization(self):
  text='Friday_of_Week,NFCI,Credit\n11/13/2026,-0.450,-0.008\n11/20/2026,-0.444,-0.010\n'
  result=providers.parse_chicago_credit(text)
  self.assertEqual(result.name,'NFCICREDIT')
  self.assertAlmostEqual(result.loc['2026-11-20'],-.010)
  self.assertEqual(result.index[-1],pd.Timestamp('2026-11-20'))
 def test_merge_retains_later_cached_dates_and_explicit_provider_missing(self):
  cached=pd.Series([1.,2.,3.],index=pd.date_range('2026-08-01',periods=3,freq='MS'))
  fetched=pd.Series([1.5,np.nan],index=pd.date_range('2026-08-01',periods=2,freq='MS'))
  merged=providers.merge_observations(cached,fetched,'UNRATE')
  self.assertEqual(merged.loc['2026-08-01'],1.5)
  self.assertTrue(pd.isna(merged.loc['2026-09-01']))
  self.assertEqual(merged.loc['2026-10-01'],3.)
  self.assertEqual(len(merged),3)
 def test_cached_target_provenance_is_not_refreshed_or_extended(self):
  dates=pd.date_range('2026-09-01',periods=2,freq='MS')
  cached={key:pd.Series([1.,2.],index=dates,name=key) for key in ['GS10','TB3MS','UNRATE','USREC','GS2','GS30']}
  cached['NFCICREDIT']=pd.Series([-.01],index=pd.to_datetime(['2026-11-20']),name='NFCICREDIT')
  fetched={key:pd.Series([1.5],index=pd.to_datetime(['2026-09-01']),name=key) for key in providers.CORE}
  original={key:{'sourceRetrievedAt':'2026-11-25T00:00:00Z'} for key in cached}
  urls={key:'https://official.example.test/data.csv' for key in fetched}
  with patch.object(providers,'fetch_official_sources',return_value=(fetched,urls)):
   output,meta=providers.fallback_dataset(cached,original,checked_at='2027-03-01T00:00:00Z')
  pd.testing.assert_series_equal(output['USREC'],cached['USREC'])
  target=meta['perSeries']['USREC']
  self.assertFalse(target['refreshed'])
  self.assertTrue(target['latestObservationFromCache'])
  self.assertEqual(target['mode'],'dated-cache')
  self.assertEqual(target['lastDate'],'2026-10-01')
  self.assertEqual(target['sourceRetrievedAt'],'2026-11-25T00:00:00Z')
  self.assertIsNone(target['providerRetrievedAt'])
  core=meta['perSeries']['GS10']
  self.assertTrue(core['refreshed'])
  self.assertTrue(core['latestObservationFromCache'])
  self.assertEqual(core['verifiedProviderLastDate'],'2026-09-01')
  self.assertEqual(core['sourceRetrievedAt'],'2026-11-25T00:00:00Z')
  self.assertEqual(core['providerRetrievedAt'],'2027-03-01T00:00:00Z')
 def test_missing_official_provider_fails_closed_instead_of_calling_cache_fresh(self):
  header='sasdate,'+','.join(providers.MD_SERIES)+'\n'
  md=header+'Transform:,'+','.join(['2']*len(providers.MD_SERIES))+'\n09/01/2026,4.99,3.94,4.2,336.298,3.75,4.37,4.80\n'
  chicago='Friday_of_Week,Credit\n11/20/2026,-0.010\n'
  page='<a href="/-/media/project/frbstl/stlouisfed/research/fred-md/monthly/2026-10-md.csv">current.csv</a>'
  class Response:
   def __init__(self,text):self.text=text
   def raise_for_status(self):pass
  for failing_provider in ['md','credit']:
   with self.subTest(provider=failing_provider):
    def get(url,**kwargs):
     if failing_provider=='md' and url==providers.FRED_MD_PAGE:raise OSError('fixture network failure')
     if failing_provider=='credit' and url==providers.CHICAGO_CREDIT_CSV:raise OSError('fixture network failure')
     return Response(page if url==providers.FRED_MD_PAGE else chicago if url==providers.CHICAGO_CREDIT_CSV else md)
    with self.assertRaises(OSError):
     providers.fallback_dataset({}, {}, get=get, checked_at='2027-03-01T00:00:00Z')
 def test_future_features_advance_without_inventing_recession_labels(self):
  # Use a temporary copy so fixture observations never touch public research data.
  spec=importlib.util.spec_from_file_location('future_fixture_engine',ROOT/'research'/'build_model.py')
  engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
  baseline=json.loads((ROOT/'data'/'snapshot.json').read_text())
  target_raw=pd.read_csv(ROOT/'research'/'raw'/'USREC.csv',index_col=0,parse_dates=True).USREC.dropna()
  target_last=target_raw.index[-1]
  asof=target_last+pd.DateOffset(months=7)
  feature_last=asof-pd.DateOffset(months=2)
  with tempfile.TemporaryDirectory(prefix='horizon-provider-audit-') as folder:
   temp=Path(folder)
   shutil.copytree(ROOT/'research'/'raw',temp/'research'/'raw')
   (temp/'data').mkdir();(temp/'public'/'data').mkdir(parents=True)
   (temp/'data'/'snapshot.json').write_text(json.dumps(baseline))
   for series_id in ['GS10','TB3MS','UNRATE']:
    path=temp/'research'/'raw'/f'{series_id}.csv'
    frame=pd.read_csv(path,index_col=0,parse_dates=True)
    extra_dates=pd.date_range(frame.index[-1]+pd.offsets.MonthBegin(1),feature_last,freq='MS')
    extra=pd.DataFrame({series_id:[frame[series_id].dropna().iloc[-1]]*len(extra_dates)},index=extra_dates)
    frame=pd.concat([frame,extra]);frame.index.name='observation_date';frame.to_csv(path)
   path=temp/'research'/'raw'/'NFCICREDIT.csv'
   frame=pd.read_csv(path,index_col=0,parse_dates=True)
   end=feature_last+pd.offsets.MonthEnd(0)
   extra_dates=pd.date_range(frame.index[-1]+pd.Timedelta(days=7),end,freq='W-FRI')
   extra=pd.DataFrame({'NFCICREDIT':[frame.NFCICREDIT.dropna().iloc[-1]]*len(extra_dates)},index=extra_dates)
   frame=pd.concat([frame,extra]);frame.index.name='observation_date';frame.to_csv(path)
   # Simulate a lagging optional tenor so this regression actually separates
   # the Treasury observation cutoff from the latest published USREC month.
   slow_path=temp/'research'/'raw'/'GS30.csv'
   slow=pd.read_csv(slow_path,index_col=0,parse_dates=True)
   slow=slow.loc[slow.index<target_last]
   slow.index.name='observation_date';slow.to_csv(slow_path)
   # Treasury and USREC releases can have different cutoffs. Compute the
   # common available Treasury month independently of the outcome-label date.
   curve_months=None
   for series_id in ['TB3MS','GS1','GS2','GS5','GS10','GS30']:
    values=pd.read_csv(temp/'research'/'raw'/f'{series_id}.csv',index_col=0,parse_dates=True)[series_id].dropna()
    available=set(values.index[values.index<asof.to_period('M').to_timestamp()])
    curve_months=available if curve_months is None else curve_months & available
   expected_curve_date=max(curve_months).strftime('%Y-%m-%d')
   self.assertLess(pd.Timestamp(expected_curve_date),target_last)
   engine.ROOT=temp;engine.RAW=temp/'research'/'raw'
   with patch.object(sys,'argv',['build_model.py','--offline','--as-of',asof.strftime('%Y-%m-%d')]),contextlib.redirect_stdout(io.StringIO()):
    engine.main()
   result=json.loads((temp/'data'/'snapshot.json').read_text())
   predictions=pd.read_csv(temp/'public'/'data'/'predictions.csv',index_col=0,parse_dates=True)
   self.assertEqual(result['latest']['issueDate'],asof.strftime('%Y-%m-%d'))
   self.assertEqual(result['latest']['featureDate'],feature_last.strftime('%Y-%m-%d'))
   expected_last_issue=target_last-pd.DateOffset(months=12)
   self.assertEqual(result['metrics']['end'],expected_last_issue.strftime('%Y-%m-%d'))
   self.assertTrue(predictions.loc[predictions.index>expected_last_issue,'target'].isna().all())
   target_source=next(source for source in result['sources'] if source['id']=='USREC')
   self.assertEqual(target_source['lastDate'],target_last.strftime('%Y-%m-%d'))
   curve_dates={row['date'] for row in result['yieldCurve']}
   self.assertEqual(len(curve_dates),1)
   self.assertEqual(next(iter(curve_dates)),expected_curve_date)

if __name__=='__main__':unittest.main(verbosity=2)
