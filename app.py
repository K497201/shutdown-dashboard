import pandas as pd
import streamlit as st
import plotly.express as px
from io import BytesIO
from reportlab.platypus import KeepTogether
from reportlab.lib import colors
from reportlab.platypus import TableStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
import plotly.io as pio
import tempfile
import os
from collections import Counter
import re

# Set Plotly export settings
pio.kaleido.scope.default_format = "png"
pio.kaleido.scope.default_width = 800
pio.kaleido.scope.default_height = 400


# =================================================
# PAGE CONFIG
# =================================================
st.set_page_config(
    page_title="Well Shutdown Dashboard",
    page_icon="⛽",
    layout="wide"
)

# =================================================
# GLOBAL STYLE (NO SIDEBAR)
# =================================================
st.markdown("""
<style>
body {background-color: #f5f6fa;}
.block-container {padding-top: 1.2rem;}

.filter-box {
    background-color: white;
    padding: 15px;
    border-radius: 12px;
    margin-bottom: 15px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.chart-box {
    background-color: white;
    padding: 15px;
    border-radius: 12px;
    margin-bottom: 15px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
</style>
""", unsafe_allow_html=True)

# =================================================
# HEADER
# =================================================
st.markdown("## ⛽ Well Shutdown & Trip Dashboard")
st.caption("Operational downtime intelligence & reliability monitoring")

# =================================================
# DATA LOADING FUNCTION
# =================================================
@st.cache_data
def load_data(file):
    filename = file.name.lower()
    
    # 1. Read the file based on extension
    if filename.endswith('.csv'):
        try:
            df = pd.read_csv(file)
        except UnicodeDecodeError:
            df = pd.read_csv(file, encoding='latin1')
        
        # --- 1. DATA RECOVERY (Dates) ---
        if "Created" in df.columns and "Shutdown Date/Time" in df.columns:
            df["Shutdown Date/Time"] = df["Shutdown Date/Time"].fillna(df["Created"])

        # --- 2. DATA RECOVERY (Reasons) ---
        df.columns = df.columns.str.strip()
        if "ShutdownReason" in df.columns and "Remarks / Shutdown Reason" in df.columns:
            condition = (df["ShutdownReason"].astype(str).str.lower().str.strip() == "other") & \
                        (df["Remarks / Shutdown Reason"].notna()) & \
                        (df["Remarks / Shutdown Reason"].astype(str).str.strip() != "")
            df.loc[condition, "ShutdownReason"] = df.loc[condition, "Remarks / Shutdown Reason"]

        # --- 3. CSV SPECIFIC CLEANING ---
        # Keep I (index 8), Drop J-AB (9-27)
        indices_to_drop = [2, 4] + list(range(9, 28))
        existing_indices = [i for i in indices_to_drop if i < len(df.columns)]
        df.drop(df.columns[existing_indices], axis=1, inplace=True)
        
    else:
        # Excel logic
        df = pd.read_excel(file, engine="openpyxl")
        df.columns = df.columns.str.strip()
        
        if "ShutdownReason" in df.columns and "Remarks / Shutdown Reason" in df.columns:
            condition = (df["ShutdownReason"].astype(str).str.lower().str.strip() == "other") & \
                        (df["Remarks / Shutdown Reason"].notna())
            df.loc[condition, "ShutdownReason"] = df.loc[condition, "Remarks / Shutdown Reason"]

    df.columns = df.columns.str.strip()

    # 2. Process Dates and Numerics
    df["Shutdown Date/Time"] = pd.to_datetime(df["Shutdown Date/Time"], dayfirst=True, errors="coerce")
    df["Start Up Date/Time"] = pd.to_datetime(df["Start Up Date/Time"], dayfirst=True, errors="coerce")
    df["Downtime (Hrs)"] = pd.to_numeric(df["Downtime (Hrs)"], errors="coerce")

    # 3. Fill blanks
    if df["Shutdown Date/Time"].notna().any():
        min_valid_date = df["Shutdown Date/Time"].min()
        df["Shutdown Date/Time"] = df["Shutdown Date/Time"].fillna(min_valid_date)
    
    df["Site"] = df["Site"].fillna("Unknown Site")
    df["Well"] = df["Well"].fillna("Unknown Well")
    
    if "ShutdownReason" in df.columns:
        df["ShutdownReason"] = df["ShutdownReason"].fillna("Unknown")
    else:
        df["ShutdownReason"] = "Unknown"

    if "Alert" in df.columns:
        df["Alert"] = df["Alert"].fillna("No Alert")

    # 4. Extract Time Features for Heatmap
    df["DayOfWeek"] = df["Shutdown Date/Time"].dt.day_name()
    df["Hour"] = df["Shutdown Date/Time"].dt.hour
    df["Shutdown Month"] = df["Shutdown Date/Time"].dt.to_period("M").astype(str)

    # Sort days for heatmap ordering
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    df["DayOfWeek"] = pd.Categorical(df["DayOfWeek"], categories=days_order, ordered=True)

    return df

