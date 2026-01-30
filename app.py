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
}

.kpi-box {
    background-color: white;
    padding: 15px;
    border-radius: 12px;
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
        # Try reading with utf-8, fall back if needed
        try:
            df = pd.read_csv(file)
        except UnicodeDecodeError:
            df = pd.read_csv(file, encoding='latin1')
        
        # --- 1. DATA RECOVERY (Dates) ---
        # Before dropping Column C ("Created"), use it to fill missing "Shutdown Date/Time"
        # This handles rows with missing shutdown dates.
        if "Created" in df.columns and "Shutdown Date/Time" in df.columns:
            df["Shutdown Date/Time"] = df["Shutdown Date/Time"].fillna(df["Created"])

        # --- 2. DATA RECOVERY (Reasons) ---
        # Use Column I ("Remarks / Shutdown Reason") to fill "ShutdownReason" if it is "Other"
        # Ensure column names are stripped of whitespace first just in case
        df.columns = df.columns.str.strip()
        
        if "ShutdownReason" in df.columns and "Remarks / Shutdown Reason" in df.columns:
            # Normalize to lower case for comparison, but keep original data
            condition = (df["ShutdownReason"].astype(str).str.lower().str.strip() == "other") & \
                        (df["Remarks / Shutdown Reason"].notna()) & \
                        (df["Remarks / Shutdown Reason"].astype(str).str.strip() != "")
            
            # Update ShutdownReason with Remark where condition is met
            df.loc[condition, "ShutdownReason"] = df.loc[condition, "Remarks / Shutdown Reason"]

        # --- 3. CSV SPECIFIC CLEANING ---
        # Map Excel Column Letters to 0-based Indices:
        # A=0, B=1, C=2, D=3, E=4, F=5, G=6, H=7, I=8, J=9 ... AB=27
        
        # Logic: 
        # - Remove C (Index 2)
        # - Remove E (Index 4)
        # - Keep I (Index 8) -> CHANGED based on request
        # - Remove J to AB (Index 9 to 27)
        
        indices_to_drop = [2, 4] + list(range(9, 28))
        
        # Filter indices to ensure we don't try to drop columns that don't exist
        existing_indices = [i for i in indices_to_drop if i < len(df.columns)]
        
        # Drop by column index
        df.drop(df.columns[existing_indices], axis=1, inplace=True)
        
    else:
        # Excel logic
        df = pd.read_excel(file, engine="openpyxl")
        df.columns = df.columns.str.strip()
        
        # Apply the same logic for Excel if columns exist
        if "ShutdownReason" in df.columns and "Remarks / Shutdown Reason" in df.columns:
            condition = (df["ShutdownReason"].astype(str).str.lower().str.strip() == "other") & \
                        (df["Remarks / Shutdown Reason"].notna())
            df.loc[condition, "ShutdownReason"] = df.loc[condition, "Remarks / Shutdown Reason"]

    df.columns = df.columns.str.strip()

    # 2. Process Dates and Numerics
    # Added dayfirst=True to handle DD/MM/YYYY formats correctly
    df["Shutdown Date/Time"] = pd.to_datetime(df["Shutdown Date/Time"], dayfirst=True, errors="coerce")
    df["Start Up Date/Time"] = pd.to_datetime(df["Start Up Date/Time"], dayfirst=True, errors="coerce")
    df["Downtime (Hrs)"] = pd.to_numeric(df["Downtime (Hrs)"], errors="coerce")

    # 3. Fill blanks (CRITICAL)
    # If Shutdown Date is STILL NaT (after trying fillna above), fill with the min date
    # so it doesn't get filtered out by the date picker.
    if df["Shutdown Date/Time"].notna().any():
        min_valid_date = df["Shutdown Date/Time"].min()
        df["Shutdown Date/Time"] = df["Shutdown Date/Time"].fillna(min_valid_date)
    
    df["Site"] = df["Site"].fillna("Unknown Site")
    df["Well"] = df["Well"].fillna("Unknown Well")
    
    if "ShutdownReason" in df.columns:
        df["ShutdownReason"] = df["ShutdownReason"].fillna("Unknown / Not Reported")
    else:
        df["ShutdownReason"] = "Unknown" # Fallback if column missing

    if "Alert" in df.columns:
        df["Alert"] = df["Alert"].fillna("No Alert")

    # 4. Create Categorical Buckets
    df["Downtime Bucket"] = pd.cut(
        df["Downtime (Hrs)"],
        [-1, 1, 5, 24, 1e6],
        labels=["0–1 hr", "1–5 hrs", "5–24 hrs", ">24 hrs"]
    )

    # 5. Extract Month
    df["Shutdown Month"] = df["Shutdown Date/Time"].dt.to_period("M").astype(str)

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
    st.warning("Please upload an Excel or CSV file to continue.")
    st.stop()

# =================================================
# FILTER BAR (PRO STYLE)
# =================================================
st.markdown("### 🔎 Filters")

with st.container():
    st.markdown('<div class="filter-box">', unsafe_allow_html=True)

    f1, f2, f3, f4, f5 = st.columns([1.2, 1.2, 1.8, 1.2, 2])

    site_f = f1.selectbox(
        "Site",
        ["All Sites"] + sorted(df["Site"].unique())
    )

    well_f = f2.selectbox(
        "Well",
        ["All Wells"] + sorted(df["Well"].unique())
    )

    # Check if column exists (CSV safety)
    reason_options = ["All Reasons"]
    if "ShutdownReason" in df.columns:
        # Get unique reasons after the "Other" replacement update
        unique_reasons = sorted([str(x) for x in df["ShutdownReason"].unique()])
        reason_options += unique_reasons
        
    reason_f = f3.selectbox(
        "Shutdown Reason",
        reason_options
    )

    alert_options = ["All Alerts"]
    if "Alert" in df.columns:
        alert_options += sorted([str(x) for x in df["Alert"].unique()])

    alert_f = f4.selectbox(
        "Alert",
        alert_options
    )

    # Handle cases where data might be empty after upload or have NaT dates
    min_date = df["Shutdown Date/Time"].min()
    max_date = df["Shutdown Date/Time"].max()
    
    if pd.isna(min_date) or pd.isna(max_date):
         st.error("Date column contains no valid dates or file is empty.")
         st.stop()

    date_f = f5.date_input(
        "Shutdown Date Range",
        [min_date.date(), max_date.date()]
    )

    st.markdown('</div>', unsafe_allow_html=True)

# =================================================
# APPLY FILTERS (SAFE & CLEAR)
# =================================================
filtered_df = df.copy()

if site_f != "All Sites":
    filtered_df = filtered_df[filtered_df["Site"] == site_f]

if well_f != "All Wells":
    filtered_df = filtered_df[filtered_df["Well"] == well_f]

if reason_f != "All Reasons" and "ShutdownReason" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["ShutdownReason"].astype(str) == reason_f]

