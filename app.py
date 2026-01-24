import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import os
import datetime
from github import Github

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Pro Trading Dashboard", layout="wide")
MASTER_DB = "trade_history.csv"

# --- CONFIGURATION FOR GITHUB ---
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"] if "GITHUB_TOKEN" in st.secrets else None
REPO_NAME = "Sstendafity/trading-dashboard"  # <--- REMEMBER TO CHANGE THIS

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
    
    /* Make buttons smaller for shortcuts */
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
            return pd.read_csv(MASTER_DB)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame(columns=['Account', 'Date', 'Time', 'Contract', 'Side', 'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID'])

def save_to_master(new_df):
    if os.path.exists(MASTER_DB):
        old_df = pd.read_csv(MASTER_DB)
    else:
        old_df = pd.DataFrame()

    combined = pd.concat([old_df, new_df], ignore_index=True)
    
    if 'Order ID' in combined.columns:
        combined['Order ID'] = combined['Order ID'].astype(str)
        combined = combined.drop_duplicates(subset=['Order ID'], keep='last')

    combined.to_csv(MASTER_DB, index=False)
    csv_str = combined.to_csv(index=False)
    success = update_github_repo(csv_str)
    
    return combined, success

def normalize_raw_data(file):
    df_raw = pd.read_csv(file)
    filename = file.name
    account_name = filename.split()[0]
    
    if 'Status' in df_raw.columns:
        df_raw = df_raw[df_raw['Status'] == 'closed'].copy()
    
    temp_dt = df_raw['Time'].astype(str).str.split(' IST').str[0]
    temp_dt = pd.to_datetime(temp_dt, errors='coerce')
    
    df_raw['Date'] = temp_dt.dt.date
    df_raw['Time'] = temp_dt.dt.time.astype(str)
    
    conversion_rate = 85.0
    if 'Realised P&L' in df_raw.columns:
        df_raw['Realised P&L(INR)'] = df_raw['Realised P&L'] * conversion_rate
        df_raw['Trading Fees(INR)'] = df_raw['Trading Fees'] * conversion_rate
        
    df_raw['Account'] = account_name
    
    if 'Order ID' in df_raw.columns:
        df_raw['Order ID'] = df_raw['Order ID'].astype(str)
    
    target_cols = ['Account', 'Date', 'Time', 'Contract', 'Side', 
                   'Realised P&L(INR)', 'Trading Fees(INR)', 'Status', 'Order ID']
    available_cols = [c for c in target_cols if c in df_raw.columns]
    return df_raw[available_cols]

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
    df['Date'] = pd.to_datetime(df['Date'])
    min_d = df['Date'].min().date()
    max_d = df['Date'].max().date()
    
    all_accounts = df['Account'].unique().tolist()
    all_contracts = df['Contract'].unique().tolist()
    all_sides = df['Side'].unique().tolist()
    timeframes = ["Daily", "Weekly", "Monthly", "Yearly"]

    if 'f_date' not in st.session_state: st.session_state['f_date'] = (min_d, max_d)
    if 'f_acc' not in st.session_state: st.session_state['f_acc'] = all_accounts
    if 'f_con' not in st.session_state: st.session_state['f_con'] = all_contracts
    if 'f_side' not in st.session_state: st.session_state['f_side'] = all_sides
    if 'f_freq' not in st.session_state: st.session_state['f_freq'] = "Daily"

    with st.expander("🛠️ Filter Options (Click to Expand)", expanded=False):
        
        # --- TOP ROW: RESET & STATUS ---
        k1, k2 = st.columns([1, 4])
        with k1:
             if st.button("🔄 Reset All", use_container_width=True):
                st.session_state['f_date'] = (min_d, max_d)
                st.session_state['f_acc'] = all_accounts
                st.session_state['f_con'] = all_contracts
                st.session_state['f_side'] = all_sides
                st.session_state['f_freq'] = "Daily"
                st.rerun()
        
        st.markdown("---") # Separator line
        
        # --- MIDDLE: QUICK DATE SHORTCUTS (The Fix for Untidy Look) ---
        # We use 2 rows of 3 buttons. This is symmetric and clean.
        st.write("**Quick Date Ranges:**")
        today = datetime.date.today()
        
        # Row 1
        r1_col1, r1_col2, r1_col3 = st.columns(3)
        if r1_col1.button("📅 Today", use_container_width=True):
            st.session_state['f_date'] = (today, today)
            st.rerun()
        if r1_col2.button("⏪ Yesterday", use_container_width=True):
            yesterday = today - datetime.timedelta(days=1)
            st.session_state['f_date'] = (yesterday, yesterday)
            st.rerun()
        if r1_col3.button("📆 This Week", use_container_width=True):
            start = today - datetime.timedelta(days=today.weekday())
            st.session_state['f_date'] = (start, today)
            st.rerun()
            
        # Row 2
        r2_col1, r2_col2, r2_col3 = st.columns(3)
        if r2_col1.button("🗓️ This Month", use_container_width=True):
            start = today.replace(day=1)
            st.session_state['f_date'] = (start, today)
            st.rerun()
        if r2_col2.button("📅 This Year", use_container_width=True):
            start = today.replace(month=1, day=1)
            st.session_state['f_date'] = (start, today)
            st.rerun()
        if r2_col3.button("∞ All Time", use_container_width=True):
            st.session_state['f_date'] = (min_d, max_d)
            st.rerun()

        st.markdown("---") # Separator line
            
        # --- BOTTOM: FINE TUNING ---
        c1, c2 = st.columns([1, 2])
        
        with c1:
            st.date_input("Custom Date Range", 
                          min_value=min_d, max_value=max_d,
                          key='f_date') 
            st.selectbox("Timeframe Aggregation", timeframes, key='f_freq')
        
        with c2:
            st.multiselect("Account", all_accounts, key='f_acc')
            st.multiselect("Contract", all_contracts, key='f_con')
            st.multiselect("Side", all_sides, key='f_side')

    # Apply Logic
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
    st.info("👋 No data found. Please run 'migrate.py' or upload files.")
