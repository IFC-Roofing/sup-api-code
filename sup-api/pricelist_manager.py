#!/usr/bin/env python3
"""
Pricelist Manager — Simple audit trail for pricelist usage.
Logs which pricelist was active when each supplement was generated.

The actual pricelist lives in Google Sheets (tab: "Pricelist").
This module just tracks usage for consistency and audit purposes.
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import os
import logging

logger = logging.getLogger("sup-api.pricelist")

WORKSPACE = Path(os.environ.get("SUP_WORKSPACE", str(Path(__file__).parent.parent.parent)))
DATA_DIR = Path(os.environ.get("SUP_DATA_DIR", str(WORKSPACE / "data" / "learning")))


class PricelistManager:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "learning.db"
        self._init_table()

    def _init_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pricelist_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                project_name TEXT,
                supplement_version TEXT,
                generated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def track_usage(self, project_id: int, project_name: str, version: str = "1.0"):
        """Log that a supplement was generated using the active pricelist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO pricelist_usage (project_id, project_name, supplement_version, generated_at)
            VALUES (?, ?, ?, ?)
        """, (project_id, project_name, version, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        logger.info(f"Pricelist usage logged: {project_name} v{version}")

    def get_project_history(self, project_id: int) -> List[Dict]:
        """Get pricelist usage history for a project."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM pricelist_usage
            WHERE project_id = ?
            ORDER BY generated_at DESC
        """, (project_id,))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results


pricelist_manager = PricelistManager()