if alert_f != "All Alerts" and "Alert" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["Alert"].astype(str) == alert_f]

# Ensure date_f has two values (Start and End) before filtering
if len(date_f) == 2:
    filtered_df = filtered_df[
        (filtered_df["Shutdown Date/Time"].dt.date >= date_f[0]) &
        (filtered_df["Shutdown Date/Time"].dt.date <= date_f[1])
    ]

st.caption(
    f"📄 Total Records: {len(df)} | Displayed: {len(filtered_df)}"
)

# =================================================
# KPI ROW
# =================================================
k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("Shutdowns", len(filtered_df))
k2.metric("Downtime (hrs)", f"{filtered_df['Downtime (Hrs)'].sum():,.1f}")
k3.metric("Avg Downtime", f"{filtered_df['Downtime (Hrs)'].mean():,.2f}")
k4.metric(">24h Shutdowns", (filtered_df["Downtime (Hrs)"] > 24).sum())
k5.metric("Affected Wells", filtered_df["Well"].nunique())

st.divider()

# =================================================
# CHARTS
# =================================================
c1, c2 = st.columns(2)

with c1:
    st.subheader("🔴 Top Wells by Downtime")
    top_wells = (
        filtered_df.groupby("Well")["Downtime (Hrs)"]
        .sum().sort_values(ascending=False).head(10).reset_index()
    )
    if not top_wells.empty:
        st.plotly_chart(
            px.bar(
                top_wells,
                x="Downtime (Hrs)",
                y="Well",
                orientation="h",
                color="Downtime (Hrs)",
                color_continuous_scale="Reds"
            ),
            use_container_width=True
        )
    else:
        st.info("No data for charts")

