#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 research/build_model.py --refresh "$@"
python3 research/forecast_ledger.py
python3 research/rate_path_ledger.py
python3 research/test_model.py
python3 research/test_innovation.py
python3 research/test_provider_fallback.py
python3 research/test_forecast_ledger.py
python3 research/test_rate_path.py
python3 research/test_rate_path_ledger.py
node --test scripts/*.test.mjs
