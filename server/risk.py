"""
Risk module: derives a per-ticket and project-wide risk score purely from
already-computed evaluation results (no source re-scan needed).
"""
from typing import Dict, List

import ticket_status
from models import ProjectRisk, RiskItem, TicketResult

_SEVERITY_THRESHOLDS = (
    ("Critical", 70),
    ("High", 45),
    ("Medium", 20),
)


def _severity_for_score(score: float) -> str:
    for label, threshold in _SEVERITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "Low"


def score_ticket_risk(ticket: Dict, result: TicketResult) -> Dict:
    """
    Weighted heuristic risk score (0-100) for one ticket:
      - assessment contradiction: Mismatch +40 / Incomplete +15 / Match +0
      - schedule slip: Late +35 / At-Risk +20 / else +0
      - reported-Done completion gap: (100 - completion_percent) * 0.3, capped at 30,
        only applies when the reported status is Done/Closed/Resolved (otherwise a
        low completion_percent is expected, not risky)
      - low-confidence penalty: only added once something else already flagged
        risk, since low confidence alone isn't a risk factor
    """
    score = 0.0
    factors: List[str] = []

    if result.assessment == "Mismatch":
        score += 40
        factors.append("Code contradicts the reported ticket status.")
    elif result.assessment == "Incomplete":
        score += 15
        factors.append("Implementation is genuinely still in progress.")

    if result.schedule_status == "Late":
        score += 35
        days = f" ({result.days_diff}d overdue)" if result.days_diff else ""
        factors.append(f"Past due date{days}.")
    elif result.schedule_status == "At-Risk":
        score += 20
        factors.append("Due date approaching with low completion.")

    if ticket_status.is_done_status(ticket.get("status")):
        gap = max(0.0, 100.0 - result.completion_percent)
        gap_score = min(30.0, gap * 0.3)
        if gap_score > 0:
            score += gap_score
            factors.append(
                f"Reported {ticket.get('status')} but only ~{result.completion_percent:.0f}% "
                "of the work is actually evidenced in code."
            )

    if score > 0:
        score += max(0.0, 1.0 - result.confidence) * 10
        if result.confidence < 0.5:
            factors.append("Low model confidence in this assessment — verify manually.")

    score = max(0.0, min(100.0, score))
    severity = _severity_for_score(score)

    if severity in ("Critical", "High"):
        recommended_action = (
            "Re-verify with the ticket owner immediately and correct the reported status."
        )
    elif severity == "Medium":
        recommended_action = "Follow up before the next status review."
    else:
        recommended_action = "No action needed — on track."

    return {
        "risk_score": round(score, 1),
        "severity": severity,
        "factors": factors,
        "recommended_action": recommended_action,
    }


def build_project_risk(tickets: List[Dict], results: List[TicketResult]) -> ProjectRisk:
    tickets_by_id = {t["ticket_id"].upper(): t for t in tickets}

    items: List[RiskItem] = []
    for result in results:
        ticket = tickets_by_id.get(result.ticket_id.upper(), {"status": result.status})
        scored = score_ticket_risk(ticket, result)
        items.append(
            RiskItem(
                ticket_id=result.ticket_id,
                summary=result.summary,
                risk_score=scored["risk_score"],
                severity=scored["severity"],
                factors=scored["factors"],
                recommended_action=scored["recommended_action"],
                assessment=result.assessment,
                schedule_status=result.schedule_status,
                completion_percent=result.completion_percent,
                confidence=result.confidence,
            )
        )

    items.sort(key=lambda it: -it.risk_score)

    distribution = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for item in items:
        distribution[item.severity] = distribution.get(item.severity, 0) + 1

    overall = round(sum(it.risk_score for it in items) / len(items), 1) if items else 0.0

    if not items:
        message = "No tickets evaluated yet."
    elif distribution["Critical"] > 0:
        message = f"{distribution['Critical']} ticket(s) at Critical risk — review immediately."
    elif distribution["High"] > 0:
        message = f"{distribution['High']} ticket(s) at High risk."
    else:
        message = "No critical or high-risk tickets found."

    return ProjectRisk(
        items=items,
        overall_risk_score=overall,
        distribution=distribution,
        message=message,
    )