# =================================================
# FILE UPLOAD & EXECUTION
# =================================================
uploaded_file = st.file_uploader(
    "Upload Shutdown File (Excel or CSV)",
    type=["xlsx", "csv"]
)

if uploaded_file is not None:
    df = load_data(uploaded_file)
else:
    st.info("👋 Upload your shutdown data to generate the analysis.")
    st.stop()

# =================================================
# FILTER BAR
# =================================================
with st.container():
    st.markdown('<div class="filter-box">', unsafe_allow_html=True)
    st.markdown("### 🔎 Filters")
    f1, f2, f3, f4, f5 = st.columns([1.2, 1.2, 1.8, 1.2, 2])

    site_f = f1.selectbox("Site", ["All Sites"] + sorted(df["Site"].unique()))
    well_f = f2.selectbox("Well", ["All Wells"] + sorted(df["Well"].unique()))
    
    reason_options = ["All Reasons"]
    if "ShutdownReason" in df.columns:
        unique_reasons = sorted([str(x) for x in df["ShutdownReason"].unique()])
        reason_options += unique_reasons
    reason_f = f3.selectbox("Shutdown Reason", reason_options)

    alert_options = ["All Alerts"]
    if "Alert" in df.columns:
        alert_options += sorted([str(x) for x in df["Alert"].unique()])
    alert_f = f4.selectbox("Alert", alert_options)

    min_date = df["Shutdown Date/Time"].min()
    max_date = df["Shutdown Date/Time"].max()
    
    if pd.isna(min_date) or pd.isna(max_date):
         st.error("Date column contains no valid dates.")
         st.stop()

    date_f = f5.date_input("Shutdown Date Range", [min_date.date(), max_date.date()])
    st.markdown('</div>', unsafe_allow_html=True)

# Apply Filters
filtered_df = df.copy()
if site_f != "All Sites": filtered_df = filtered_df[filtered_df["Site"] == site_f]
if well_f != "All Wells": filtered_df = filtered_df[filtered_df["Well"] == well_f]
if reason_f != "All Reasons" and "ShutdownReason" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["ShutdownReason"].astype(str) == reason_f]
if alert_f != "All Alerts" and "Alert" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["Alert"].astype(str) == alert_f]
if len(date_f) == 2:
    filtered_df = filtered_df[
        (filtered_df["Shutdown Date/Time"].dt.date >= date_f[0]) &
        (filtered_df["Shutdown Date/Time"].dt.date <= date_f[1])
    ]

# =================================================
# KPI ROW
# =================================================
st.caption(f"📄 Total Records: {len(df)} | Displayed: {len(filtered_df)}")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Shutdowns", len(filtered_df))
k2.metric("Downtime (hrs)", f"{filtered_df['Downtime (Hrs)'].sum():,.1f}")
k3.metric("Avg Downtime", f"{filtered_df['Downtime (Hrs)'].mean():,.2f}")
k4.metric(">24h Shutdowns", (filtered_df["Downtime (Hrs)"] > 24).sum())
k5.metric("Affected Wells", filtered_df["Well"].nunique())

st.divider()

# =================================================
# SECTION 1: OVERVIEW CHARTS
# =================================================
c1, c2 = st.columns(2)

with c1:
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.subheader("🔴 Top Wells by Downtime")
    top_wells = (
        filtered_df.groupby("Well")["Downtime (Hrs)"]
        .sum().sort_values(ascending=False).head(10).reset_index()
    )
    if not top_wells.empty:
        fig = px.bar(top_wells, x="Downtime (Hrs)", y="Well", orientation="h", color="Downtime (Hrs)", color_continuous_scale="Reds")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data")
    st.markdown('</div>', unsafe_allow_html=True)

