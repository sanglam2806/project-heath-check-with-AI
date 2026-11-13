"""
Builds a single-run schedule trend: for every ticket that has a Due Date,
how many days ahead of (negative) or behind (positive) that date it sits
today - reusing the days_diff/schedule_status the evaluator already
computed. This needs no history across runs; it's a snapshot, not a
time series.

The headline estimate ("Trending N-M days late") is drawn only from
tickets that are already overdue (schedule_status == "Late"), since that
is real, already-elapsed slip - not a fabricated forecast. At-risk
tickets are called out separately by count, without inventing a lateness
figure for them.
"""
from typing import Dict, List

from models import ProjectTrend, TicketResult, TicketVariance


def _build_message(bars: List[TicketVariance]) -> ProjectTrend:
    late_days = [b.variance_days for b in bars if b.schedule_status == "Late"]
    at_risk_count = sum(1 for b in bars if b.schedule_status == "At-Risk")

    if late_days:
        lo, hi = min(late_days), max(late_days)
        message = f"Trending {lo} days late" if lo == hi else f"Trending {lo}–{hi} days late"
        if at_risk_count:
            message += f", plus {at_risk_count} ticket(s) at risk of slipping further."
        else:
            message += "."
        trend_min, trend_max = lo, hi
    elif at_risk_count:
        message = (
            f"On schedule so far, but {at_risk_count} ticket(s) "
            "are at risk of missing their due date."
        )
        trend_min = trend_max = None
    elif bars:
        message = "On schedule - no overdue or at-risk tickets."
        trend_min = trend_max = None
    else:
        message = "No tickets with a Due Date to chart."
        trend_min = trend_max = None

    return ProjectTrend(
        tickets=bars, trend_min_days=trend_min, trend_max_days=trend_max, message=message
    )


def build_project_trend(tickets: List[Dict], results: List[TicketResult]) -> ProjectTrend:
    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}

    bars: List[TicketVariance] = []
    for r in results:
        if r.days_diff is None:
            continue  # no (parseable) Due Date -> nothing to plot
        t = tickets_by_id.get(r.ticket_id.upper(), {})
        bars.append(TicketVariance(
            ticket_id=r.ticket_id,
            summary=r.summary,
            due_date=t.get("due_date", ""),
            variance_days=r.days_diff,
            schedule_status=r.schedule_status,
        ))

    bars.sort(key=lambda b: b.variance_days, reverse=True)
    return _build_message(bars)
