"""
Learning Service for Supplement AI
Tracks supplement events, strategy outcomes, adjuster patterns, and seasonal trends.
All paths configurable via environment variables — no hardcoded absolute paths.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger("sup-api.learning")

# ── Configurable data directory ────────────────────────────────
_WORKSPACE = Path(os.environ.get("SUP_WORKSPACE", str(Path(__file__).parent.parent.parent)))
_DATA_DIR = Path(os.environ.get("SUP_DATA_DIR", str(_WORKSPACE / "data" / "learning")))


class LearningService:
    """Core learning service — tracks events, outcomes, patterns."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "learning.db"
        self.cache_dir = self.data_dir / "cache"
        self.logs_dir = self.data_dir / "logs"

        self.cache_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

        self._init_database()

    # ── Database setup ─────────────────────────────────────────

    def _init_database(self):
        """Initialize SQLite database with all learning tables."""
        conn = sqlite3.connect(self.db_path)

        # ── supplement_events (extended with adjuster + response time tracking)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplement_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                project_name TEXT,
                event_type TEXT,          -- 'generated', 'sent', 'response', 'outcome'
                status TEXT,              -- 'pending', 'approved', 'denied', 'partial'
                carrier TEXT,
                amount_requested REAL,
                amount_approved REAL DEFAULT 0,
                strategies_used TEXT,     -- JSON array
                event_data TEXT,          -- JSON blob
                context_data TEXT,        -- JSON blob
                event_timestamp TEXT,
                parent_event_id INTEGER,
                adjuster_name TEXT,
                adjuster_id TEXT,
                response_received_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── learning_patterns
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT,        -- 'carrier_behavior', 'strategy_success'
                context_key TEXT,         -- 'Allstate_steep_waste'
                pattern_data TEXT,        -- JSON with success rates, etc
                confidence_score REAL DEFAULT 0.0,
                sample_size INTEGER DEFAULT 0,
                discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                UNIQUE(pattern_type, context_key)
            )
        """)

        # ── strategy_outcomes (extended with photos_submitted)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplement_event_id INTEGER,
                strategy_name TEXT,
                trade_tag TEXT,
                strategy_amount REAL,
                outcome TEXT,             -- 'approved', 'denied', 'partial'
                approved_amount REAL DEFAULT 0,
                denial_reason TEXT,
                photos_submitted TEXT,    -- JSON array of photo references
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (supplement_event_id) REFERENCES supplement_events(id)
            )
        """)

        # ── f9_outcomes — track F9 note effectiveness per trade/carrier
        conn.execute("""
            CREATE TABLE IF NOT EXISTS f9_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplement_event_id INTEGER,
                trade_tag TEXT,
                line_item TEXT,
                f9_text TEXT,
                f9_version INTEGER DEFAULT 1,
                outcome TEXT,
                carrier TEXT,
                adjuster_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (supplement_event_id) REFERENCES supplement_events(id)
            )
        """)

        # ── user_preferences — per-user settings + learned preferences
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                preference_key TEXT,
                preference_value TEXT,
                context TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, preference_key)
            )
        """)

        # ── learned_approaches — successful approaches discovered over time
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learned_approaches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                carrier TEXT,
                approach_name TEXT NOT NULL,
                description TEXT,
                evidence TEXT,
                carrier_note TEXT,
                success_count INTEGER DEFAULT 1,
                failure_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'observed',  -- 'observed', 'manual', 'fallback'
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(strategy, carrier, approach_name)
            )
        """)

        # Migrate: add columns that may be missing on existing DBs
        self._migrate_add_columns(conn)

        conn.commit()
        conn.close()
        logger.info(f"Learning database initialized: {self.db_path}")

    def _migrate_add_columns(self, conn):
        """Safely add new columns to existing tables (idempotent)."""
        migrations = [
            ("supplement_events", "adjuster_name", "TEXT"),
            ("supplement_events", "adjuster_id", "TEXT"),
            ("supplement_events", "response_received_at", "TEXT"),
            ("strategy_outcomes", "photos_submitted", "TEXT"),
        ]
        for table, col, col_type in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists

    # ── Connection helper ──────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Tracking ───────────────────────────────────────────────

    def track_supplement_generation(
        self,
        project_id: int,
        project_name: str,
        carrier: str,
        strategies: List[str],
        amount_requested: float,
        adjuster_name: Optional[str] = None,
        adjuster_id: Optional[str] = None,
    ) -> int:
        """Track when a supplement is generated."""
        conn = sqlite3.connect(self.db_path)

        cursor = conn.execute("""
            INSERT INTO supplement_events
            (project_id, project_name, event_type, status, carrier,
             amount_requested, strategies_used, event_timestamp, event_data,
             adjuster_name, adjuster_id)
            VALUES (?, ?, 'generated', 'pending', ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, project_name, carrier, amount_requested,
            json.dumps(strategies), datetime.now().isoformat(),
            json.dumps({
                "generated_at": datetime.now().isoformat(),
                "strategy_count": len(strategies),
            }),
            adjuster_name, adjuster_id,
        ))

        event_id = cursor.lastrowid

        # Track individual strategies
        per_strategy = amount_requested / max(len(strategies), 1)
        for strategy in strategies:
            conn.execute("""
                INSERT INTO strategy_outcomes
                (supplement_event_id, strategy_name, outcome, strategy_amount)
                VALUES (?, ?, 'unknown', ?)
            """, (event_id, strategy, per_strategy))

        conn.commit()
        conn.close()

        self._log_event({
            "event_id": event_id,
            "type": "generation",
            "project": project_name,
            "carrier": carrier,
            "strategies": strategies,
            "amount": amount_requested,
            "adjuster_name": adjuster_name,
            "timestamp": datetime.now().isoformat(),
        })

        logger.info(f"Tracked generation: {project_name} (ID: {event_id})")
        return event_id

    def track_insurance_response(
        self,
        event_id: int,
        approved_items: List[Dict],
        denied_items: List[Dict],
        total_approved: float,
        adjuster_name: Optional[str] = None,
    ):
        """Track insurance response to a supplement."""
        conn = sqlite3.connect(self.db_path)

        status = self._determine_status(total_approved, event_id, conn)
        now_iso = datetime.now().isoformat()

        conn.execute("""
            UPDATE supplement_events
            SET status = ?, amount_approved = ?, response_received_at = ?
            WHERE id = ?
        """, (status, total_approved, now_iso, event_id))

        if adjuster_name:
            conn.execute("""
                UPDATE supplement_events SET adjuster_name = ? WHERE id = ? AND adjuster_name IS NULL
            """, (adjuster_name, event_id))

        for item in approved_items:
            conn.execute("""
                UPDATE strategy_outcomes
                SET outcome = 'approved', approved_amount = ?
                WHERE supplement_event_id = ? AND strategy_name = ?
            """, (item.get("amount", 0), event_id, item.get("strategy")))

        for item in denied_items:
            conn.execute("""
                UPDATE strategy_outcomes
                SET outcome = 'denied', denial_reason = ?
                WHERE supplement_event_id = ? AND strategy_name = ?
            """, (item.get("reason"), event_id, item.get("strategy")))

        conn.commit()
        conn.close()

        self._maybe_update_patterns()
        logger.info(f"Tracked response for event {event_id}: {status}")

    def track_f9_outcome(
        self,
        supplement_event_id: int,
        trade_tag: str,
        line_item: str,
        f9_text: str,
        outcome: str,
        carrier: str,
        adjuster_name: Optional[str] = None,
        f9_version: int = 1,
    ) -> int:
        """Track F9 note effectiveness."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            INSERT INTO f9_outcomes
            (supplement_event_id, trade_tag, line_item, f9_text,
             f9_version, outcome, carrier, adjuster_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (supplement_event_id, trade_tag, line_item, f9_text,
              f9_version, outcome, carrier, adjuster_name))
        row_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return row_id

    # ── Learned patterns ───────────────────────────────────────

    def get_learned_patterns(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        """Get learned patterns for supplement generation."""
        cache_file = self.cache_dir / f"{carrier.lower()}_insights.json"
        if cache_file.exists() and self._cache_is_fresh(cache_file):
            with open(cache_file) as f:
                return json.load(f)

        patterns = self._generate_fresh_patterns(carrier, strategies)
        with open(cache_file, "w") as f:
            json.dump(patterns, f)
        return patterns

    def _generate_fresh_patterns(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        conn = self._get_connection()
        patterns: Dict[str, Any] = {}

        # Carrier behavior
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM supplement_events
            WHERE carrier = ? AND event_type = 'generated'
            AND created_at > date('now', '-90 days')
            GROUP BY status
        """, (carrier,))
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
        total = sum(status_counts.values())

        if total >= 10:
            denial_rate = (status_counts.get("denied", 0) / total) * 100
            patterns[f"{carrier}_behavior"] = {
                "denial_rate": denial_rate,
                "sample_size": total,
                "recommendation": "conservative" if denial_rate > 60 else "standard",
            }

        # Per-strategy patterns
        for strategy in strategies:
            cursor = conn.execute("""
                SELECT outcome, COUNT(*) as count
                FROM strategy_outcomes so
                JOIN supplement_events se ON so.supplement_event_id = se.id
                WHERE se.carrier = ? AND so.strategy_name = ?
                AND se.created_at > date('now', '-90 days')
                GROUP BY outcome
            """, (carrier, strategy))
            outcome_counts = {row["outcome"]: row["count"] for row in cursor.fetchall()}
            strat_total = sum(outcome_counts.values())

            if strat_total >= 5:
                success_count = outcome_counts.get("approved", 0) + outcome_counts.get("partial", 0)
                success_rate = (success_count / strat_total) * 100
                if success_rate < 20:
                    rec = "needs_better_approach"
                elif success_rate > 80:
                    rec = "current_approach_working"
                else:
                    rec = "standard_approach"

                patterns[f"{carrier}_{strategy}"] = {
                    "success_rate": success_rate,
                    "sample_size": strat_total,
                    "recommendation": rec,
                }

        conn.close()
        return patterns

    # ── Seasonal patterns ──────────────────────────────────────

    def get_seasonal_patterns(self, carrier: str) -> Dict[str, Any]:
        """Analyze success rates by month/quarter for a carrier."""
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT
                strftime('%m', created_at) AS month,
                status,
                COUNT(*) AS cnt
            FROM supplement_events
            WHERE carrier = ?
              AND created_at > date('now', '-365 days')
              AND status IS NOT NULL
            GROUP BY month, status
            ORDER BY month
        """, (carrier,))

        monthly: Dict[str, Dict[str, int]] = {}
        for row in cursor.fetchall():
            m = row["month"]
            monthly.setdefault(m, {"approved": 0, "partial": 0, "denied": 0, "pending": 0})
            monthly[m][row["status"]] = row["cnt"]

        # Aggregate into quarters
        quarter_map = {"01": "Q1", "02": "Q1", "03": "Q1",
                       "04": "Q2", "05": "Q2", "06": "Q2",
                       "07": "Q3", "08": "Q3", "09": "Q3",
                       "10": "Q4", "11": "Q4", "12": "Q4"}
        quarterly: Dict[str, Dict[str, int]] = {}
        for m, counts in monthly.items():
            q = quarter_map.get(m, "??")
            quarterly.setdefault(q, {"approved": 0, "partial": 0, "denied": 0, "pending": 0})
            for k, v in counts.items():
                quarterly[q][k] = quarterly[q].get(k, 0) + v

        def _rate(d: Dict[str, int]) -> float:
            t = sum(d.values()) - d.get("pending", 0)
            if t == 0:
                return 0.0
            return round(((d.get("approved", 0) + d.get("partial", 0)) / t) * 100, 1)

        conn.close()
        return {
            "carrier": carrier,
            "monthly": {m: {"counts": c, "success_rate": _rate(c)} for m, c in sorted(monthly.items())},
            "quarterly": {q: {"counts": c, "success_rate": _rate(c)} for q, c in sorted(quarterly.items())},
            "generated_at": datetime.now().isoformat(),
        }

    # ── Response time patterns ─────────────────────────────────

    def get_response_time_patterns(self, carrier: str) -> Dict[str, Any]:
        """Analyze how long carriers take to respond."""
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT
                id,
                created_at,
                response_received_at,
                status
            FROM supplement_events
            WHERE carrier = ?
              AND response_received_at IS NOT NULL
              AND created_at > date('now', '-365 days')
        """, (carrier,))

        deltas: List[float] = []
        status_deltas: Dict[str, List[float]] = {}
        for row in cursor.fetchall():
            try:
                sent = datetime.fromisoformat(row["created_at"])
                recv = datetime.fromisoformat(row["response_received_at"])
                days = (recv - sent).total_seconds() / 86400
                deltas.append(days)
                status_deltas.setdefault(row["status"], []).append(days)
            except (ValueError, TypeError):
                continue

        conn.close()

        if not deltas:
            return {"carrier": carrier, "insufficient_data": True, "sample_size": 0}

        return {
            "carrier": carrier,
            "sample_size": len(deltas),
            "avg_response_days": round(sum(deltas) / len(deltas), 1),
            "min_response_days": round(min(deltas), 1),
            "max_response_days": round(max(deltas), 1),
            "by_status": {
                s: {
                    "avg_days": round(sum(d) / len(d), 1),
                    "count": len(d),
                }
                for s, d in status_deltas.items()
            },
            "generated_at": datetime.now().isoformat(),
        }

    # ── Adjuster patterns ─────────────────────────────────────

    def get_adjuster_patterns(self, adjuster_name: str) -> Dict[str, Any]:
        """Get patterns for a specific adjuster."""
        conn = self._get_connection()

        cursor = conn.execute("""
            SELECT carrier, status, COUNT(*) as cnt
            FROM supplement_events
            WHERE adjuster_name = ?
              AND created_at > date('now', '-365 days')
            GROUP BY carrier, status
        """, (adjuster_name,))

        carrier_stats: Dict[str, Dict[str, int]] = {}
        for row in cursor.fetchall():
            c = row["carrier"] or "Unknown"
            carrier_stats.setdefault(c, {"approved": 0, "partial": 0, "denied": 0, "pending": 0})
            carrier_stats[c][row["status"]] = row["cnt"]

        # Average response time for this adjuster
        cursor = conn.execute("""
            SELECT created_at, response_received_at
            FROM supplement_events
            WHERE adjuster_name = ? AND response_received_at IS NOT NULL
        """, (adjuster_name,))
        resp_days: List[float] = []
        for row in cursor.fetchall():
            try:
                d = (datetime.fromisoformat(row["response_received_at"]) -
                     datetime.fromisoformat(row["created_at"])).total_seconds() / 86400
                resp_days.append(d)
            except (ValueError, TypeError):
                continue

        conn.close()

        total_all = sum(sum(v.values()) for v in carrier_stats.values())
        return {
            "adjuster_name": adjuster_name,
            "total_supplements": total_all,
            "carriers": {
                c: {
                    "counts": s,
                    "success_rate": round(
                        ((s.get("approved", 0) + s.get("partial", 0)) /
                         max(sum(s.values()) - s.get("pending", 0), 1)) * 100, 1
                    ),
                }
                for c, s in carrier_stats.items()
            },
            "avg_response_days": round(sum(resp_days) / len(resp_days), 1) if resp_days else None,
            "generated_at": datetime.now().isoformat(),
        }

    # ── Insights ───────────────────────────────────────────────

    def get_insights_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary insights for dashboard."""
        conn = self._get_connection()

        cursor = conn.execute(f"""
            SELECT status, COUNT(*) as count
            FROM supplement_events
            WHERE created_at > date('now', '-{days} days')
            GROUP BY status
        """)
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
        total = sum(status_counts.values())

        success_rate = 0.0
        if total > 0:
            successful = status_counts.get("approved", 0) + status_counts.get("partial", 0)
            success_rate = (successful / total) * 100

        cursor = conn.execute(f"""
            SELECT so.strategy_name,
                   AVG(CASE WHEN so.outcome IN ('approved', 'partial') THEN 1.0 ELSE 0.0 END) * 100 as success_rate,
                   COUNT(*) as attempts
            FROM strategy_outcomes so
            JOIN supplement_events se ON so.supplement_event_id = se.id
            WHERE se.created_at > date('now', '-{days} days')
            GROUP BY so.strategy_name
            HAVING attempts >= 5
            ORDER BY success_rate DESC
            LIMIT 10
        """)
        top_strategies = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            "summary": {
                "total_supplements": total,
                "success_rate": round(success_rate, 2),
                "status_breakdown": status_counts,
                "time_period_days": days,
            },
            "top_strategies": top_strategies,
            "generated_at": datetime.now().isoformat(),
        }

    # ── User preferences ───────────────────────────────────────

    def get_user_preference(self, user_id: int, key: str) -> Optional[str]:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT preference_value FROM user_preferences WHERE user_id = ? AND preference_key = ?",
            (user_id, key),
        )
        row = cursor.fetchone()
        conn.close()
        return row["preference_value"] if row else None

    def set_user_preference(self, user_id: int, user_name: str, key: str, value: str, context: str = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO user_preferences (user_id, user_name, preference_key, preference_value, context, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, preference_key) DO UPDATE SET
                preference_value = excluded.preference_value,
                context = excluded.context,
                updated_at = excluded.updated_at
        """, (user_id, user_name, key, value, context, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    # ── Internal helpers ───────────────────────────────────────

    def _determine_status(self, approved_amount: float, event_id: int, conn) -> str:
        cursor = conn.execute("SELECT amount_requested FROM supplement_events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        requested = row[0] if row else 0
        if approved_amount == 0:
            return "denied"
        elif requested and approved_amount >= requested * 0.95:
            return "approved"
        else:
            return "partial"

    def _log_event(self, event_data: Dict):
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(event_data) + "\n")

    def _cache_is_fresh(self, cache_file: Path, max_age_hours: int = 12) -> bool:
        if not cache_file.exists():
            return False
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        return file_age < timedelta(hours=max_age_hours)

    def _maybe_update_patterns(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT COUNT(*) FROM supplement_events
            WHERE created_at > datetime('now', '-1 hour')
        """)
        recent_count = cursor.fetchone()[0]
        conn.close()
        if recent_count >= 3:
            logger.info("Triggering pattern update due to new data")
            self._update_all_patterns()

    def _update_all_patterns(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT DISTINCT carrier FROM supplement_events
            WHERE created_at > date('now', '-90 days')
            AND carrier IS NOT NULL
        """)
        carriers = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Clear cache
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()

        logger.info(f"Updated patterns for {len(carriers)} carriers")


# ── Singleton ──────────────────────────────────────────────────
learning_service = LearningService()