with c2:
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.subheader("⚡ Shutdown Reason Distribution")
    if not filtered_df.empty and "ShutdownReason" in filtered_df.columns:
        reason_counts = filtered_df["ShutdownReason"].value_counts().reset_index()
        reason_counts.columns = ["ShutdownReason", "Count"]
        if len(reason_counts) > 12:
            top_12 = reason_counts.head(12)
            other_count = reason_counts.iloc[12:]["Count"].sum()
            if other_count > 0:
                new_row = pd.DataFrame({"ShutdownReason": ["Others / Misc"], "Count": [other_count]})
                reason_counts = pd.concat([top_12, new_row])
        
        fig = px.pie(reason_counts, names="ShutdownReason", values="Count", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data")
    st.markdown('</div>', unsafe_allow_html=True)

# =================================================
# SECTION 2: TEMPORAL & PATTERN ANALYSIS
# =================================================
st.subheader("📅 Temporal & Pattern Analysis")

t1, t2 = st.columns([2, 1])

with t1:
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.markdown("#### ⏳ Shutdown Timeline (Gantt Chart)")
    
    # Prepare data for Gantt
    gantt_df = filtered_df.dropna(subset=['Start Up Date/Time', 'Shutdown Date/Time']).copy()
    
    if not gantt_df.empty:
        # Limit to top 50 recent events to prevent overcrowding
        gantt_df = gantt_df.sort_values("Shutdown Date/Time", ascending=False).head(50)
        
        fig_gantt = px.timeline(
            gantt_df, 
            x_start="Shutdown Date/Time", 
            x_end="Start Up Date/Time", 
            y="Well",
            color="ShutdownReason",
            hover_data=["Downtime (Hrs)", "ShutdownReason"],
            height=400
        )
        fig_gantt.update_yaxes(autorange="reversed") # Recent at top
        st.plotly_chart(fig_gantt, use_container_width=True)
    else:
        st.warning("Not enough date data to generate Timeline.")
    st.markdown('</div>', unsafe_allow_html=True)

with t2:
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    st.markdown("#### 🔥 Failure Heatmap (Day vs Hour)")
    
    if not filtered_df.empty:
        heatmap_data = filtered_df.groupby(["DayOfWeek", "Hour"]).size().reset_index(name="Count")
        
        fig_heat = px.density_heatmap(
            heatmap_data, 
            x="Hour", 
            y="DayOfWeek", 
            z="Count", 
            color_continuous_scale="Viridis",
            nbinsx=24
        )
        fig_heat.update_layout(xaxis_title="Hour of Day (0-23)", yaxis_title="Day of Week")
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("No data")
    st.markdown('</div>', unsafe_allow_html=True)

# =================================================
# SECTION 3: TEXT ANALYTICS (ROOT CAUSE)
# =================================================
st.subheader("📝 Text Analytics (Root Cause Mining)")

with st.container():
    st.markdown('<div class="chart-box">', unsafe_allow_html=True)
    
    # Text Processing Logic
    text_data = ""
    if "Remarks / Shutdown Reason" in filtered_df.columns:
        text_data += " ".join(filtered_df["Remarks / Shutdown Reason"].dropna().astype(str).tolist())
    if "ShutdownReason" in filtered_df.columns:
        text_data += " ".join(filtered_df["ShutdownReason"].dropna().astype(str).tolist())
        
    if text_data:
        # Simple cleaning
        text_data = text_data.lower()
        text_data = re.sub(r'[^\w\s]', '', text_data) # Remove punctuation
        words = text_data.split()
        
        # Stopwords list (basic manual list to avoid external dependency issues)
        stopwords = {
            "the", "to", "and", "of", "a", "in", "for", "on", "with", "at", "was", "is", "due", 
            "shutdown", "manual", "trip", "tripped", "alarm", "well", "sd", "vsd", "h", "hrs", "by", "from"
        }
        
        filtered_words = [w for w in words if w not in stopwords and not w.isdigit() and len(w) > 2]
        word_counts = Counter(filtered_words).most_common(20)
        
        word_df = pd.DataFrame(word_counts, columns=["Keyword", "Frequency"])
        
        col_text1, col_text2 = st.columns([1, 2])
        
        with col_text1:
            st.markdown("#### 🔠 Top Keywords in Remarks")
            st.dataframe(word_df, height=300, use_container_width=True)
            
        with col_text2:
            st.markdown("#### 📊 Keyword Frequency Chart")
            if not word_df.empty:
                fig_words = px.bar(
                    word_df, 
                    x="Frequency", 
                    y="Keyword", 
                    orientation='h',
                    color="Frequency",
                    color_continuous_scale="Bluered"
                )
                fig_words.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_words, use_container_width=True)
            else:
                st.info("No sufficient text data found.")
    else:
        st.warning("No text data available in 'Remarks' or 'ShutdownReason' columns.")
        
    st.markdown('</div>', unsafe_allow_html=True)

