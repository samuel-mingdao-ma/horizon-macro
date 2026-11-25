#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 research/build_model.py --refresh "$@"
python3 research/test_model.py
node --test scripts/refresh-data.test.mjs scripts/refresh-data.bond.test.mjs
