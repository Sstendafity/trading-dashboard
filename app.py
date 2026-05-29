import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import os
import datetime
import re
from github import Github
from auth import check_password

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Pro Trading Dashboard", layout="wide")

# if not check_password():
#     st.stop()  # Stop rendering the rest of the app

MASTER_DB = "trade_history.csv"

# --- CONFIGURATION FOR GITHUB ---
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard" 

# --- CUSTOM CSS ---
st.markdown("""
    <style>
    .metric-card {
        background-color: #f9f9f9;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-label {
        font-size: 14px;
        color: #666;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 24px;
        font-weight: bold;
    }
    .green-text { color: #2ca02c; }
    .red-text { color: #d62728; }
    .normal-text { color: #333; }
    div.stButton > button:first-child {
        height: 2em;
        padding-top: 0px;
        padding-bottom: 0px;
    }
    </style>
""", unsafe_allow_html=True)

# --- HELPER FUNCTIONS ---
def custom_metric(label, value, color_condition="normal"):
    color_class = "normal-text"
    if color_condition == "green": color_class = "green-text"
    elif color_condition == "red": color_class = "red-text"
    html = f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value {color_class}">{value}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

# --- GITHUB SYNC FUNCTION ---
def update_github_repo(csv_content):
    if not GITHUB_TOKEN or "your-username" in REPO_NAME:
        st.warning("⚠️ GitHub Token or Repo Name not configured properly in code!")
        return False
        
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        try:
            contents = repo.get_contents(MASTER_DB)
            repo.update_file(contents.path, "Update trade history via App", csv_content, contents.sha)
        except:
            repo.create_file(MASTER_DB, "Create trade history via App", csv_content)
        return True
    except Exception as e:
        st.error(f"GitHub Sync Failed: {e}")
        return False

# ==========================================
# 1. DATABASE & PROCESSING ENGINE
# ==========================================