else:
    # --- PRE-CALCULATE DATETIME ---
    raw_ts = df_filtered['Date'].astype(str) + ' ' + df_filtered['Time'].astype(str)
    clean_ts = raw_ts.str.slice(0, 19)
    df_filtered['Datetime'] = pd.to_datetime(clean_ts, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    
    df_filtered['Net PnL'] = df_filtered['Realised P&L(INR)'] - df_filtered['Trading Fees(INR)']
    
    def get_type(row):
        if row['Realised P&L(INR)'] > 0: return 'Win'
        elif row['Realised P&L(INR)'] < 0: return 'Loss'
        return 'Order Fee'
    df_filtered['Type'] = df_filtered.apply(get_type, axis=1)

    # --- ROW 1: GLOBAL SCORECARD ---
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

    # --- ROW 3: ACCOUNT BREAKDOWN ---
    st.markdown("### Account Breakdown")
    unique_accounts = sorted(df_filtered['Account'].unique())
    
    if len(unique_accounts) > 0:
        cols = st.columns(len(unique_accounts))
        for i, acc in enumerate(unique_accounts):
            acc_data = df_filtered[df_filtered['Account'] == acc]
            acc_net = acc_data['Net PnL'].sum()
            acc_wins = acc_data[acc_data['Type'] == 'Win'].shape[0]
            acc_losses = acc_data[acc_data['Type'] == 'Loss'].shape[0]
            acc_total = acc_wins + acc_losses
            acc_wr = (acc_wins / acc_total * 100) if acc_total > 0 else 0
            
            acc_net_color = "green" if acc_net > 0 else ("red" if acc_net < 0 else "normal")
            
            with cols[i]:
                wr_class = "green-text" if acc_wr >= 50 else "red-text"
                net_class = "green-text" if acc_net > 0 else ("red-text" if acc_net < 0 else "normal-text")
                html = f"""
                <div class="metric-card">
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
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)')
        )
        st.plotly_chart(fig_equity, key="equity")
        
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
        fig_daily.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_daily, key="period_pnl")

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
                fig_hour.update_layout(coloraxis_showscale=False, height=200, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig_hour, key="hour", width="stretch")
        with c2:
            with st.container(border=True):
                st.markdown("**Fee Drain**")
                metrics = pd.DataFrame({'Metric': ['Gross Profit', 'Trading Fees'], 'Value': [total_gross, total_fees]})
                fig_fees = px.bar(metrics, x='Metric', y='Value', color='Metric', 
                                  color_discrete_map={'Gross Profit': '#2E7D32', 'Trading Fees': '#D32F2F'})
                fig_fees.update_layout(showlegend=False, height=200, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig_fees, key="fees", width="stretch")
        with c3:
            with st.container(border=True):
                st.markdown("**Long vs. Short**")
                side_pnl = df_filtered.groupby('Side')['Net PnL'].sum().reset_index()
                fig_side = px.bar(side_pnl, y='Side', x='Net PnL', orientation='h', 
                                  color='Net PnL', color_continuous_scale=['#D32F2F', '#2E7D32'])
                fig_side.update_layout(coloraxis_showscale=False, height=200, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig_side, key="side", width="stretch")

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