# =================================================
# TABLE + EXPORT
# =================================================
st.subheader("📋 Shutdown Event Log")

# Smart Column Selection
all_cols = filtered_df.columns.tolist()
priority_cols = ["Shutdown Date/Time", "Well", "Downtime (Hrs)", "ShutdownReason", "Remarks / Shutdown Reason", "Alert"]
final_cols = [c for c in priority_cols if c in all_cols]
# Add remaining cols if needed, or just keep it clean
if not final_cols: final_cols = all_cols

st.dataframe(
    filtered_df[final_cols].sort_values("Shutdown Date/Time", ascending=False),
    use_container_width=True,
    height=350
)

buffer = BytesIO()
filtered_df.to_excel(buffer, index=False)

st.download_button(
    "⬇ Download Filtered Data (XLSX)",
    buffer.getvalue(),
    "Shutdown_Filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# =================================================
# PDF REPORT SECTION
# =================================================
st.divider()
st.subheader("📄 Well Shutdown PDF Report")

pdf_well = st.selectbox("Select Well for PDF Report", sorted(df["Well"].unique()), key="pdf_well")

if st.button("🧾 Generate PDF Report"):
    well_df = df[df["Well"] == pdf_well]

    if well_df.empty:
        st.error("No data available for selected well.")
        st.stop()

    # Calculation
    total_sd = len(well_df)
    total_dt = well_df["Downtime (Hrs)"].sum()
    avg_dt = well_df["Downtime (Hrs)"].mean()
    max_dt = well_df["Downtime (Hrs)"].max()

    # Monthly Trend
    monthly = well_df.groupby("Shutdown Month").size().reset_index(name="Shutdown Count")
    fig_monthly = px.line(monthly, x="Shutdown Month", y="Shutdown Count", markers=True, title="Monthly Shutdown Trend")

    # Reason Pie
    if "ShutdownReason" in well_df.columns:
        reason = well_df.groupby("ShutdownReason").agg(Total_Downtime=("Downtime (Hrs)", "sum")).reset_index()
    else:
        reason = pd.DataFrame(columns=["ShutdownReason", "Total_Downtime"])
        
    fig_reason = px.pie(
        reason, names="ShutdownReason", values="Total_Downtime", hole=0.4, 
        title="Downtime by Reason", color_discrete_sequence=px.colors.qualitative.Plotly
    )

    # Save images
    tmp_dir = tempfile.mkdtemp()
    trend_img = os.path.join(tmp_dir, "trend.png")
    reason_img = os.path.join(tmp_dir, "reason.png")

    try:
        pio.write_image(fig_monthly, trend_img, engine="kaleido")
        pio.write_image(fig_reason, reason_img, engine="kaleido")
    except ValueError:
        st.error("Kaleido package is required for PDF image generation.")
        st.stop()

    # Build PDF
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#0B3C5D")
    
    elements = []
    elements.append(Paragraph(f"<b>Well Shutdown Performance Report</b><br/><font size=12>Well: {pdf_well}</font>", styles["Title"]))
    elements.append(Spacer(1, 20))

    # KPI Table
    kpi_data = [
        ["Total Shutdowns", total_sd],
        ["Total Downtime (hrs)", f"{total_dt:,.2f}"],
        ["Average Downtime (hrs)", f"{avg_dt:,.2f}"],
        ["Longest Shutdown (hrs)", f"{max_dt:,.2f}"],
    ]
    kpi_table = Table(kpi_data, colWidths=[200, 150])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0B3C5D")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 25))

    # Images
    elements.append(Image(trend_img, width=6.5*inch, height=3*inch))
    elements.append(Spacer(1, 15))
    elements.append(Image(reason_img, width=5.5*inch, height=3*inch))
    elements.append(Spacer(1, 25))

    doc.build(elements)
    st.success("PDF report generated successfully")
    st.download_button("⬇ Download PDF Report", data=pdf_buffer.getvalue(), file_name=f"{pdf_well}_Report.pdf", mime="application/pdf")