// Projects now come from the real backend (GET /api/projects, see
// client/src/api.js) instead of a mock array here. What's left below is
// purely the per-ticket detail synthesizer: real per-ticket scan history
// isn't wired up yet, so Project Detail / Check Health's existing-project
// re-run still fabricate ticket-level results from a project's aggregate
// stats (ticketCount/matchPercent/avgCompletion/healthStatus) — whichever
// project object is passed in, real or otherwise.

const STATUS_CYCLE = ['Done', 'In Progress', 'To Do']
const ASSIGNEE_CYCLE = ['Nguyen Van A', 'Tran Thi B', 'Le Van C', 'Pham Thi D']

const MISSING_PARTS_BY_ASSESSMENT = {
  Mismatch: ['Reported complete but core logic/endpoint is not implemented in code.'],
  Incomplete: ['Partial implementation found; some acceptance criteria not yet met.'],
  Match: [],
}

const SUGGESTIONS_BY_ASSESSMENT = {
  Mismatch: ['Re-verify with the ticket owner and correct the reported status.'],
  Incomplete: ['Continue implementation and add tests.'],
  Match: ['Verify acceptance criteria manually.'],
}

/**
 * Deterministically synthesize a full "scan result" (per-ticket results +
 * summary + health + trend) for a mock project, shaped exactly like a real
 * /api/evaluate response, so the Project Detail page can reuse
 * EvaluationResultsView. No randomness — same project always renders the
 * same detail so navigating back and forth is stable.
 */
export function buildMockProjectDetail(project) {
  const total = project.ticketCount
  const matchCount = Math.round((total * project.matchPercent) / 100)
  const remaining = total - matchCount

  let mismatchCount
  if (project.healthStatus === 'Late') mismatchCount = Math.ceil(remaining * 0.6)
  else if (project.healthStatus === 'Risk') mismatchCount = Math.floor(remaining * 0.3)
  else mismatchCount = 0
  const incompleteCount = remaining - mismatchCount

  const prefix = String(project.id).toUpperCase().replace(/[^A-Z0-9]/g, '') || 'TASK'

  const results = Array.from({ length: total }, (_, i) => {
    const assessment =
      i < matchCount ? 'Match' : i < matchCount + mismatchCount ? 'Mismatch' : 'Incomplete'
    const status = STATUS_CYCLE[i % STATUS_CYCLE.length]
    const completionPercent =
      assessment === 'Match'
        ? 80 + (i % 20)
        : assessment === 'Mismatch'
          ? 5 + (i % 25)
          : 30 + (i % 40)
    const isFlagged = assessment !== 'Match' && i % 3 !== 0
    const scheduleStatus = isFlagged ? (i % 2 === 0 ? 'Late' : 'At-Risk') : 'On-time'

    return {
      ticket_id: `${prefix}-${i + 1}`,
      summary: `${project.name} — task ${i + 1}`,
      status,
      completion_percent: Math.min(100, completionPercent),
      assessment,
      confidence: 0.5 + (i % 5) * 0.1,
      missing_parts: MISSING_PARTS_BY_ASSESSMENT[assessment],
      suggestions: SUGGESTIONS_BY_ASSESSMENT[assessment],
      evidence_files: i % 3 === 0 ? [] : [`src/module${i % 7}/file${i}.py`],
      notes: '',
      schedule_status: scheduleStatus,
      days_diff: scheduleStatus === 'Late' ? 2 + (i % 10) : scheduleStatus === 'At-Risk' ? -(1 + (i % 5)) : null,
      assignee: ASSIGNEE_CYCLE[i % ASSIGNEE_CYCLE.length],
    }
  })

  const issues = results
    .filter((r) => r.assessment === 'Mismatch' || r.schedule_status === 'Late')
    .map((r) => ({
      ticket_id: r.ticket_id,
      summary: r.summary,
      assessment: r.assessment,
      schedule_status: r.schedule_status,
      reason: r.missing_parts[0] || `${r.assessment}: schedule ${r.schedule_status}.`,
    }))

  const trendTickets = results
    .filter((r) => r.schedule_status !== 'On-time')
    .slice(0, 12)
    .map((r) => ({
      ticket_id: r.ticket_id,
      summary: r.summary,
      due_date: '2026-09-01',
      variance_days: r.days_diff ?? 0,
      schedule_status: r.schedule_status,
    }))

  return {
    results,
    summary: {
      total_tickets: total,
      match_count: matchCount,
      mismatch_count: mismatchCount,
      incomplete_count: incompleteCount,
      match_percent: project.matchPercent,
      avg_completion: project.avgCompletion,
      scanned_files: total * 3,
    },
    health: {
      status: project.healthStatus,
      issues,
      next_milestone: {
        status: 'None',
        days: null,
        message: 'No milestone tickets found (Issue Type = "Milestone" with a Due Date).',
      },
    },
    trend: {
      tickets: trendTickets,
      trend_min_days: trendTickets.length ? Math.min(...trendTickets.map((t) => t.variance_days)) : null,
      trend_max_days: trendTickets.length ? Math.max(...trendTickets.map((t) => t.variance_days)) : null,
      message: trendTickets.length
        ? `${trendTickets.length} ticket(s) tracked against schedule.`
        : 'No tickets with a Due Date to chart.',
    },
  }
}
