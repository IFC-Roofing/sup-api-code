"""
log_decision.py — Append a supplement decision to the Decisions Log Google Sheet.

Usage:
  python log_decision.py "Rose Brock" 5128 "fence" "Drop fence - NRD too high, not worth fighting" "John Merrifield"
  python log_decision.py "Nick Schmidt" 5054 "O&P" "Accept denial, not complex enough for appraisal" "David Davis"

Args:
  1. Project Name
  2. Project ID
  3. Trade (fence, O&P, gutters, roof, garage, chimney, solar, general, etc.)
  4. Decision description
  5. Who gave the order (name)
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Config
WORKSPACE = Path(__file__).resolve().parent.parent.parent
CREDS_PATH = WORKSPACE / "google-drive-key.json"
SHEET_ID = "1QLeEHPr1mmhJfKqC7rgTlirmBXN3618d_77yK4jrW_8"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        str(CREDS_PATH).with_subject('sup@ifcroofing.com'), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def log_decision(project_name: str, project_id: int, trade: str, decision: str, ordered_by: str, logged_in_convo: str = "Pending"):
    """Append a decision row to the Google Sheet."""
    sheets = get_sheets_service()
    
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    row = [date_str, project_name, str(project_id), trade, decision, ordered_by, logged_in_convo]
    
    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range="Sheet1!A:G",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]}
    ).execute()
    
    print(f"✅ Decision logged: {project_name} | {trade} | {decision} | by {ordered_by}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: python log_decision.py <project_name> <project_id> <trade> <decision> <ordered_by>")
        sys.exit(1)
    
    log_decision(
        project_name=sys.argv[1],
        project_id=int(sys.argv[2]),
        trade=sys.argv[3],
        decision=sys.argv[4],
        ordered_by=sys.argv[5],
    )
