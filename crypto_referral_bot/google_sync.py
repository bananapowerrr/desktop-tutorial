import asyncio
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv()

# Google Sheets authentication
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]
_creds_path = os.getenv("GOOGLE_CREDS_PATH")
if not _creds_path:
    raise ValueError("GOOGLE_CREDS_PATH is not set")
creds = ServiceAccountCredentials.from_json_keyfile_name(_creds_path, scope)
client = gspread.authorize(creds)

def get_sheet():
    """Get the Google Sheets document"""
    sheet_id = os.getenv("GOOGLE_SPREADSHEET_ID") or os.getenv("SHEET_ID")
    return client.open(sheet_id)

def get_worksheet(sheet_name=None):
    """Get a specific worksheet by name"""
    sheet = get_sheet()
    if sheet_name:
        return sheet.worksheet(sheet_name)
    return sheet.sheet1

def _get_row_sync(telegram_id):
    worksheet = get_worksheet()
    try:
        row = worksheet.find(str(telegram_id))
        return worksheet.row_values(row.row)
    except gspread.exceptions.CellNotFound:
        return None

async def get_row(telegram_id):
    return await asyncio.to_thread(_get_row_sync, telegram_id)

def _update_row_sync(telegram_id, data):
    worksheet = get_worksheet()
    try:
        row = worksheet.find(str(telegram_id))
        worksheet.update_cell(row.row, 1, str(telegram_id))
        for i, value in enumerate(data, start=2):
            worksheet.update_cell(row.row, i, value)
        return True
    except Exception as e:
        print(f"Error updating row: {str(e)}")
        return False

async def update_row(telegram_id, data):
    return await asyncio.to_thread(_update_row_sync, telegram_id, data)