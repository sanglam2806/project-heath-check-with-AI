// Mirrors server/ticket_status.py's is_done_status()/is_in_progress_status()
// BY HAND -- JS can't import that Python module, so keep these two
// definitions in sync. Teams name their terminal statuses differently
// (Done, Closed, Resolved, "Release", "Ready for Release", "Deployed to
// prod", "Verified", "Shipped", ...), so DONE matching also checks for a
// handful of substrings anywhere in the status.
const DONE_STATUSES = ['done', 'closed', 'resolved']
const DONE_SUBSTRINGS = ['release', 'deploy', 'complete', 'verified', 'shipped']
const IN_PROGRESS_STATUSES = ['in progress', 'in_progress', 'doing', 'development']

function normalize(status) {
  return String(status || '').trim().toLowerCase()
}

export function isDoneStatus(status) {
  const s = normalize(status)
  if (DONE_STATUSES.includes(s)) return true
  for (const sub of DONE_SUBSTRINGS) {
    if (!s.includes(sub)) continue
    // The one known false-positive: "complete" is a substring of
    // "incomplete", which must NOT count as done.
    if (sub === 'complete' && s.includes('incomplete')) continue
    return true
  }
  return false
}

export function isInProgressStatus(status) {
  return IN_PROGRESS_STATUSES.includes(normalize(status))
}
