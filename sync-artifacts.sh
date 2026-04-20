#!/bin/bash
# Sync task artifacts from filesystem to DB.
# Usage:
#   sync-artifacts.sh <project> <task-number>          — sync to DB, keep files
#   sync-artifacts.sh <project> <task-number> --clean   — sync to DB + delete text files
#
# Called by orchestrator after each pipeline stage (without --clean).
# Called after full pipeline completion (with --clean).

set -e
cd "$(dirname "$0")"

PROJECT="${1:?Usage: sync-artifacts.sh <project> <task-number> [--clean]}"
TASK_NUM="${2:?Usage: sync-artifacts.sh <project> <task-number> [--clean]}"

exec .venv/bin/python -m dashboard.db.sync_artifacts "$PROJECT" "$TASK_NUM" $3
