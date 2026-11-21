#!/usr/bin/env bash
# LtBooks Ver 1.0 manual-panel installer entry point.
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/install.sh" --manual "$@"