def load_master_db():
    if os.path.exists(MASTER_DB):
        try:
            db = pd.read_csv(MASTER_DB)
            if 'Account' in db.columns:
                db['Account'] = db['Account'].astype(str).apply(lambda x: re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', x.strip()))
            
            # --- CHANGE: Normalize 'Side' terminology instantly ---
            if 'Side' in db.columns:
                side_map = {'buy': 'Long', 'long': 'Long', 'sell': 'Short', 'short': 'Short', 'unknown': 'Unknown'}
                db['Side'] = db['Side'].astype(str).str.lower().map(side_map).fillna('Unknown')
                
            return db
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame(columns=['Account', 'Date', 'Time', 'Contract', 'Side', 'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'])

def save_to_master(new_df):
    if os.path.exists(MASTER_DB):
        old_df = pd.read_csv(MASTER_DB)
    else:
        old_df = pd.DataFrame()

    # ADD THESE TWO LINES — deduplicate columns before concat
    old_df = old_df.loc[:, ~old_df.columns.duplicated()]
    new_df = new_df.loc[:, ~new_df.columns.duplicated()]

    combined = pd.concat([old_df, new_df], ignore_index=True)
    
    # --- ADD THIS: Normalize Account Names before saving (A6 -> A-6) ---
    if 'Account' in combined.columns:
        combined['Account'] = combined['Account'].astype(str).apply(lambda x: re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', x.strip()))
        
    # --- CHANGE: Normalize 'Side' terminology before saving ---
    if 'Side' in combined.columns:
        side_map = {'buy': 'Long', 'long': 'Long', 'sell': 'Short', 'short': 'Short', 'unknown': 'Unknown'}
        combined['Side'] = combined['Side'].astype(str).str.lower().map(side_map).fillna('Unknown')
    
    if 'Date' in combined.columns:
        def fix_date_time(row):
            d = str(row['Date']).strip()
            t = str(row['Time']).strip() if pd.notna(row['Time']) else ''

            # Case 1: datetime embedded in Date (e.g. "2026-02-19 17:20:23.071065")
            if ' ' in d and '-' in d:
                dt = datetime.datetime.fromisoformat(d)
                return pd.Series({'Date': dt.strftime('%Y-%m-%d'), 'Time': dt.strftime('%H:%M:%S')})

            # Case 2: DD/MM/YYYY → YYYY-MM-DD
            if '/' in d:
                dt = datetime.datetime.strptime(d, "%d/%m/%Y")
                return pd.Series({'Date': dt.strftime('%Y-%m-%d'), 'Time': t})

            # Case 3: already YYYY-MM-DD, keep as-is
            return pd.Series({'Date': d, 'Time': t})

        fixed = combined.apply(fix_date_time, axis=1)
        combined['Date'] = fixed['Date']
        combined['Time'] = fixed['Time']

    if 'Order ID' in combined.columns:
        combined['Order ID'] = combined['Order ID'].astype(str)
        combined = combined.drop_duplicates(subset=['Order ID'], keep='last')

    combined.to_csv(MASTER_DB, index=False)
    csv_str = combined.to_csv(index=False)
    success = update_github_repo(csv_str)
    
    return combined, success

def process_pnl_statement(df, filename):
    """Logic for the new P&L Statement format"""
    
    # 1. Account Name from Filename (Simple & Robust)
    account_name = filename.split()[0]
            
    # Clean & Transform
    df['dt'] = pd.to_datetime(df['Date & Time'], dayfirst=True, errors='coerce')
    df['Date'] = df['dt'].dt.date
    df['Time'] = df['dt'].dt.time.astype(str)
    
    df['Order ID'] = df['Trade ID'].astype(str)
    df['Contract'] = df['Symbol']
    df['Side'] = df['Side'].str.lower()
    
    # Dynamic Rate
    if 'USDT-INR Rate' in df.columns:
        df['Rate'] = pd.to_numeric(df['USDT-INR Rate'], errors='coerce').fillna(0)
    else:
        df['Rate'] = 0 

    # P&L Calculation
    df['P&L_INR_Raw'] = pd.to_numeric(df['Actual Realised P&L (in INR)'], errors='coerce')
    df['P&L_USDT'] = pd.to_numeric(df['Notional Realised P&L (in USDT)'], errors='coerce')
    
    df['Realised P&L(INR)'] = df['P&L_INR_Raw']
    # Fill missing INR values using USDT * Rate
    mask_pnl = df['Realised P&L(INR)'].isna()
    df.loc[mask_pnl, 'Realised P&L(INR)'] = df.loc[mask_pnl, 'P&L_USDT'] * df.loc[mask_pnl, 'Rate']
    df['Realised P&L(INR)'] = df['Realised P&L(INR)'].fillna(0)

    # Fees Calculation
    fee_inr = pd.to_numeric(df['Actual Trading Fee (in INR)'], errors='coerce').fillna(0)
    gst_inr = pd.to_numeric(df['GST(18%)'], errors='coerce').fillna(0)
    df['Trading Fees(INR)'] = fee_inr + gst_inr
    
    df['Status'] = 'closed'
    df['Account'] = account_name
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    return df[target_cols]
def process_zebpay_format(df, filename):
    """Logic for ZebPay TXNHISTORY_STATEMENT format (A-15)"""
    account_name = filename.split()[0].replace('.xlsx', '').replace('.csv', '')
    account_name = re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', account_name)

    # Only process rows that belong to an actual trade (have a Trade ID)
    df = df[df['Trade ID'].notna()].copy()

    # Parse datetime — Time column has format "14:45:05.251Z"
    df['dt'] = pd.to_datetime(
        df['Date'].astype(str) + ' ' + df['Time (in UTC)'].astype(str).str.replace('Z', '', regex=False),
        errors='coerce'
    )

    # Pivot: for each Trade ID, extract P&L and fees
    pnl = (
        df[df['Type'] == 'REALIZED_PNL']
        .groupby('Trade ID')
        .agg(
            Date=('dt', 'first'),
            Symbol=('Symbol', 'first'),
            PnL=('Amount', 'sum')
        )
        .reset_index()
    )

    fees = (
        df[df['Type'].isin(['COMMISSION', 'GST_ON_COMMISSION'])]
        .groupby('Trade ID')['Amount']
        .sum()
        .abs()  # stored as negatives, flip to positive
        .reset_index()
        .rename(columns={'Amount': 'Fees'})
    )

    result = pnl.merge(fees, on='Trade ID', how='left')
    result['Fees'] = result['Fees'].fillna(0)

    # WITH this — avoid the duplicate Date column entirely
    result['Account'] = account_name
    result['Time'] = result['Date'].dt.strftime('%H:%M:%S')
    result['Date'] = result['Date'].dt.strftime('%Y-%m-%d')  # overwrite in place
    result['Order ID'] = result['Trade ID'].astype(int).astype(str)
    result['Contract'] = result['Symbol']
    result['Side'] = 'Unknown'
    result['Status'] = 'closed'
    result['Realised P&L(INR)'] = result['PnL']
    result['Trading Fees(INR)'] = result['Fees']

    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side',
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    return result[target_cols]

def process_future_position_history(df, filename):
    """Logic for the new A5 Future Position history format"""
    # Clean Account Name (e.g., "A5.xlsx" -> "A5")
    account_name = filename.split()[0].replace('.xlsx', '').replace('.csv', '')
    
    df['dt'] = pd.to_datetime(df['Exit Time (IST)'], errors='coerce')
    df = df.dropna(subset=['dt']).copy()
    
    df['Date'] = df['dt'].dt.date
    df['Time'] = df['dt'].dt.time.astype(str)
    
    df['Order ID'] = df['Symbol'] + "_" + df['Exit Time (IST)'].astype(str)
    df['Contract'] = df['Symbol']
    
    # Calculate Side (LONG if (Exit-Entry)*PNL > 0, else SHORT)
    df['Side'] = np.where((df['Exit Price (USDT)'] - df['Entry Price (USDT)']) * df['Realized PNL (USDT)'] >= 0, 'long', 'short')
    
    # Apply Rate
    usd_to_inr = 90.96
    df['Realised P&L(INR)'] = df['Realized PNL (USDT)'] * usd_to_inr
    
    # Estimate Fees: 0.05% standard transaction fee applied to Entry & Exit
    df['Trading Fees(INR)'] = (df['Quantity'] * (df['Entry Price (USDT)'] + df['Exit Price (USDT)']) * 0.0005) * usd_to_inr
    
    df['Status'] = 'closed'
    df['Account'] = account_name
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    return df[target_cols]

def process_a4_format(df, filename):
    """Logic for the new A-4 Trades file format"""
    # Standardize Account Name (e.g. A4 -> A-4)
    account_name = filename.split()[0].replace('.xlsx', '').replace('.csv', '')
    account_name = re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', account_name)
    
    # Clean Dates using Executed At
    df['dt'] = pd.to_datetime(df['Executed At'], errors='coerce')
    df = df.dropna(subset=['dt']).copy()
    
    df['Date'] = df['dt'].dt.date
    df['Time'] = df['dt'].dt.time.astype(str)
    
    df['Order ID'] = df['Trade ID'].astype(str)
    df['Contract'] = df['Coin'].astype(str).str.upper() # e.g., 'btc' -> 'BTC'
    df['Side'] = df['Side'].astype(str)
    
    # Financials (Already in INR, no conversion needed)
    df['Realised P&L(INR)'] = pd.to_numeric(df['Realised P&L'], errors='coerce').fillna(0)
    df['Trading Fees(INR)'] = pd.to_numeric(df['Commission'], errors='coerce').fillna(0)
    
    df['Status'] = 'closed'
    df['Account'] = account_name
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    return df[target_cols]

def process_coindcx_future(df, filename):
    """Logic for the new A6 CoinDCX Future Orders format"""
    account_name = filename.split()[0].replace('.xlsx', '').replace('.csv', '')
    
    # Clean Dates
    df['dt'] = pd.to_datetime(df['Transaction time'], errors='coerce')
    df = df.dropna(subset=['dt']).copy()
    
    df['Date'] = df['dt'].dt.date
    df['Time'] = df['dt'].dt.time.astype(str)
    
    df['Order ID'] = df['Transaction ID'].astype(str)
    # Clean up contract names (e.g. "B-BTC_USDT" -> "BTC_USDT")
    df['Contract'] = df['Crypto Pair'].str.replace('B-', '', regex=False)
    
    # FIX FOR MISSING SIDE: Default to unknown
    df['Side'] = 'unknown'
    
    # Financials (CoinDCX provides INR directly)
    df['Realised P&L(INR)'] = pd.to_numeric(df['Gross P&L for this transaction(in INR)'], errors='coerce').fillna(0)
    df['Trading Fees(INR)'] = pd.to_numeric(df['Fees(in INR)'], errors='coerce').fillna(0)
    
    df['Status'] = 'closed'
    df['Account'] = account_name
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    return df[target_cols]

def process_gts_format(df, filename):
    """Logic for GTS (Giottus) transaction_history format (A-16)"""
    account_name = filename.split()[0].replace('.csv', '').replace('.xlsx', '')
    account_name = re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', account_name)

    USD_TO_INR = 85.0

    # Parse datetime
    df['dt'] = pd.to_datetime(df['Time'], errors='coerce')
    df = df.dropna(subset=['dt']).copy()

    # Convert Amount to numeric (handles +/- signs and scientific notation)
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
    df['Total Commission'] = pd.to_numeric(df['Total Commission'], errors='coerce').fillna(0)

    # ==========================================
    # 1. REALIZED PNL TRADES (grouped by Order-Id)
    # ==========================================
    trades = df[
        (df['Type'] == 'Realized PNL') &
        (df['Order-Id'].notna()) &
        (df['Order-Id'].astype(str).str.strip() != '')
    ].copy()

    if not trades.empty:
        trade_pnl = (
            trades.groupby('Order-Id')
            .agg(
                dt=('dt', 'first'),
                Symbol=('Symbol', 'first'),
                PnL_USDT=('Amount', 'sum'),
            )
            .reset_index()
        )

        # Get commissions for same Order-Id
        commissions = df[
            (df['Type'] == 'Commission') &
            (df['Order-Id'].notna()) &
            (df['Order-Id'].astype(str).str.strip() != '')
        ].copy()
        commissions['Total Commission'] = pd.to_numeric(
            commissions['Total Commission'], errors='coerce'
        ).fillna(0)
        fee_by_order = (
            commissions.groupby('Order-Id')['Total Commission']
            .sum()
            .abs()
            .reset_index()
            .rename(columns={'Total Commission': 'Fees_USDT'})
        )

        result = trade_pnl.merge(fee_by_order, on='Order-Id', how='left')
        result['Fees_USDT'] = result['Fees_USDT'].fillna(0)

        result['Realised P&L(INR)'] = result['PnL_USDT'] * USD_TO_INR
        result['Trading Fees(INR)'] = result['Fees_USDT'] * USD_TO_INR
        result['Order ID'] = result['Order-Id'].astype(str)
        result['Contract'] = result['Symbol']
        result['Side'] = 'Unknown'
        result['Status'] = 'closed'
        result['Account'] = account_name
        result['Date'] = result['dt'].dt.strftime('%Y-%m-%d')
        result['Time'] = result['dt'].dt.strftime('%H:%M:%S')

        trade_rows = result[[
            'Account', 'Date', 'Time', 'Contract', 'Side',
            'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'
        ]]
    else:
        trade_rows = pd.DataFrame(columns=[
            'Account', 'Date', 'Time', 'Contract', 'Side',
            'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'
        ])

    # ---- Funding fees ----
    funding = df[df['Type'] == 'Funding Fee'].copy()
    if not funding.empty:
        funding['Realised P&L(INR)'] = funding['Amount'] * USD_TO_INR
        funding['Trading Fees(INR)'] = 0.0
        funding['Order ID'] = (
            funding['Symbol'].astype(str) + '_funding_' +
            funding['dt'].dt.strftime('%Y%m%d%H%M%S')
        )
        funding['Contract'] = funding['Symbol']
        funding['Side'] = 'Unknown'
        funding['Status'] = 'closed'
        funding['Account'] = account_name
        funding['Date'] = funding['dt'].dt.strftime('%Y-%m-%d')
        funding['Time'] = funding['dt'].dt.strftime('%H:%M:%S')
        funding_rows = funding[['Account', 'Date', 'Time', 'Contract', 'Side',
                                'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']]
    else:
        funding_rows = pd.DataFrame(columns=['Account', 'Date', 'Time', 'Contract', 'Side',
                                            'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'])

    return trade_rows

def process_binance_format(df, filename):
    """Logic for Binance Futures Transaction History format (A-17)
    Columns: Time, Type, Amount, Asset, Symbol, Transaction ID
    (plus unnamed filler columns from Excel export)
    Types: REALIZED_PNL, COMMISSION, FUNDING_FEE, TRANSFER
    Values in USDT — convert at 85 INR/USDT
    Date format: YY-MM-DD HH:MM:SS
    """
    account_name = filename.split()[0].replace('.xlsx', '').replace('.csv', '')
    account_name = re.sub(r'^([a-zA-Z]+)(\d+)$', r'\1-\2', account_name)
 
    USD_TO_INR = 85.0
 
    # Drop unnamed filler columns (Excel export artifact)
    df = df[[c for c in df.columns if 'Unnamed' not in str(c)]].copy()
 
    # Parse datetime — format is YY-MM-DD HH:MM:SS
    df['dt'] = pd.to_datetime(df['Time'], format='%y-%m-%d %H:%M:%S', errors='coerce')
    # Fallback for other formats
    mask_failed = df['dt'].isna()
    if mask_failed.any():
        df.loc[mask_failed, 'dt'] = pd.to_datetime(
            df.loc[mask_failed, 'Time'], errors='coerce'
        )
    df = df.dropna(subset=['dt']).copy()
 
    df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0)
    df['Transaction ID'] = df['Transaction ID'].astype(str).str.strip()
 
    # ---- Realized PNL trades (grouped by Transaction ID) ----
    trades = df[
        (df['Type'] == 'REALIZED_PNL') &
        (df['Transaction ID'].notna()) &
        (df['Transaction ID'] != '') &
        (df['Transaction ID'] != 'nan')
    ].copy()
 
    if not trades.empty:
        trade_pnl = (
            trades.groupby('Transaction ID')
            .agg(dt=('dt', 'first'), Symbol=('Symbol', 'first'), PnL_USDT=('Amount', 'sum'))
            .reset_index()
        )
        commissions = df[
            (df['Type'] == 'COMMISSION') &
            (df['Transaction ID'].notna()) &
            (df['Transaction ID'] != '') &
            (df['Transaction ID'] != 'nan')
        ].copy()
        fee_by_txn = (
            commissions.groupby('Transaction ID')['Amount']
            .sum().abs().reset_index()
            .rename(columns={'Amount': 'Fees_USDT'})
        )
        result = trade_pnl.merge(fee_by_txn, on='Transaction ID', how='left')
        result['Fees_USDT'] = result['Fees_USDT'].fillna(0)
        result['Realised P&L(INR)'] = result['PnL_USDT'] * USD_TO_INR
        result['Trading Fees(INR)'] = result['Fees_USDT'] * USD_TO_INR
        result['Order ID'] = result['Transaction ID'].astype(str)
        result['Contract'] = result['Symbol'].astype(str).str.replace('USDT', '/USDT', regex=False)
        result['Side'] = 'Unknown'
        result['Status'] = 'closed'
        result['Account'] = account_name
        result['Date'] = result['dt'].dt.strftime('%Y-%m-%d')
        result['Time'] = result['dt'].dt.strftime('%H:%M:%S')
        trade_rows = result[['Account', 'Date', 'Time', 'Contract', 'Side',
                              'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']]
    else:
        trade_rows = pd.DataFrame(columns=['Account', 'Date', 'Time', 'Contract', 'Side',
                                           'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'])
 
    # ---- Funding fees ----
    funding = df[df['Type'] == 'FUNDING_FEE'].copy()
    if not funding.empty:
        funding['Realised P&L(INR)'] = funding['Amount'] * USD_TO_INR
        funding['Trading Fees(INR)'] = 0.0
        funding['Order ID'] = (
            funding['Symbol'].astype(str) + '_funding_' +
            funding['dt'].dt.strftime('%Y%m%d%H%M%S') + '_' +
            funding['Transaction ID'].astype(str)
        )
        funding['Contract'] = funding['Symbol'].astype(str).str.replace('USDT', '/USDT', regex=False)
        funding['Side'] = 'Unknown'
        funding['Status'] = 'closed'
        funding['Account'] = account_name
        funding['Date'] = funding['dt'].dt.strftime('%Y-%m-%d')
        funding['Time'] = funding['dt'].dt.strftime('%H:%M:%S')
        funding_rows = funding[['Account', 'Date', 'Time', 'Contract', 'Side',
                                 'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']]
    else:
        funding_rows = pd.DataFrame(columns=['Account', 'Date', 'Time', 'Contract', 'Side',
                                              'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'])
 
    return pd.concat([trade_rows, funding_rows], ignore_index=True)

def process_legacy_csv(df, filename):
    """Logic for the original CSV format"""
    # Safety check: if it's a random file (like deposits), ignore it
    if 'Time' not in df.columns or 'Realised P&L' not in df.columns:
        return pd.DataFrame()

    if 'Status' in df.columns:
        df = df[df['Status'] == 'closed'].copy()
    
    temp_dt = df['Time'].astype(str).str.split(' IST').str[0]
    temp_dt = pd.to_datetime(temp_dt, errors='coerce')
    
    df = df[temp_dt.notna()].copy()
    df['Date'] = temp_dt[temp_dt.notna()].dt.date
    df['Time'] = temp_dt[temp_dt.notna()].dt.time.astype(str)
    
    fixed_conversion_rate = 85.0
    
    df['Realised P&L(INR)'] = df['Realised P&L'] * fixed_conversion_rate
    df['Trading Fees(INR)'] = df['Trading Fees'] * fixed_conversion_rate
        
    df['Account'] = filename.split()[0]
    
    if 'Order ID' in df.columns:
        df['Order ID'] = df['Order ID'].astype(str)
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    available_cols = [c for c in target_cols if c in df.columns]
    return df[available_cols]

def normalize_raw_data(file):
    is_excel = False
    if file.name.endswith(('.xlsx', '.xls')):
        is_excel = True
    else:
        try:
            file.seek(0)
            file.readline().decode('utf-8')
            file.seek(0)
        except UnicodeDecodeError:
            is_excel = True
            file.seek(0)

    if is_excel:
        try:
            xl = pd.ExcelFile(file)
            # 1. Check A-4 format (Excel) - Look for specific sheet
            if 'Trades' in xl.sheet_names:
                df = xl.parse('Trades')
                # A4 files seem clean, headers on line 0
                return process_a4_format(df, file.name)
            
            # 2. Check A5 format (Excel)
            if 'Future Position history' in xl.sheet_names:
                df = xl.parse('Future Position history')
                return process_future_position_history(df, file.name)
        
            # ADD THIS — ZebPay format
            if 'TXNHISTORY_STATEMENT' in xl.sheet_names:
                df = xl.parse('TXNHISTORY_STATEMENT')
                return process_zebpay_format(df, file.name)
            
            # Binance format (A-17) — detect by sheet name or column signature
            if 'Sheet0' in xl.sheet_names:
                df = xl.parse('Sheet0')
                df_clean = df[[c for c in df.columns if 'Unnamed' not in str(c)]]
                if 'Transaction ID' in df_clean.columns and 'Type' in df_clean.columns:
                    if df_clean['Type'].isin(['REALIZED_PNL', 'COMMISSION', 'FUNDING_FEE', 'TRANSFER']).any():
                        return process_binance_format(df, file.name)
                    
            # Signature checks for other formats
            df_peek = pd.read_excel(file, header=None, nrows=15)
            file.seek(0)
            
            # 3. Check A6 CoinDCX format
            for i in range(len(df_peek)):
                row_str = " ".join(df_peek.iloc[i].astype(str).fillna(""))
                if "Transaction ID" in row_str and "Crypto Pair" in row_str:
                    df = pd.read_excel(file, skiprows=i)
                    return process_coindcx_future(df, file.name)
            
            # 4. Check A4 P&L format (Legacy header skip)
            first_cell = str(df_peek.iloc[0, 0])
            if "P&L Statement" in first_cell:
                df = pd.read_excel(file, skiprows=13)
                return process_pnl_statement(df, file.name)
            else:
                df = pd.read_excel(file)
                return process_legacy_csv(df, file.name)
        except Exception:
            return pd.DataFrame()
    else:
        try:
            file.seek(0)
            lines = [file.readline().decode('utf-8', errors='ignore') for _ in range(15)]
            file.seek(0)

            first_line = lines[0]
            # 0. Check Binance format (A-16) — detect by column headers
            if "Order-Id" in first_line and "Realized PNL" in first_line or "Total Commission" in first_line:
                df = pd.read_csv(file)
                return process_gts_format(df, file.name)
            
            # 1. Check A6 CoinDCX format in CSV
            coindcx_skip = -1
            for i, line in enumerate(lines):
                if "Transaction ID" in line and "Crypto Pair" in line:
                    coindcx_skip = i
                    break
            if coindcx_skip >= 0:
                df = pd.read_csv(file, skiprows=coindcx_skip)
                return process_coindcx_future(df, file.name)
            
            # 2. Check A-4 format (CSV) - Look for columns specific to Trades file
            if "Trade ID" in first_line and "Commission" in first_line:
                df = pd.read_csv(file)
                return process_a4_format(df, file.name)
                
            # 3. Check A5 format in CSV
            if "Exit Time (IST)" in first_line and "Realized PNL" in first_line:
                df = pd.read_csv(file)
                return process_future_position_history(df, file.name)
            # 4. Check A4 format in CSV (Legacy header skip)
            elif "P&L Statement" in first_line:
                df = pd.read_csv(file, skiprows=13)
                return process_pnl_statement(df, file.name)
            else:
                df = pd.read_csv(file)
                return process_legacy_csv(df, file.name)
        except Exception:
            return pd.DataFrame()

# ==========================================
# 2. UI & LAYOUT
# ==========================================

st.title("📈 Pro Trading Dashboard (Live)")

df = load_master_db()

# --- SIDEBAR (UPLOAD & SYNC) ---
with st.sidebar:
    st.header("1. Upload Data")
    uploaded_files = st.file_uploader("Drop Files Here", accept_multiple_files=True)
    if uploaded_files:
        if st.button("Update Database"):
            new_data_list = []
            for f in uploaded_files:
                try:
                    clean_df = normalize_raw_data(f)
                    if not clean_df.empty:
                        new_data_list.append(clean_df)
                except Exception as e:
                    st.error(f"Error reading {f.name}: {e}")
            if new_data_list:
                full_new_data = pd.concat(new_data_list)
                _, success = save_to_master(full_new_data)
                
                if success:
                    st.success("✅ Database Updated & Saved to Cloud!")
                else:
                    st.warning("⚠️ Saved locally, but Cloud Sync failed.")
                
                st.rerun()

# --- FILTER SECTION ---
df_filtered = pd.DataFrame() 

if not df.empty:
    # --- CRITICAL FIX: Handle Mixed Date Formats ---
    # This prevents the "ValueError: time data doesn't match format" error
    df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%d', errors='coerce')
    df = df.dropna(subset=['Date'])
    
    if df['Date'].notna().any():
        min_d = df['Date'].min().date()
        max_d = max(df['Date'].max().date(), datetime.date.today()) 
    else:
        min_d = datetime.date.today()
        max_d = datetime.date.today()
    
    # --- CHANGE: Define Unlocked Calendar Range ---
    # This allows the UI to go back to 2024, even if your data starts in 2025
    calendar_min = datetime.date(2024, 1, 1) 
    calendar_max = max_d

    all_accounts = df['Account'].unique().tolist()
    all_contracts = df['Contract'].unique().tolist()
    all_sides = df['Side'].unique().tolist()
    timeframes = ["Daily", "Weekly", "Monthly", "Yearly"]

    if 'f_date' not in st.session_state: st.session_state['f_date'] = (min_d, max_d) # Default: All Time Data
    if 'f_acc' not in st.session_state: st.session_state['f_acc'] = all_accounts
    if 'f_con' not in st.session_state: st.session_state['f_con'] = all_contracts
    if 'f_side' not in st.session_state: st.session_state['f_side'] = all_sides
    if 'f_freq' not in st.session_state: st.session_state['f_freq'] = "Daily"

    # --- CHANGE: Sanitize using CALENDAR limits, not DATA limits ---
    current_val = st.session_state['f_date']
    if isinstance(current_val, tuple) and len(current_val) == 2:
        start_val, end_val = current_val
        # Prevent crash by ensuring values are within the UI limits
        valid_start = max(start_val, calendar_min)
        valid_end = min(end_val, calendar_max)
        if valid_start > valid_end: valid_start = valid_end
        st.session_state['f_date'] = (valid_start, valid_end)

    with st.expander("🛠️ Filter Options (Click to Expand)", expanded=False):
        
        k1, k2 = st.columns([1, 4])
        with k1:
             if st.button("🔄 Reset All", use_container_width=True):
                st.session_state['f_date'] = (min_d, max_d)
                st.session_state['f_acc'] = all_accounts
                st.session_state['f_con'] = all_contracts
                st.session_state['f_side'] = all_sides
                st.session_state['f_freq'] = "Daily"
                st.rerun()
        
        st.markdown("---") 
        
        st.write("**Quick Date Ranges:**")
        today = datetime.date.today()
        
        # Update this function to use calendar_min
        def set_date_range(start, end):
            safe_start = max(start, calendar_min) # <--- Changed from min_d
            safe_end = min(end, calendar_max)
            if safe_start > safe_end: safe_start = safe_end
            st.session_state['f_date'] = (safe_start, safe_end)
            st.rerun()

        r1_col1, r1_col2, r1_col3 = st.columns(3)
        if r1_col1.button("📅 Today", use_container_width=True):
            set_date_range(today, today)
        if r1_col2.button("⏪ Yesterday", use_container_width=True):
            yesterday = today - datetime.timedelta(days=1)
            set_date_range(yesterday, yesterday)
        if r1_col3.button("📆 This Week", use_container_width=True):
            start = today - datetime.timedelta(days=today.weekday())
            set_date_range(start, today)
            
        r2_col1, r2_col2, r2_col3 = st.columns(3)
        if r2_col1.button("🗓️ This Month", use_container_width=True):
            start = today.replace(day=1)
            set_date_range(start, today)
        if r2_col2.button("📅 This Year", use_container_width=True):
            start = today.replace(month=1, day=1)
            set_date_range(start, today)
        if r2_col3.button("∞ All Time", use_container_width=True):
            st.session_state['f_date'] = (min_d, max_d)
            st.rerun()

        st.markdown("---") 
            
        c1, c2 = st.columns([1, 2])
        with c1:
            # --- FIX: SPLIT START & END DATE WIDGETS ---
            # Unpack the current values DIRECTLY from session state
            curr_start, curr_end = st.session_state['f_date']
            
            # Create two small columns side-by-side
            d_col1, d_col2 = st.columns(2)
            
            with d_col1:
                # Note: No 'key' here. We handle state manually below.
                new_start = st.date_input("Start Date", 
                                          value=curr_start,
                                          min_value=calendar_min,
                                          max_value=calendar_max)
            with d_col2:
                new_end = st.date_input("End Date", 
                                        value=curr_end,
                                        min_value=calendar_min,
                                        max_value=calendar_max)
            
            # Safety: Ensure Start isn't after End
            if new_start > new_end:
                new_start = new_end
            
            # Update the main session state so the rest of the app works
            st.session_state['f_date'] = (new_start, new_end)

            st.selectbox("Timeframe Aggregation", timeframes, key='f_freq')
        with c2:
            st.multiselect("Account", all_accounts, key='f_acc')
            st.multiselect("Contract", all_contracts, key='f_con')
            st.multiselect("Side", all_sides, key='f_side')

    date_range = st.session_state['f_date']
    
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
        mask = (
            df['Account'].isin(st.session_state['f_acc']) & 
            df['Contract'].isin(st.session_state['f_con']) & 
            df['Side'].isin(st.session_state['f_side']) &
            (df['Date'].dt.date >= start_date) &
            (df['Date'].dt.date <= end_date)
        )
        df_filtered = df[mask].copy()
    else:
        df_filtered = df.copy() 
else:
    df_filtered = pd.DataFrame()

# --- DASHBOARD CONTENT ---

if df_filtered.empty:
    if not df.empty:
        st.info("ℹ️ No trades found for the selected date range.")
    else:
        st.info("👋 No data found. Please run 'migrate.py' or upload files.")
else:
    # --- CHART PREP (THE FIX) ---
    raw_ts = df_filtered['Date'].astype(str) + ' ' + df_filtered['Time'].astype(str)
    clean_ts = raw_ts.str.slice(0, 19)
    df_filtered['Datetime'] = pd.to_datetime(clean_ts, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    
    # FIX: Drop rows where Datetime is NaT
    df_filtered = df_filtered.dropna(subset=['Datetime']).copy()
    
    df_filtered['Net PnL'] = df_filtered['Realised P&L(INR)'] - df_filtered['Trading Fees(INR)']
    
    def get_type(row):
        if row['Realised P&L(INR)'] > 0: return 'Win'
        elif row['Realised P&L(INR)'] < 0: return 'Loss'
        return 'Order Fee'
    df_filtered['Type'] = df_filtered.apply(get_type, axis=1)

    total_net = df_filtered['Net PnL'].sum()
    total_gross = df_filtered['Realised P&L(INR)'].sum()
    total_fees = df_filtered['Trading Fees(INR)'].sum()
    
    global_wins = df_filtered[df_filtered['Type'] == 'Win'].shape[0]
    global_losses = df_filtered[df_filtered['Type'] == 'Loss'].shape[0]
    global_total = global_wins + global_losses
    global_wr = (global_wins / global_total * 100) if global_total > 0 else 0
    
    max_win = df_filtered['Net PnL'].max()
    max_loss = df_filtered['Net PnL'].min()
    if pd.isna(max_win): max_win = 0
    if pd.isna(max_loss): max_loss = 0

    st.markdown("### Global Performance")
    
    net_color = "green" if total_net > 0 else ("red" if total_net < 0 else "normal")
    wr_color = "green" if global_wr >= 50 else "red"
    gr_color = "green" if total_gross > total_fees else ("red" if total_gross < total_fees else "normal")

    k1, k2, k3, k4 = st.columns(4)
    with k1: custom_metric("Net P&L (INR)", f"₹ {total_net:,.2f}", net_color)
    with k2: custom_metric("Gross P&L", f"₹ {total_gross:,.2f}", gr_color)
    with k3: custom_metric("Total Fees", f"₹ {total_fees:,.2f}", "red") 
    with k4: custom_metric("Win Rate", f"{global_wr:.2f}%", wr_color)

    m1, m2, m3, m4 = st.columns(4)
    with m1: custom_metric("Max Win", f"₹ {max_win:,.2f}", "green")
    with m2: custom_metric("Max Loss", f"₹ {max_loss:,.2f}", "red")
    
    st.divider()

    st.markdown("### Account Breakdown")
    
    def sort_by_prefix_then_number(acc):
        match = re.search(r'^([a-zA-Z]+)-(\d+)$', str(acc))
        if match:
            return (match.group(1).upper(), int(match.group(2)))
        return ('ZZZ', float('inf'))
        
    unique_accounts = sorted(df_filtered['Account'].unique(), key=sort_by_prefix_then_number)
    
    if len(unique_accounts) > 0:
        MAX_COLS = 4 
        for i in range(0, len(unique_accounts), MAX_COLS):
            chunk = unique_accounts[i:i + MAX_COLS]
            cols = st.columns(MAX_COLS)
            
            for j, acc in enumerate(chunk):
                acc_data = df_filtered[df_filtered['Account'] == acc]
                acc_net = acc_data['Net PnL'].sum()
                acc_wins = acc_data[acc_data['Type'] == 'Win'].shape[0]
                acc_losses = acc_data[acc_data['Type'] == 'Loss'].shape[0]
                acc_total = acc_wins + acc_losses
                acc_wr = (acc_wins / acc_total * 100) if acc_total > 0 else 0
                
                # --- ADD THIS: Hardcoded Group Label Logic ---
                acc_upper = str(acc).upper()
                if acc_upper in ['A-1', 'A-2', 'A-3', 'A-4', 'A-5', 'A-6']: grp_label = 'Delta'
                elif acc_upper in ['A-7', 'A-8', 'A-9', 'A-10', 'A-11']: grp_label = 'CS'
                elif acc_upper == 'A-12': grp_label = 'PI42'
                elif acc_upper == 'A-13': grp_label = 'CDX'
                elif acc_upper == 'A-14': grp_label = 'Mudrex'
                elif acc_upper == 'A-15': grp_label = 'Zebpay'
                elif acc_upper == 'A-16': grp_label = 'Giottus'
                elif acc_upper == 'A-17': grp_label = 'Binance'
                elif acc_upper == 'A-18': grp_label = 'Bybit'
                else: grp_label = 'Other'
                
                acc_net_color = "green" if acc_net > 0 else ("red" if acc_net < 0 else "normal")
                
                with cols[j]:
                    wr_class = "green-text" if acc_wr >= 50 else "red-text"
                    net_class = "green-text" if acc_net > 0 else ("red-text" if acc_net < 0 else "normal-text")
                    
                    # --- CHANGE: Injected the new grey label div above the existing one ---
                    html = f"""
                    <div class="metric-card">
                        <div style="font-size: 16px; color: #888; text-transform: uppercase; font-weight: bold; margin-bottom: 2px;">{grp_label}</div>
                        <div class="metric-label">{acc} Win Rate and Net P&L</div>
                        <div class="metric-value {wr_class}">{acc_wr:.2f}%</div>
                        <div style="font-size: 24px; font-weight: bold; margin-top:5px;" class="{net_class}">
                            ₹ {acc_net:,.2f}
                        </div>
                    </div>
                    """
                    st.markdown(html, unsafe_allow_html=True)
    
    st.divider()

    # --- CHARTS ---
    tab_dashboard, tab_raw = st.tabs(["📊 Graphical Report", "📄 Raw Data"])

    with tab_dashboard:
        # --- THE FIX: INTERACTION TOGGLE & KEY RESET ---
        enable_zoom = st.toggle("Enable Zooming & Interaction", value=False)
        
        if enable_zoom:
            chart_config = {'displayModeBar': True, 'scrollZoom': True}
            drag_mode = "zoom" 
            st.caption("✅ Zoom Enabled: You can pinch/drag charts. Toggle OFF to reset & lock.")
        else:
            chart_config = {'displayModeBar': False, 'scrollZoom': False}
            drag_mode = False 
        
        # We append the toggle state to the 'key' to force a full reset/re-render
        chart_key_suffix = f"_{enable_zoom}"

        # 1. EQUITY CURVE
        st.subheader("Cumulative Net P&L")
        
        df_sorted = df_filtered.sort_values(by='Datetime')
        df_sorted['Equity'] = df_sorted['Net PnL'].cumsum()
        
        df_sorted = df_sorted.reset_index(drop=True)
        new_rows = []
        for i in range(1, len(df_sorted)):
            prev_eq = df_sorted.loc[i-1, 'Equity']
            curr_eq = df_sorted.loc[i, 'Equity']
            if (prev_eq > 0 and curr_eq < 0) or (prev_eq < 0 and curr_eq > 0):
                prev_time = df_sorted.loc[i-1, 'Datetime']
                curr_time = df_sorted.loc[i, 'Datetime']
                fraction = abs(prev_eq) / (abs(prev_eq) + abs(curr_eq))
                time_diff = curr_time - prev_time
                zero_time = prev_time + (time_diff * fraction)
                zero_row = df_sorted.loc[i-1].copy()
                zero_row['Datetime'] = zero_time
                zero_row['Equity'] = 0
                new_rows.append(zero_row)
        
        if new_rows:
            df_zeros = pd.DataFrame(new_rows)
            df_final = pd.concat([df_sorted, df_zeros]).sort_values(by='Datetime')
        else:
            df_final = df_sorted
            
        fig_equity = go.Figure()
        y_green = df_final['Equity'].copy()
        y_green[y_green < 0] = None 
        fig_equity.add_trace(go.Scatter(
            x=df_final['Datetime'], y=y_green,
            fill='tozeroy', mode='lines', 
            line=dict(color='#2E7D32', width=2),
            fillcolor='rgba(46, 125, 50, 0.2)',
            name='Profit'
        ))
        y_red = df_final['Equity'].copy()
        y_red[y_red > 0] = None
        fig_equity.add_trace(go.Scatter(
            x=df_final['Datetime'], y=y_red,
            fill='tozeroy', mode='lines', 
            line=dict(color='#D32F2F', width=2),
            fillcolor='rgba(211, 47, 47, 0.2)',
            name='Drawdown'
        ))
        
        fig_equity.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), 
            height=350,
            hovermode="x unified",
            dragmode=drag_mode,
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)')
        )
        st.plotly_chart(fig_equity, key=f"equity{chart_key_suffix}", config=chart_config)
        
        # 2. PERIOD P&L
        freq_choice = st.session_state['f_freq']
        st.subheader(f"{freq_choice} Net P&L")
        
        df_period = df_filtered.copy()
        
        if freq_choice == "Weekly":
            period_pnl = df_period.groupby(pd.Grouper(key='Datetime', freq='W-MON'))['Net PnL'].sum().reset_index()
        elif freq_choice == "Monthly":
            period_pnl = df_period.groupby(pd.Grouper(key='Datetime', freq='ME'))['Net PnL'].sum().reset_index()
        elif freq_choice == "Yearly":
            period_pnl = df_period.groupby(pd.Grouper(key='Datetime', freq='YE'))['Net PnL'].sum().reset_index()
        else:
            period_pnl = df_period.groupby('Date')['Net PnL'].sum().reset_index()
            period_pnl.rename(columns={'Date': 'Datetime'}, inplace=True)

        period_pnl['Color'] = period_pnl['Net PnL'].apply(lambda x: '#2E7D32' if x >= 0 else '#D32F2F')
        
        fig_daily = go.Figure()
        fig_daily.add_trace(go.Bar(
            x=period_pnl['Datetime'], y=period_pnl['Net PnL'], 
            marker_color=period_pnl['Color']
        ))
        fig_daily.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), dragmode=drag_mode)
        st.plotly_chart(fig_daily, key=f"period_pnl{chart_key_suffix}", config=chart_config)

        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.container(border=True):
                st.markdown("**Hourly Performance**")
                df_filtered['HourStr'] = df_filtered['Time'].astype(str).str.split(':').str[0]
                df_filtered['Hour'] = pd.to_numeric(df_filtered['HourStr'], errors='coerce')
                hourly_pnl = df_filtered.groupby('Hour')['Net PnL'].sum().reset_index()
                fig_hour = px.bar(hourly_pnl, x='Hour', y='Net PnL', color='Net PnL', 
                                  color_continuous_scale=['#D32F2F', '#FDD835', '#2E7D32']) 
                fig_hour.update_layout(coloraxis_showscale=False, height=200, margin=dict(l=0,r=0,t=0,b=0), dragmode=drag_mode)
                st.plotly_chart(fig_hour, key=f"hour{chart_key_suffix}", width='stretch', config=chart_config)
        with c2:
            with st.container(border=True):
                st.markdown("**Fee Drain**")
                metrics = pd.DataFrame({'Metric': ['Gross Profit', 'Trading Fees'], 'Value': [total_gross, total_fees]})
                fig_fees = px.bar(metrics, x='Metric', y='Value', color='Metric', 
                                  color_discrete_map={'Gross Profit': '#2E7D32', 'Trading Fees': '#D32F2F'})
                fig_fees.update_layout(showlegend=False, height=200, margin=dict(l=0,r=0,t=0,b=0), dragmode=drag_mode)
                st.plotly_chart(fig_fees, key=f"fees{chart_key_suffix}", width='stretch', config=chart_config)
        with c3:
            with st.container(border=True):
                st.markdown("**Long vs. Short**")
                side_pnl = df_filtered.groupby('Side')['Net PnL'].sum().reset_index()
                fig_side = px.bar(side_pnl, y='Side', x='Net PnL', orientation='h', 
                                  color='Net PnL', color_continuous_scale=['#D32F2F', '#2E7D32'])
                fig_side.update_layout(coloraxis_showscale=False, height=200, margin=dict(l=0,r=0,t=0,b=0), dragmode=drag_mode)
                st.plotly_chart(fig_side, key=f"side{chart_key_suffix}", width='stretch', config=chart_config)

    with tab_raw:
        def highlight_pnl(val):
            if val > 0: return 'color: #2ca02c; font-weight: bold'
            elif val < 0: return 'color: #d62728; font-weight: bold'
            else: return 'font-weight: bold'
        
        def highlight_type(val):
            if val == 'Win': return 'color: #2ca02c; font-weight: bold'
            elif val == 'Loss': return 'color: #d62728; font-weight: bold'
            else: return 'font-weight: bold'
        styled_df = df_filtered.style.format({
            'Realised P&L(INR)': '₹ {:,.2f}',
            'Trading Fees(INR)': '₹ {:,.2f}',
            'Net PnL': '₹ {:,.2f}'
        }).map(highlight_pnl, subset=['Realised P&L(INR)', 'Net PnL'])\
          .map(highlight_type, subset=['Type'])
        st.dataframe(styled_df, width="stretch", height=600)