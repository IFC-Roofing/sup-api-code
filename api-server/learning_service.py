#!/usr/bin/env python3
"""
Learning Service for Supplement AI
Handles all learning, memory, and pattern discovery in the microservice
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LearningService:
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.db_path = self.data_dir / "learning.db"
        self.cache_dir = self.data_dir / "cache"
        self.logs_dir = self.data_dir / "logs"
        
        self.cache_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database with learning tables"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS supplement_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                project_name TEXT,
                event_type TEXT,  -- 'generated', 'sent', 'response', 'outcome'
                status TEXT,      -- 'pending', 'approved', 'denied', 'partial'
                carrier TEXT,
                amount_requested REAL,
                amount_approved REAL DEFAULT 0,
                strategies_used TEXT,  -- JSON array
                event_data TEXT,       -- JSON blob
                context_data TEXT,     -- JSON blob
                event_timestamp TEXT,
                parent_event_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT,    -- 'carrier_behavior', 'strategy_success'
                context_key TEXT,     -- 'Allstate_steep_waste'
                pattern_data TEXT,    -- JSON with success rates, etc
                confidence_score REAL DEFAULT 0.0,
                sample_size INTEGER DEFAULT 0,
                discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                UNIQUE(pattern_type, context_key)
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplement_event_id INTEGER,
                strategy_name TEXT,
                trade_tag TEXT,
                strategy_amount REAL,
                outcome TEXT,         -- 'approved', 'denied', 'partial'
                approved_amount REAL DEFAULT 0,
                denial_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (supplement_event_id) REFERENCES supplement_events (id)
            )
        """)
        
        conn.commit()
        conn.close()
        
        logger.info(f"Learning database initialized: {self.db_path}")
    
    def track_supplement_generation(self, project_id: int, project_name: str, 
                                   carrier: str, strategies: List[str], 
                                   amount_requested: float) -> int:
        """Track when a supplement is generated"""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute("""
            INSERT INTO supplement_events 
            (project_id, project_name, event_type, status, carrier, 
             amount_requested, strategies_used, event_timestamp, event_data)
            VALUES (?, ?, 'generated', 'pending', ?, ?, ?, ?, ?)
        """, (
            project_id, project_name, carrier, amount_requested,
            json.dumps(strategies), datetime.now().isoformat(),
            json.dumps({
                'generated_at': datetime.now().isoformat(),
                'strategy_count': len(strategies)
            })
        ))
        
        event_id = cursor.lastrowid
        
        # Track individual strategies
        for strategy in strategies:
            conn.execute("""
                INSERT INTO strategy_outcomes 
                (supplement_event_id, strategy_name, outcome, strategy_amount)
                VALUES (?, ?, 'unknown', ?)
            """, (event_id, strategy, amount_requested / len(strategies)))
        
        conn.commit()
        conn.close()
        
        # Log to daily file
        self._log_event({
            'event_id': event_id,
            'type': 'generation',
            'project': project_name,
            'carrier': carrier,
            'strategies': strategies,
            'amount': amount_requested,
            'timestamp': datetime.now().isoformat()
        })
        
        logger.info(f"Tracked generation: {project_name} (ID: {event_id})")
        return event_id
    
    def track_insurance_response(self, event_id: int, approved_items: List[Dict],
                                denied_items: List[Dict], total_approved: float):
        """Track insurance response to a supplement"""
        conn = sqlite3.connect(self.db_path)
        
        # Update the main event
        status = self._determine_status(total_approved, event_id, conn)
        conn.execute("""
            UPDATE supplement_events 
            SET status = ?, amount_approved = ?, event_data = json_set(
                COALESCE(event_data, '{}'), 
                '$.response_received_at', ?
            )
            WHERE id = ?
        """, (status, total_approved, datetime.now().isoformat(), event_id))
        
        # Update strategy outcomes
        for item in approved_items:
            conn.execute("""
                UPDATE strategy_outcomes 
                SET outcome = 'approved', approved_amount = ?
                WHERE supplement_event_id = ? AND strategy_name = ?
            """, (item.get('amount', 0), event_id, item.get('strategy')))
        
        for item in denied_items:
            conn.execute("""
                UPDATE strategy_outcomes
                SET outcome = 'denied', denial_reason = ?
                WHERE supplement_event_id = ? AND strategy_name = ?
            """, (item.get('reason'), event_id, item.get('strategy')))
        
        conn.commit()
        conn.close()
        
        # Trigger pattern learning if we have enough new data
        self._maybe_update_patterns()
        
        logger.info(f"Tracked response for event {event_id}: {status}")
    
    def get_learned_patterns(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        """Get learned patterns for supplement generation"""
        patterns = {}
        
        # Load from cache first
        cache_file = self.cache_dir / f"{carrier.lower()}_insights.json"
        if cache_file.exists() and self._cache_is_fresh(cache_file):
            with open(cache_file) as f:
                cached = json.load(f)
                patterns.update(cached)
        else:
            # Generate fresh patterns
            patterns = self._generate_fresh_patterns(carrier, strategies)
            with open(cache_file, 'w') as f:
                json.dump(patterns, f)
        
        return patterns
    
    def _generate_fresh_patterns(self, carrier: str, strategies: List[str]) -> Dict[str, Any]:
        """Generate fresh learned patterns from database"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        patterns = {}
        
        # Carrier behavior pattern
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM supplement_events 
            WHERE carrier = ? AND event_type = 'generated' 
            AND created_at > date('now', '-90 days')
            GROUP BY status
        """, (carrier,))
        
        status_counts = dict(cursor.fetchall())
        total = sum(status_counts.values())
        
        if total >= 10:  # Minimum sample size
            denial_rate = (status_counts.get('denied', 0) / total) * 100
            patterns[f"{carrier}_behavior"] = {
                'denial_rate': denial_rate,
                'sample_size': total,
                'recommendation': 'conservative' if denial_rate > 60 else 'standard'
            }
        
        # Strategy success patterns  
        for strategy in strategies:
            cursor = conn.execute("""
                SELECT outcome, COUNT(*) as count
                FROM strategy_outcomes so
                JOIN supplement_events se ON so.supplement_event_id = se.id
                WHERE se.carrier = ? AND so.strategy_name = ?
                AND se.created_at > date('now', '-90 days')
                GROUP BY outcome
            """, (carrier, strategy))
            
            outcome_counts = dict(cursor.fetchall())
            total = sum(outcome_counts.values())
            
            if total >= 5:  # Minimum for strategy patterns
                success_count = outcome_counts.get('approved', 0) + outcome_counts.get('partial', 0)
                success_rate = (success_count / total) * 100
                
                if success_rate < 20:
                    recommendation = 'needs_better_approach'  # Not 'avoid'
                elif success_rate > 80:
                    recommendation = 'current_approach_working'
                else:
                    recommendation = 'standard_approach'
                
                patterns[f"{carrier}_{strategy}"] = {
                    'success_rate': success_rate,
                    'sample_size': total,
                    'recommendation': recommendation
                }
        
        conn.close()
        return patterns
    
    def _determine_status(self, approved_amount: float, event_id: int, conn) -> str:
        """Determine overall status from approval amount"""
        cursor = conn.execute(
            "SELECT amount_requested FROM supplement_events WHERE id = ?", 
            (event_id,)
        )
        requested = cursor.fetchone()[0]
        
        if approved_amount == 0:
            return 'denied'
        elif approved_amount >= requested * 0.95:
            return 'approved'
        else:
            return 'partial'
    
    def _log_event(self, event_data: Dict):
        """Log event to daily JSONL file"""
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.jsonl"
        
        with open(log_file, 'a') as f:
            f.write(json.dumps(event_data) + '\n')
    
    def _cache_is_fresh(self, cache_file: Path, max_age_hours: int = 12) -> bool:
        """Check if cache file is still fresh"""
        if not cache_file.exists():
            return False
        
        file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        return file_age < timedelta(hours=max_age_hours)
    
    def _maybe_update_patterns(self):
        """Update patterns if we have enough new data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT COUNT(*) FROM supplement_events 
            WHERE created_at > datetime('now', '-1 hour')
        """)
        recent_count = cursor.fetchone()[0]
        conn.close()
        
        if recent_count >= 3:  # Threshold for pattern updates
            logger.info("Triggering pattern update due to new data")
            self._update_all_patterns()
    
    def _update_all_patterns(self):
        """Update all learning patterns (background job equivalent)"""
        conn = sqlite3.connect(self.db_path)
        
        # Get all carriers with recent activity
        cursor = conn.execute("""
            SELECT DISTINCT carrier FROM supplement_events 
            WHERE created_at > date('now', '-90 days')
            AND carrier IS NOT NULL
        """)
        carriers = [row[0] for row in cursor.fetchall()]
        
        for carrier in carriers:
            self._update_carrier_patterns(carrier, conn)
        
        conn.close()
        
        # Clear cache to force fresh generation
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        
        logger.info(f"Updated patterns for {len(carriers)} carriers")
    
    def _update_carrier_patterns(self, carrier: str, conn):
        """Update patterns for a specific carrier"""
        # This would contain the full pattern discovery logic
        # Similar to the Rails PatternLearnerJob but in Python
        pass
    
    def get_insights_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get summary insights for dashboard"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # Overall success rate
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM supplement_events 
            WHERE created_at > date('now', '-{} days')
            GROUP BY status
        """.format(days))
        
        status_counts = dict(cursor.fetchall())
        total = sum(status_counts.values())
        
        success_rate = 0
        if total > 0:
            successful = status_counts.get('approved', 0) + status_counts.get('partial', 0)
            success_rate = (successful / total) * 100
        
        # Top strategies
        cursor = conn.execute("""
            SELECT so.strategy_name, 
                   AVG(CASE WHEN so.outcome IN ('approved', 'partial') THEN 1.0 ELSE 0.0 END) * 100 as success_rate,
                   COUNT(*) as attempts
            FROM strategy_outcomes so
            JOIN supplement_events se ON so.supplement_event_id = se.id
            WHERE se.created_at > date('now', '-{} days')
            GROUP BY so.strategy_name
            HAVING attempts >= 5
            ORDER BY success_rate DESC
            LIMIT 10
        """.format(days))
        
        top_strategies = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return {
            'summary': {
                'total_supplements': total,
                'success_rate': round(success_rate, 2),
                'time_period_days': days
            },
            'top_strategies': top_strategies,
            'generated_at': datetime.now().isoformat()
        }

# Global instance
learning_service = LearningService()