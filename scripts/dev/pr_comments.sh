#!/bin/bash
# Fetch PR review comments and reviews using GitHub CLI
# Usage: ./pr_comments.sh <pr-number>
# Requires: gh CLI (https://cli.github.com/), authenticated
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <pr-number>" >&2
  exit 1
fi

# Always operate from the repo root
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

PR="$1"
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OUTDIR="docs/reviews"

mkdir -p "$OUTDIR"

echo "Fetching PR discussion comments..."
gh pr view "$PR" --json comments > "$OUTDIR/pr_${PR}_discussion.json"

echo "Fetching PR reviews..."
gh pr view "$PR" --json reviews > "$OUTDIR/pr_${PR}_reviews.json"

echo "Fetching PR inline comments..."
gh api "repos/$REPO/pulls/$PR/comments" > "$OUTDIR/pr_${PR}_inline.json"

echo "Done. Results in $OUTDIR/"