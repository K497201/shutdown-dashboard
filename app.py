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
# FILE UPLOAD (TOP, NOT SIDEBAR)
# =================================================
uploaded_file = st.file_uploader(
    "Upload Shutdown Excel File",
    type=["xlsx"]
)

@st.cache_data
def load_data(uploaded_file):
    df = pd.read_excel(uploaded_file, engine="openpyxl")
    df.columns = df.columns.str.strip()
    return df

if uploaded_file is not None:
    df = load_data(uploaded_file)
else:
    st.info("Please upload an Excel file to continue")
    st.stop()


    df["Shutdown Date/Time"] = pd.to_datetime(df["Shutdown Date/Time"], errors="coerce")
    df["Start Up Date/Time"] = pd.to_datetime(df["Start Up Date/Time"], errors="coerce")
    df["Downtime (Hrs)"] = pd.to_numeric(df["Downtime (Hrs)"], errors="coerce")

    # Fill blanks (CRITICAL)
    df["Site"] = df["Site"].fillna("Unknown Site")
    df["Well"] = df["Well"].fillna("Unknown Well")
    df["ShutdownReason"] = df["ShutdownReason"].fillna("Unknown / Not Reported")
    df["Alert"] = df["Alert"].fillna("No Alert")

    df["Downtime Bucket"] = pd.cut(
        df["Downtime (Hrs)"],
        [-1, 1, 5, 24, 1e6],
        labels=["0–1 hr", "1–5 hrs", "5–24 hrs", ">24 hrs"]
    )

    df["Shutdown Month"] = df["Shutdown Date/Time"].dt.to_period("M").astype(str)

    return df

if uploaded_file is None:
    st.warning("⬆ Upload the Excel file to start")
    st.stop()

df = load_data(uploaded_file)

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

    reason_f = f3.selectbox(
        "Shutdown Reason",
        ["All Reasons"] + sorted(df["ShutdownReason"].unique())
    )

    alert_f = f4.selectbox(
        "Alert",
        ["All Alerts"] + sorted(df["Alert"].unique())
    )

    date_f = f5.date_input(
        "Shutdown Date Range",
        [df["Shutdown Date/Time"].min().date(),
         df["Shutdown Date/Time"].max().date()]
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

if reason_f != "All Reasons":
    filtered_df = filtered_df[filtered_df["ShutdownReason"] == reason_f]

if alert_f != "All Alerts":
    filtered_df = filtered_df[filtered_df["Alert"] == alert_f]

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

with c2:
    st.subheader("⚡ Shutdown Reason Distribution")
    st.plotly_chart(
        px.pie(
            filtered_df,
            names="ShutdownReason",
            hole=0.45
        ),
        use_container_width=True
    )

st.subheader("📈 Monthly Shutdown Trend")
monthly = filtered_df.groupby("Shutdown Month").size().reset_index(name="Shutdown Count")
st.plotly_chart(
    px.line(monthly, x="Shutdown Month", y="Shutdown Count", markers=True),
    use_container_width=True
)

# =================================================
# TABLE + EXPORT
# =================================================
st.subheader("📋 Shutdown Event Log")

st.dataframe(
    filtered_df.sort_values("Shutdown Date/Time", ascending=False),
    use_container_width=True,
    height=350
)

buffer = BytesIO()
filtered_df.to_excel(buffer, index=False)

st.download_button(
    "⬇ Download Filtered Data",
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

    reason = (
        well_df.groupby("ShutdownReason")
        .agg(Total_Downtime=("Downtime (Hrs)", "sum"))
        .reset_index()
    )

    fig_monthly = px.line(
        monthly,
        x="Shutdown Month",
        y="Shutdown Count",
        markers=True,
        title="Monthly Shutdown Trend"
    )

    fig_reason = px.pie(
    reason,
    names="ShutdownReason",
    values="Total_Downtime",
    hole=0.4,
    title="Downtime by Shutdown Reason",
    color="ShutdownReason",
    color_discrete_sequence=[
        "#1F77B4",  # blue
        "#FF7F0E",  # orange
        "#2CA02C",  # green
        "#D62728",  # red
        "#9467BD",  # purple
        "#8C564B"   # brown
    ]
)

    # -----------------------------
    # Save charts as images
    # -----------------------------
    tmp_dir = tempfile.mkdtemp()
    trend_img = os.path.join(tmp_dir, "trend.png")
    reason_img = os.path.join(tmp_dir, "reason.png")

    pio.write_image(fig_monthly, trend_img, width=800, height=400)
    pio.write_image(fig_reason, reason_img, width=600, height=400)

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

    table_df = well_df.sort_values(
        "Shutdown Date/Time", ascending=False
    ).head(20)[[
        "Shutdown Date/Time",
        "Start Up Date/Time",
        "Downtime (Hrs)",
        "ShutdownReason",
        "Alert"
    ]]

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
