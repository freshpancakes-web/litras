#!/bin/bash
# Asks GitHub to refresh prices.js, waits for the result, and pulls it into this folder.
# Run by the launchd job installed with schedule_prices.sh. Safe to run by hand.
# It never discards anything except local changes to prices.js (a generated file),
# and it only touches the checkout when it is on the main branch.
#
# Test overrides: FC_GH (path to gh), FC_WAIT_ROUNDS (default 6), FC_WAIT_SECONDS (default 30).

# launchd gives a minimal PATH.
PATH="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export PATH

DIR="$(cd "$(dirname "$0")" && pwd)"
GH="${FC_GH:-$HOME/.local/bin/gh}"
ROUNDS="${FC_WAIT_ROUNDS:-6}"
SECONDS_WAIT="${FC_WAIT_SECONDS:-30}"

log() { echo "[$(date '+%Y-%m-%d %H:%M')] $*"; }

price_date() { grep -o '"date":"[0-9-]*"' | head -1 | cut -d'"' -f4; }

main() {
  cd "$DIR" || return 1
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    log "$DIR is not a git repository."
    return 1
  fi

  if [ -x "$GH" ]; then
    local gh_out
    if gh_out="$("$GH" workflow run update-prices.yml 2>&1)"; then
      log "Asked GitHub to update the prices."
    else
      log "gh failed to start the price job; continuing without it: $(echo "$gh_out" | tr '\n' ' ')"
    fi
  else
    log "gh not found at $GH; skipping the trigger."
  fi

  local local_date remote_date i
  local_date="$(price_date < prices.js 2>/dev/null)"
  i=0
  while [ "$i" -lt "$ROUNDS" ]; do
    i=$((i + 1))
    sleep "$SECONDS_WAIT"
    if git fetch origin main >/dev/null 2>&1; then
      remote_date="$(git show origin/main:prices.js 2>/dev/null | price_date)"
      if [[ -n "$remote_date" && "$remote_date" > "$local_date" ]]; then
        log "GitHub has prices for $remote_date."
        break
      fi
    else
      log "git fetch failed (round $i)."
    fi
  done

  local branch
  branch="$(git symbolic-ref --short -q HEAD)"
  if [ "$branch" != "main" ]; then
    log "On branch '${branch:-detached HEAD}', not main; leaving the folder alone."
    return 0
  fi

  git checkout -- prices.js >/dev/null 2>&1
  local out
  if out="$(git pull --ff-only origin main 2>&1)"; then
    log "Pulled from GitHub. Prices are dated $(price_date < prices.js)."
  else
    log "Could not update from GitHub (nothing else was changed): $(echo "$out" | tr '\n' ' ')"
  fi
  return 0
}

main
exit $?
