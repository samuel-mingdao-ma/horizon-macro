#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 research/build_model.py --refresh "$@"
python3 research/forecast_ledger.py
python3 research/rate_path_ledger.py
python3 research/regime_receipts.py
python3 research/leading_receipts.py
python3 research/weight_receipts.py
python3 research/credit_receipts.py
python3 research/expansion_receipts.py
python3 research/pace_receipts.py
python3 research/confirmation_receipts.py
python3 research/curve_legs_receipts.py
python3 research/test_model.py
python3 research/test_innovation.py
python3 research/test_provider_fallback.py
python3 research/test_forecast_ledger.py
python3 research/test_rate_path.py
python3 research/test_rate_path_ledger.py
python3 research/test_regime_prior.py
python3 research/test_regime_receipts.py
python3 research/test_leading_trial.py
python3 research/test_onset_diagnostics.py
python3 research/test_leading_receipts.py
python3 research/test_leading_feeds.py
python3 research/test_weight_trial.py
python3 research/test_weight_warning.py
python3 research/test_weight_receipts.py
python3 research/test_credit_trial.py
python3 research/test_credit_diagnostics.py
python3 research/test_credit_receipts.py
python3 research/test_expansion_trial.py
python3 research/test_expansion_receipts.py
python3 research/test_pace_trial.py
python3 research/test_pace_receipts.py
python3 research/test_confirmation_trial.py
python3 research/test_confirmation_receipts.py
python3 research/test_curve_legs.py
python3 research/test_curve_legs_receipts.py
node --test scripts/*.test.mjs