with c2:
    st.subheader("⚡ Shutdown Reason Distribution")
    if not filtered_df.empty and "ShutdownReason" in filtered_df.columns:
        # Limit pie chart to top 10 reasons to avoid clutter if 'Others' expansion created many categories
        reason_counts = filtered_df["ShutdownReason"].value_counts().reset_index()
        reason_counts.columns = ["ShutdownReason", "Count"]
        
        if len(reason_counts) > 15:
            # Group smaller categories into "Misc" for the chart if too many unique remarks
            top_15 = reason_counts.head(15)
            other_count = reason_counts.iloc[15:]["Count"].sum()
            if other_count > 0:
                new_row = pd.DataFrame({"ShutdownReason": ["Misc / Low Freq Reasons"], "Count": [other_count]})
                reason_counts = pd.concat([top_15, new_row])
        
        st.plotly_chart(
            px.pie(
                reason_counts,
                names="ShutdownReason",
                values="Count",
                hole=0.4
            ),
            use_container_width=True
        )
    else:
        st.info("Shutdown Reason column missing or empty")

st.subheader("📈 Monthly Shutdown Trend")
monthly = filtered_df.groupby("Shutdown Month").size().reset_index(name="Shutdown Count")
if not monthly.empty:
    st.plotly_chart(
        px.line(monthly, x="Shutdown Month", y="Shutdown Count", markers=True),
        use_container_width=True
    )

# =================================================
# TABLE + EXPORT
# =================================================
st.subheader("📋 Shutdown Event Log")

# Display specific columns if they exist to keep table clean
cols_to_show = [c for c in ["Shutdown Date/Time", "Well", "Downtime (Hrs)", "ShutdownReason", "Remarks / Shutdown Reason", "Alert"] if c in filtered_df.columns]
# If Remarks column doesn't exist in filtered (e.g. excel upload without it), fallback to all
if not cols_to_show:
    cols_to_show = filtered_df.columns

st.dataframe(
    filtered_df[cols_to_show].sort_values("Shutdown Date/Time", ascending=False),
    use_container_width=True,
    height=350
)

buffer = BytesIO()
# Export as Excel regardless of input type
filtered_df.to_excel(buffer, index=False)

