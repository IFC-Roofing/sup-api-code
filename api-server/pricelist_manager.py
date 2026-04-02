#!/usr/bin/env python3
"""
Pricelist Management System
Handles multiple pricelists with version consistency rules
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import sqlite3
from pathlib import Path

class PricelistManager:
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "learning.db"
        self._init_pricelist_tracking()
    
    def _init_pricelist_tracking(self):
        """Initialize pricelist tracking in database"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_pricelists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                project_name TEXT NOT NULL,
                supplement_version TEXT NOT NULL,  -- '1.0', '2.0', etc.
                pricelist_code TEXT NOT NULL,      -- 'TXDF8X_FEB26'
                pricelist_date TEXT,               -- '2026-02-15'
                selected_reason TEXT,              -- 'latest', 'consistency', 'manual_override'
                manual_override BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, supplement_version)
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS available_pricelists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pricelist_code TEXT UNIQUE NOT NULL,
                pricelist_date TEXT NOT NULL,       -- '2026-02-15'
                region TEXT DEFAULT 'TX',           -- 'TX', 'CA', etc.
                description TEXT,                   -- 'Texas February 2026'
                sheet_tab_name TEXT,                -- Sheet tab name
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def register_available_pricelist(self, code: str, date: str, region: str = 'TX', 
                                   description: str = None, sheet_tab: str = None):
        """Register a new pricelist as available"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO available_pricelists 
            (pricelist_code, pricelist_date, region, description, sheet_tab_name)
            VALUES (?, ?, ?, ?, ?)
        """, (code, date, region, description, sheet_tab))
        conn.commit()
        conn.close()
    
    def get_latest_pricelist(self, region: str = 'TX') -> Optional[str]:
        """Get the most recent pricelist for a region"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            SELECT pricelist_code FROM available_pricelists 
            WHERE region = ? AND is_active = 1
            ORDER BY pricelist_date DESC 
            LIMIT 1
        """, (region,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    
    def get_project_pricelist_history(self, project_id: int) -> List[Dict]:
        """Get all pricelist usage for a project"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM project_pricelists 
            WHERE project_id = ? 
            ORDER BY supplement_version
        """, (project_id,))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def select_pricelist_for_supplement(self, project_id: int, project_name: str, 
                                      version: str, manual_override: str = None,
                                      region: str = 'TX') -> Tuple[str, str]:
        """
        Select appropriate pricelist for a supplement
        Returns: (pricelist_code, selection_reason)
        """
        
        # Manual override takes precedence
        if manual_override:
            reason = f"manual_override: {manual_override}"
            self._track_pricelist_usage(
                project_id, project_name, version, manual_override, 
                reason, manual_override=True
            )
            return manual_override, reason
        
        # Check if this is version 1.0 (new project)
        if version == '1.0':
            latest_pricelist = self.get_latest_pricelist(region)
            if not latest_pricelist:
                # Fallback to current default
                latest_pricelist = "TXDF8X_FEB26"
            
            reason = "latest_available"
            self._track_pricelist_usage(
                project_id, project_name, version, latest_pricelist, reason
            )
            return latest_pricelist, reason
        
        # Version 2.0+ - use same pricelist as 1.0
        history = self.get_project_pricelist_history(project_id)
        v1_pricelist = None
        
        for record in history:
            if record['supplement_version'] == '1.0':
                v1_pricelist = record['pricelist_code']
                break
        
        if v1_pricelist:
            reason = "consistency_with_v1.0"
            self._track_pricelist_usage(
                project_id, project_name, version, v1_pricelist, reason
            )
            return v1_pricelist, reason
        else:
            # Fallback: no v1.0 found, use latest
            latest_pricelist = self.get_latest_pricelist(region)
            reason = "fallback_to_latest (no v1.0 found)"
            self._track_pricelist_usage(
                project_id, project_name, version, latest_pricelist, reason
            )
            return latest_pricelist, reason
    
    def _track_pricelist_usage(self, project_id: int, project_name: str, 
                              version: str, pricelist_code: str, reason: str,
                              manual_override: bool = False):
        """Track which pricelist was used for a supplement"""
        conn = sqlite3.connect(self.db_path)
        
        # Get pricelist date
        cursor = conn.execute("""
            SELECT pricelist_date FROM available_pricelists 
            WHERE pricelist_code = ?
        """, (pricelist_code,))
        result = cursor.fetchone()
        pricelist_date = result[0] if result else None
        
        conn.execute("""
            INSERT OR REPLACE INTO project_pricelists 
            (project_id, project_name, supplement_version, pricelist_code, 
             pricelist_date, selected_reason, manual_override)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (project_id, project_name, version, pricelist_code, 
              pricelist_date, reason, manual_override))
        conn.commit()
        conn.close()
    
    def get_pricelist_info(self, pricelist_code: str) -> Optional[Dict]:
        """Get information about a specific pricelist"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM available_pricelists 
            WHERE pricelist_code = ?
        """, (pricelist_code,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    def list_available_pricelists(self, region: str = None) -> List[Dict]:
        """List all available pricelists"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        if region:
            cursor = conn.execute("""
                SELECT * FROM available_pricelists 
                WHERE region = ? AND is_active = 1
                ORDER BY pricelist_date DESC
            """, (region,))
        else:
            cursor = conn.execute("""
                SELECT * FROM available_pricelists 
                WHERE is_active = 1
                ORDER BY region, pricelist_date DESC
            """)
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def setup_default_pricelists(self):
        """Setup some default pricelists for testing"""
        pricelists = [
            {
                'code': 'TXDF8X_JAN26',
                'date': '2026-01-15', 
                'description': 'Texas January 2026',
                'sheet_tab': 'TXDF8X_JAN26'
            },
            {
                'code': 'TXDF8X_FEB26',
                'date': '2026-02-15',
                'description': 'Texas February 2026', 
                'sheet_tab': 'TXDF8X_FEB26'
            },
            {
                'code': 'TXDF8X_MAR26',
                'date': '2026-03-15',
                'description': 'Texas March 2026',
                'sheet_tab': 'TXDF8X_MAR26'
            }
        ]
        
        for pl in pricelists:
            self.register_available_pricelist(
                pl['code'], pl['date'], 'TX', pl['description'], pl['sheet_tab']
            )

# Global instance
pricelist_manager = PricelistManager()

if __name__ == "__main__":
    # Test the system
    print("Setting up pricelist manager...")
    pricelist_manager.setup_default_pricelists()
    
    print("\nAvailable pricelists:")
    for pl in pricelist_manager.list_available_pricelists():
        print(f"  {pl['pricelist_code']}: {pl['description']} ({pl['pricelist_date']})")
    
    print(f"\nLatest pricelist: {pricelist_manager.get_latest_pricelist()}")
    
    # Test project scenarios
    print("\nTesting project scenarios:")
    
    # New project 1.0
    code, reason = pricelist_manager.select_pricelist_for_supplement(
        1001, "Test Project A", "1.0"
    )
    print(f"Project A v1.0: {code} ({reason})")
    
    # Same project 2.0
    code, reason = pricelist_manager.select_pricelist_for_supplement(
        1001, "Test Project A", "2.0" 
    )
    print(f"Project A v2.0: {code} ({reason})")
    
    # Manual override
    code, reason = pricelist_manager.select_pricelist_for_supplement(
        1001, "Test Project A", "3.0", manual_override="TXDF8X_JAN26"
    )
    print(f"Project A v3.0: {code} ({reason})")