#!/usr/bin/env bash
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Lists open Dependabot alerts for this repo on GitHub Enterprise.
# Empty output means all open alerts have cleared.
set -euo pipefail

REPO="boozallen/foundry-agent-packages"
HOSTNAME="github.com"

gh api --hostname "${HOSTNAME}" \
  "/repos/${REPO}/dependabot/alerts?state=open" \
  --paginate | jq -r '.[] | "\(.number)\t\(.dependency.package.name)"'
