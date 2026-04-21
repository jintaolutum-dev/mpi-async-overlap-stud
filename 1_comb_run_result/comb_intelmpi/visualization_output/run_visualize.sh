#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

cd "${ROOT_DIR}"

if command -v module >/dev/null 2>&1; then
  module load python/3.10.12-base
fi

exec python3 visualize_comb_results.py