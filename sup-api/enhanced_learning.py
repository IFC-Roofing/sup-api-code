"""
Enhanced Learning Service — Recommendation-Based Intelligence
Provides insights and better approaches, NEVER says "skip this".
Always suggests "try this approach instead".

Hardcoded suggestions serve as fallback defaults; learned approaches from
successful outcomes are preferred when available.
"""

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

from learning_service import LearningService, _DATA_DIR

logger = logging.getLogger("sup-api.enhanced_learning")


class EnhancedLearningService(LearningService):
    """Enhanced learning that provides intelligence, not rules."""

    # ── Strategy intelligence ──────────────────────────────────

    def get_strategy_intelligence(self, carrier: str, strategy: str) -> Dict[str, Any]:
        """Get comprehensive intelligence about a strategy."""
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT so.outcome, so.denial_reason, so.approved_amount,
                   se.created_at, se.amount_requested, se.status
            FROM strategy_outcomes so
            JOIN supplement_events se ON so.supplement_event_id = se.id
            WHERE se.carrier = ? AND so.strategy_name = ?
            AND se.created_at > date('now', '-90 days')
            ORDER BY se.created_at DESC
        """, (carrier, strategy))

        outcomes = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if len(outcomes) < 3:
            return {
                "strategy": strategy,
                "carrier": carrier,
                "data_insufficient": True,
                "sample_size": len(outcomes),
                "recommendation": "monitor_results",
            }

        total = len(outcomes)
        successful = len([o for o in outcomes if o["outcome"] in ("approved", "partial")])
        success_rate = (successful / total) * 100

        denials = [o for o in outcomes if o["outcome"] == "denied"]
        successes = [o for o in outcomes if o["outcome"] in ("approved", "partial")]

        return {
            "strategy": strategy,
            "carrier": carrier,
            "success_rate": round(success_rate, 1),
            "sample_size": total,
            "last_updated": datetime.now().isoformat(),
            "recommendation_type": self._get_recommendation_type(success_rate),
            "insights": self._generate_strategy_insights(strategy, carrier, outcomes, denials, successes),
        }

    def get_comprehensive_intelligence(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        """Get comprehensive intelligence for multiple strategies."""
        intelligence: Dict[str, Any] = {
            "carrier": carrier,
            "analysis_date": datetime.now().isoformat(),
            "strategies": {},
            "carrier_overview": self._get_carrier_overview(carrier),
        }
        for strategy in strategies:
            intelligence["strategies"][strategy] = self.get_strategy_intelligence(carrier, strategy)
        return intelligence

    # ── Carrier overview ───────────────────────────────────────

    def _get_carrier_overview(self, carrier: str) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM supplement_events
            WHERE carrier = ? AND created_at > date('now', '-90 days')
            GROUP BY status
        """, (carrier,))
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
        total = sum(status_counts.values())
        conn.close()

        if total < 5:
            return {"insufficient_data": True, "note": f"Only {total} projects with {carrier} in last 90 days"}

        successful = status_counts.get("approved", 0) + status_counts.get("partial", 0)
        success_rate = (successful / total) * 100
        return {
            "overall_success_rate": round(success_rate, 1),
            "total_projects": total,
            "approval_breakdown": {
                "approved": status_counts.get("approved", 0),
                "partial": status_counts.get("partial", 0),
                "denied": status_counts.get("denied", 0),
            },
            "recommendation": self._get_carrier_recommendation(success_rate),
        }

    def _get_carrier_recommendation(self, success_rate: float) -> str:
        if success_rate > 70:
            return "cooperative_carrier"
        elif success_rate > 40:
            return "standard_documentation_required"
        else:
            return "challenging_carrier_extra_evidence_needed"

    # ── Recommendation helpers ─────────────────────────────────

    def _get_recommendation_type(self, success_rate: float) -> str:
        if success_rate < 25:
            return "needs_better_approach"
        elif success_rate > 75:
            return "current_approach_working"
        elif success_rate > 50:
            return "good_approach_refine"
        else:
            return "standard_approach_monitor"

    def _generate_strategy_insights(
        self,
        strategy: str,
        carrier: str,
        outcomes: List[Dict],
        denials: List[Dict],
        successes: List[Dict],
    ) -> Dict[str, Any]:
        return {
            "recent_trend": self._analyze_trend(outcomes),
            "common_denial_reasons": self._analyze_denial_reasons(denials),
            "successful_patterns": self._analyze_successful_patterns(successes),
            "recommended_approaches": self._suggest_approaches(strategy, carrier, outcomes),
        }

    # ── Trend analysis ─────────────────────────────────────────

    def _analyze_trend(self, outcomes: List[Dict]) -> Dict[str, str]:
        if len(outcomes) < 6:
            return {"trend": "insufficient_data", "note": "Need more data points"}

        mid = len(outcomes) // 2
        recent = outcomes[:mid]
        older = outcomes[mid:]

        recent_rate = len([o for o in recent if o["outcome"] in ("approved", "partial")]) / len(recent)
        older_rate = len([o for o in older if o["outcome"] in ("approved", "partial")]) / len(older)

        if recent_rate > older_rate + 0.1:
            return {"trend": "improving", "note": f"Success rate increased from {older_rate:.1%} to {recent_rate:.1%}"}
        elif recent_rate < older_rate - 0.1:
            return {"trend": "declining", "note": f"Success rate dropped from {older_rate:.1%} to {recent_rate:.1%}"}
        else:
            return {"trend": "stable", "note": f"Consistent ~{recent_rate:.1%} success rate"}

    def _analyze_denial_reasons(self, denials: List[Dict]) -> List[Dict[str, Any]]:
        if not denials:
            return []
        reason_counts: Dict[str, int] = {}
        for d in denials:
            r = d.get("denial_reason") or "No reason provided"
            reason_counts[r] = reason_counts.get(r, 0) + 1
        return [
            {"reason": r, "frequency": c, "percentage": (c / len(denials)) * 100}
            for r, c in sorted(reason_counts.items(), key=lambda x: -x[1])
        ][:3]

    def _analyze_successful_patterns(self, successes: List[Dict]) -> List[Dict[str, Any]]:
        if not successes:
            return []
        patterns: List[Dict[str, Any]] = []
        amounts = [s["approved_amount"] for s in successes if s.get("approved_amount")]
        if amounts:
            avg = sum(amounts) / len(amounts)
            patterns.append({
                "pattern_type": "amount_range",
                "insight": f"Successful requests average ${avg:,.0f}",
                "data": {"average": avg, "count": len(amounts)},
            })
        recent_wins = [s for s in successes if s.get("outcome") == "approved"]
        if recent_wins:
            patterns.append({
                "pattern_type": "recent_wins",
                "insight": f"{len(recent_wins)} recent approvals suggest approach is viable",
                "data": {"recent_approvals": len(recent_wins)},
            })
        return patterns

    # ── Approach suggestions ───────────────────────────────────
    # Learned approaches take precedence; hardcoded are fallback defaults.

    def _suggest_approaches(self, strategy: str, carrier: str, outcomes: List[Dict]) -> List[Dict[str, str]]:
        """Suggest approaches: prefer learned from DB, fall back to hardcoded defaults."""
        # Try learned approaches first
        learned = self._get_learned_approaches(strategy, carrier)
        if learned:
            return learned

        # Fallback defaults (never say "skip"; always "try this instead")
        approaches = self._get_fallback_approaches(strategy)

        # Carrier-specific notes
        carrier_notes = {
            "Allstate": "Allstate prefers detailed documentation — include photos and measurements",
            "State_Farm": "State Farm responds well to code references and technical justifications",
            "State Farm": "State Farm responds well to code references and technical justifications",
            "USAA": "USAA values military-precise documentation — be thorough and organized",
            "Travelers": "Travelers is data-driven — include cost breakdowns and comparisons",
        }
        note = carrier_notes.get(carrier)
        if note:
            for a in approaches:
                a["carrier_note"] = note

        return approaches

    def _get_learned_approaches(self, strategy: str, carrier: str) -> List[Dict[str, str]]:
        """Load approaches that were learned from successful outcomes."""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT approach_name, description, evidence, carrier_note, success_count, failure_count
            FROM learned_approaches
            WHERE strategy = ? AND (carrier = ? OR carrier IS NULL)
            AND success_count > failure_count
            ORDER BY success_count DESC
            LIMIT 5
        """, (strategy, carrier))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not rows:
            return []

        return [
            {
                "approach": r["approach_name"],
                "description": r["description"] or "",
                "evidence": r["evidence"] or "",
                "carrier_note": r.get("carrier_note") or "",
                "learned": True,
                "win_rate": round(r["success_count"] / max(r["success_count"] + r["failure_count"], 1) * 100, 1),
            }
            for r in rows
        ]

    def record_approach_outcome(
        self,
        strategy: str,
        carrier: str,
        approach_name: str,
        success: bool,
        description: str = None,
        evidence: str = None,
    ):
        """Record an approach outcome to learn over time."""
        import sqlite3 as _sq

        conn = _sq.connect(self.db_path)
        if success:
            conn.execute("""
                INSERT INTO learned_approaches (strategy, carrier, approach_name, description, evidence, success_count, source)
                VALUES (?, ?, ?, ?, ?, 1, 'observed')
                ON CONFLICT(strategy, carrier, approach_name) DO UPDATE SET
                    success_count = success_count + 1,
                    last_used = CURRENT_TIMESTAMP
            """, (strategy, carrier, approach_name, description, evidence))
        else:
            conn.execute("""
                INSERT INTO learned_approaches (strategy, carrier, approach_name, description, evidence, failure_count, source)
                VALUES (?, ?, ?, ?, ?, 1, 'observed')
                ON CONFLICT(strategy, carrier, approach_name) DO UPDATE SET
                    failure_count = failure_count + 1,
                    last_used = CURRENT_TIMESTAMP
            """, (strategy, carrier, approach_name, description, evidence))
        conn.commit()
        conn.close()

    @staticmethod
    def _get_fallback_approaches(strategy: str) -> List[Dict[str, str]]:
        """Hardcoded fallback approaches — always suggest, never skip."""
        defaults: Dict[str, List[Dict[str, str]]] = {
            "steep_on_waste": [
                {
                    "approach": "EagleView pitch documentation",
                    "description": "Use precise measurements instead of generic steep roof claims",
                    "evidence": "EagleView pitch diagram + safety equipment costs",
                },
                {
                    "approach": "OSHA safety compliance angle",
                    "description": "Document additional safety requirements for steep installations",
                    "evidence": "Safety equipment rental receipts + compliance documentation",
                },
                {
                    "approach": "Time study comparison",
                    "description": "Show actual time difference between flat vs steep installation",
                    "evidence": "Contractor time logs + productivity comparison",
                },
            ],
            "O&P": [
                {
                    "approach": "Multi-trade coordination",
                    "description": "Emphasize coordination complexity across multiple trades",
                    "evidence": "Project timeline + trade scheduling documentation",
                },
                {
                    "approach": "Business overhead documentation",
                    "description": "Provide concrete business expenses and licensing",
                    "evidence": "Business license + office lease + employee verification",
                },
                {
                    "approach": "Project management services",
                    "description": "Detail specific PM activities and deliverables",
                    "evidence": "Project management plan + progress reports",
                },
            ],
            "full_fence_scope": [
                {
                    "approach": "Pre-loss condition matching",
                    "description": "Document requirement to match existing appearance",
                    "evidence": "Before photos + building code appearance standards",
                },
                {
                    "approach": "Partial treatment visibility",
                    "description": "Show how partial repair creates obvious visual mismatch",
                    "evidence": "Panoramic fence photos + close-up damage comparison",
                },
            ],
        }
        return defaults.get(strategy, [])


# ── Singleton ──────────────────────────────────────────────────
enhanced_learning = EnhancedLearningService()