st.download_button(
    "⬇ Download Filtered Data (XLSX)",
    buffer.getvalue(),
    "Shutdown_Filtered.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


st.divider()
st.subheader("📄 Well Shutdown PDF Report")

pdf_well = st.selectbox(
    "Select Well for PDF Report",
    sorted(df["Well"].unique()),
    key="pdf_well"
)

if st.button("🧾 Generate PDF Report"):
    well_df = df[df["Well"] == pdf_well]

    if well_df.empty:
        st.error("No data available for selected well.")
        st.stop()

    # -----------------------------
    # KPIs
    # -----------------------------
    total_sd = len(well_df)
    total_dt = well_df["Downtime (Hrs)"].sum()
    avg_dt = well_df["Downtime (Hrs)"].mean()
    max_dt = well_df["Downtime (Hrs)"].max()

    # -----------------------------
    # Charts
    # -----------------------------
    monthly = (
        well_df.groupby("Shutdown Month")
        .size().reset_index(name="Shutdown Count")
    )

    # Check for Reason column availability
    if "ShutdownReason" in well_df.columns:
        reason = (
            well_df.groupby("ShutdownReason")
            .agg(Total_Downtime=("Downtime (Hrs)", "sum"))
            .reset_index()
        )
    else:
        # Fallback if column missing
        reason = pd.DataFrame(columns=["ShutdownReason", "Total_Downtime"])

    fig_monthly = px.line(
        monthly,
        x="Shutdown Month",
        y="Shutdown Count",
        markers=True,
        title="Monthly Shutdown Trend"
    )

    fig_reason = px.pie(
        reason,
        names="ShutdownReason" if not reason.empty else None,
        values="Total_Downtime" if not reason.empty else None,
        hole=0.4,
        title="Downtime by Shutdown Reason",
        color="ShutdownReason" if not reason.empty else None,
        color_discrete_sequence=px.colors.qualitative.Plotly
    )

    # -----------------------------
    # Save charts as images
    # -----------------------------
    tmp_dir = tempfile.mkdtemp()
    trend_img = os.path.join(tmp_dir, "trend.png")
    reason_img = os.path.join(tmp_dir, "reason.png")

    try:
        pio.write_image(fig_monthly, trend_img, engine="kaleido")
        pio.write_image(fig_reason, reason_img, engine="kaleido")

    except ValueError:
        st.error("Kaleido package is required for PDF image generation. Please install it or check your environment.")
        st.stop()

    # -----------------------------
    # Build PDF
    # -----------------------------
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4)

    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#0B3C5D")
    styles["Heading2"].textColor = colors.HexColor("#1F7A8C")

    elements = []

    # ===== TITLE =====
    elements.append(Paragraph(
        f"<b>Well Shutdown Performance Report</b><br/>"
        f"<font size=12>Well: {pdf_well}</font>",
        styles["Title"]
    ))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(
        f"<font size=9 color='grey'>Generated on {pd.Timestamp.now().strftime('%d %b %Y')}</font>",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 20))

    # ===== KPI TABLE =====
    kpi_table = Table([
        ["Total Shutdowns", total_sd],
        ["Total Downtime (hrs)", f"{total_dt:,.2f}"],
        ["Average Downtime (hrs)", f"{avg_dt:,.2f}"],
        ["Longest Shutdown (hrs)", f"{max_dt:,.2f}"],
    ], colWidths=[220, 120])

    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0B3C5D")),
        ("FONT", (0, 0), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))

    elements.append(kpi_table)
    elements.append(Spacer(1, 25))

    # ===== CHARTS =====
    elements.append(
        KeepTogether([
            Paragraph("Monthly Shutdown Trend", styles["Heading2"]),
            Spacer(1, 10),
            Image(trend_img, width=6.8 * inch, height=3 * inch)
        ])
    )


    elements.append(
        KeepTogether([
            Paragraph("Downtime by Shutdown Reason", styles["Heading2"]),
            Spacer(1, 10),
            Image(reason_img, width=5.5 * inch, height=3 * inch)
        ])
    )

    # ===== EVENT TABLE =====
    elements.append(Spacer(1, 25))
    elements.append(Paragraph("Recent Shutdown Events (Latest 20)", styles["Heading2"]))
    elements.append(Spacer(1, 10))

    # Columns to include in report (check availability)
    cols_to_report = ["Shutdown Date/Time", "Start Up Date/Time", "Downtime (Hrs)"]
    if "ShutdownReason" in well_df.columns:
        cols_to_report.append("ShutdownReason")
    if "Alert" in well_df.columns:
        cols_to_report.append("Alert")

    table_df = well_df.sort_values(
        "Shutdown Date/Time", ascending=False
    ).head(20)[cols_to_report]
    
    # Convert timestamps to string to avoid ReportLab issues
    table_df["Shutdown Date/Time"] = table_df["Shutdown Date/Time"].astype(str)
    table_df["Start Up Date/Time"] = table_df["Start Up Date/Time"].astype(str)

    table_data = [table_df.columns.tolist()] + table_df.values.tolist()

    event_table = Table(table_data, repeatRows=1)
    event_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3C5D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))

    elements.append(event_table)

    doc.build(elements)

    st.success("PDF report generated successfully")

    st.download_button(
        "⬇ Download PDF Report",
        data=pdf_buffer.getvalue(),
        file_name=f"{pdf_well}_Shutdown_Report.pdf",
        mime="application/pdf"
    )