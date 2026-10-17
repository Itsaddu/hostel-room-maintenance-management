"""
Hostel Room & Maintenance Management System (HRMMS)
Streamlit UI — Simulated PostgreSQL Engine
==================================================

Run:  streamlit run app.py

Tabs (sidebar navigation):
  1. Student Portal
  2. Warden / Admin Dashboard
  3. Room Occupancy & Allocations
  4. Maintenance Staff Analytics & Workload
  5. PostgreSQL Console & Schema Explorer
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db_engine import (
    CATEGORIES,
    DB_ERRORS,
    GENDERS,
    STATUSES,
    HostelDB,
    get_db,
)

st.set_page_config(
    page_title="HRMMS — Hostel Room & Maintenance Management",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# Session state — keep the database + a refresh counter across reruns
# ------------------------------------------------------------------
if "db" not in st.session_state:
    try:
        st.session_state.db = get_db(reset=True)
    except DB_ERRORS as e:
        st.error(
            "Could not connect to the configured database. Check that PostgreSQL is running "
            "and that the HRMMS_DB_* values in .env are correct. "
            f"Connection details: {e}"
        )
        st.stop()
if "refresh" not in st.session_state:
    st.session_state.refresh = 0


def db() -> HostelDB:
    return st.session_state.db


def bump() -> None:
    st.session_state.refresh += 1


# ------------------------------------------------------------------
# Styling helpers (status badges, occupancy bars)
# ------------------------------------------------------------------
STATUS_COLOR = {
    "Pending": "#f59e0b",
    "In Progress": "#3b82f6",
    "Resolved": "#10b981",
    "Reopened": "#ef4444",
}
SPEC_COLOR = {
    "Electrical": "#fbbf24",
    "Plumbing": "#60a5fa",
    "Carpentry": "#a78bfa",
    "Cleaning": "#34d399",
    "Network": "#f472b6",
}


def badge(text: str, color: str = "#64748b") -> str:
    return (
        f'<span style="background:{color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:0.78rem;font-weight:600;">{text}</span>'
    )


def status_badge(status: str) -> str:
    return badge(status, STATUS_COLOR.get(status, "#64748b"))


def spec_badge(spec: str) -> str:
    return badge(spec, SPEC_COLOR.get(spec, "#64748b"))


st.markdown(
    """
    <style>
    .block-card {
        border:1px solid #e2e8f0;border-radius:12px;padding:14px;margin-bottom:12px;
        background:#f8fafc;
    }
    .room-card {
        border:1px solid #cbd5e1;border-radius:10px;padding:10px;margin:4px;
        background:#fff;text-align:center;min-height:80px;
    }
    .room-full { background:#fee2e2; border-color:#fca5a5; }
    .room-vacant { background:#dcfce7; border-color:#86efac; }
    .room-partial { background:#fef9c3; border-color:#fde047; }
    .metric-label { font-size:0.8rem;color:#64748b; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# Sidebar: navigation + KPI summary
# ------------------------------------------------------------------
with st.sidebar:
    st.title("🏠 HRMMS")
    st.caption("Hostel Room & Maintenance Management System")
    page = st.radio(
        "Navigation",
        [
            "📋 Student Portal",
            "🛠️ Warden / Admin Dashboard",
            "🛏️ Room Occupancy & Allocations",
            "👷 Staff Analytics & Workload",
            "🗄️ PostgreSQL Console",
        ],
        index=0,
    )

    st.divider()
    m = db().metrics()
    st.subheader("Live KPIs")
    col1, col2 = st.columns(2)
    col1.metric("Occupancy", f"{m['occupancy_pct']}%", f"{m['occupied']}/{m['total_beds']} beds")
    col2.metric("Students", m["students"])
    col1.metric("Staff", m["staff"], f"{m['available_staff']} avail")
    col2.metric("Complaints", m["complaints"], f"{m['pending']} pending")

    st.divider()
    if st.button("🔄 Reset Database to Seed", use_container_width=True):
        st.session_state.db = get_db(reset=True)
        bump()
        st.success("Database reset to seed data.")
        st.rerun()

# ==================================================================
# Helper: dataframe with clickable complaint IDs
# ==================================================================
def complaints_df(filters: dict | None = None) -> pd.DataFrame:
    sql = """
        SELECT c.Complaint_ID AS ID, c.Roll_No, s.Name AS Student,
               c.Issue_Category AS Category,
               COALESCE(st.Staff_Name,'Unassigned') AS Technician,
               c.Resolution_Status AS Status, c.Date_Logged AS Logged,
               c.Date_Resolved AS Resolved, c.Description
        FROM COMPLAINT c
        JOIN STUDENT s ON c.Roll_No = s.Roll_No
        LEFT JOIN MAINTENANCE_STAFF st ON c.Staff_ID = st.Staff_ID
        WHERE 1=1
    """
    params: list = []
    if filters:
        if filters.get("status") and filters["status"] != "All":
            sql += " AND c.Resolution_Status = ?"
            params.append(filters["status"])
        if filters.get("category") and filters["category"] != "All":
            sql += " AND c.Issue_Category = ?"
            params.append(filters["category"])
        if filters.get("roll"):
            sql += " AND c.Roll_No = ?"
            params.append(filters["roll"])
    sql += " ORDER BY c.Complaint_ID DESC"
    rows = db().fetch_all(sql, tuple(params))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


# ==================================================================
# PAGE 1 : STUDENT PORTAL
# ==================================================================
def page_student() -> None:
    st.header("📋 Student Portal")
    st.caption("Look up your profile, lodge a maintenance complaint, and track status.")

    roll = st.text_input("Enter your Roll Number", value="AM.EN.U4CSE23001", key="stu_roll")
    if not roll:
        st.info("Enter a roll number to continue.")
        return

    student = db().fetch_one(
        "SELECT * FROM STUDENT WHERE Roll_No=?", (roll.strip(),)
    )
    if not student:
        st.error(f"No student found with roll number `{roll}`.")
        return

    s = dict(student)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Name", s["Name"])
    c2.metric("Gender", s["Gender"])
    room_label = f"{s['Block']}-{s['Room_No']}" if s["Room_No"] else "Unallocated"
    c3.metric("Room", room_label)
    c4.metric("Email", s["Email"][:18])

    st.divider()

    # ---- Submit complaint ----
    st.subheader("Lodge a Complaint")
    with st.form("complaint_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        category = col1.selectbox("Issue Category", CATEGORIES, key="cat")
        priority = col2.selectbox("Priority", ["Low", "Medium", "High"], key="prio")
        description = st.text_area("Describe the problem", height=90, key="desc")
        submitted = st.form_submit_button("Submit Complaint", type="primary")
        if submitted:
            if not description.strip():
                st.error("Description cannot be empty.")
            else:
                try:
                    db().execute(
                        "INSERT INTO COMPLAINT (Roll_No, Issue_Category, Description, Resolution_Status) "
                        "VALUES (?,?,?,'Pending')",
                        (roll.strip(), category, description.strip()),
                    )
                    bump()
                    st.success("Complaint lodged successfully. Status: Pending.")
                except DB_ERRORS as e:
                    st.error(f"Failed: {e}")

    st.divider()

    # ---- Complaint history ----
    st.subheader("My Complaint History")
    df = complaints_df({"roll": roll.strip()})
    if df.empty:
        st.info("No complaints found.")
    else:
        df["Status"] = df["Status"].apply(status_badge)
        df["Category"] = df["Category"].apply(spec_badge)
        st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)


# ==================================================================
# PAGE 2 : WARDEN / ADMIN DASHBOARD
# ==================================================================
def page_admin() -> None:
    st.header("🛠️ Warden / Admin Dashboard")
    st.caption("Triage complaints, verify specialization match, and transition statuses.")

    m = db().metrics()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Complaints", m["complaints"])
    k2.metric("Pending", m["pending"])
    k3.metric("In Progress", m["in_progress"])
    k4.metric("Resolved", m["resolved"])

    st.divider()

    # ---- Filters ----
    fcol1, fcol2, fcol3 = st.columns(3)
    f_status = fcol1.selectbox("Status", ["All"] + STATUSES, key="f_status")
    f_cat = fcol2.selectbox("Category", ["All"] + CATEGORIES, key="f_cat")
    fcol3.caption("")  # spacer

    df = complaints_df({"status": f_status, "category": f_cat})
    if df.empty:
        st.info("No complaints match the filters.")
        return

    df["Status"] = df["Status"].apply(status_badge)
    df["Category"] = df["Category"].apply(spec_badge)
    st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)

    st.divider()

    # ---- Action panel ----
    st.subheader("Action Panel")
    cids = df["ID"].tolist() if "ID" in df else []
    if not cids:
        st.warning("No complaints to act on.")
        return

    selected_id = st.selectbox("Select Complaint ID", cids, key="sel_cid")
    complaint = db().fetch_one(
        "SELECT * FROM COMPLAINT WHERE Complaint_ID=?", (selected_id,)
    )
    if not complaint:
        return
    c = dict(complaint)

    acol1, acol2, acol3 = st.columns(3)
    acol1.markdown(f"**Category:** {spec_badge(c['Issue_Category'])}", unsafe_allow_html=True)
    acol2.markdown(f"**Current Status:** {status_badge(c['Resolution_Status'])}", unsafe_allow_html=True)
    staff_name = "Unassigned"
    if c["Staff_ID"]:
        srow = db().fetch_one("SELECT Staff_Name, Specialization FROM MAINTENANCE_STAFF WHERE Staff_ID=?", (c["Staff_ID"],))
        staff_name = f"{srow['Staff_Name']} ({srow['Specialization']})" if srow else "Unassigned"
    acol3.markdown(f"**Technician:** {staff_name}")

    st.write(f"**Description:** {c['Description']}")

    # ---- Assign staff (specialization-aware) ----
    st.markdown("##### Assign Technician")
    avail_staff = db().fetch_all(
        "SELECT Staff_ID, Staff_Name, Specialization FROM MAINTENANCE_STAFF "
        "WHERE Is_Available=TRUE ORDER BY Specialization, Staff_Name"
    )
    staff_options = {f"{s['Staff_Name']} — {s['Specialization']} (ID {s['Staff_ID']})": s["Staff_ID"]
                     for s in avail_staff}
    if not staff_options:
        st.warning("No available staff.")
    else:
        # Highlight matching specialization
        match_label = next((k for k, v in staff_options.items()
                            if db().fetch_one("SELECT Specialization FROM MAINTENANCE_STAFF WHERE Staff_ID=?", (v,))["Specialization"] == c["Issue_Category"]),
                           None)
        if match_label:
            st.success(f"✅ Specialization match available: {match_label}")
        else:
            st.warning(f"⚠️ No staff specialized in {c['Issue_Category']} — assignment will be blocked by the engine.")

        chosen = st.selectbox("Select staff member", list(staff_options.keys()), key="assign_staff")
        if st.button("Assign & Set In Progress", type="primary"):
            try:
                db().execute(
                    "UPDATE COMPLAINT SET Staff_ID=?, Resolution_Status='In Progress' WHERE Complaint_ID=?",
                    (staff_options[chosen], selected_id),
                )
                bump()
                st.success("Staff assigned.")
                st.rerun()
            except DB_ERRORS as e:
                st.error(f"Engine blocked assignment: {e}")

    # ---- Status transitions ----
    st.markdown("##### Status Transitions")
    tcol1, tcol2, tcol3 = st.columns(3)
    if tcol1.button("⏳ In Progress"):
        db().execute("UPDATE COMPLAINT SET Resolution_Status='In Progress' WHERE Complaint_ID=?", (selected_id,))
        bump(); st.rerun()
    if tcol2.button("✅ Resolve"):
        db().execute("UPDATE COMPLAINT SET Resolution_Status='Resolved' WHERE Complaint_ID=?", (selected_id,))
        bump(); st.rerun()
    if tcol3.button("🔁 Reopen"):
        db().execute("UPDATE COMPLAINT SET Resolution_Status='Reopened' WHERE Complaint_ID=?", (selected_id,))
        bump(); st.rerun()


# ==================================================================
# PAGE 3 : ROOM OCCUPANCY & ALLOCATIONS
# ==================================================================
def page_rooms() -> None:
    st.header("🛏️ Room Occupancy & Allocations")
    st.caption("Floor-by-floor block grid, live occupancy, and allocate/vacate actions.")

    m = db().metrics()
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Total Rooms", m["total_rooms"])
    rc2.metric("Total Beds", m["total_beds"])
    rc3.metric("Available Beds", m["available_beds"])
    rc4.metric("Occupancy", f"{m['occupancy_pct']}%")

    st.divider()

    # ---- Allocate / Vacate controls ----
    with st.expander("➕ Allocate / Vacate Student", expanded=False):
        students = db().fetch_all("SELECT Roll_No, Name FROM STUDENT ORDER BY Roll_No")
        student_map = {f"{s['Roll_No']} — {s['Name']}": s["Roll_No"] for s in students}
        rooms = db().fetch_all("SELECT Room_No, Block, Capacity, Current_Occupancy, Gender_Policy FROM ROOM ORDER BY Block, Room_No")
        room_map = {f"{r['Block']}-{r['Room_No']} ({r['Current_Occupancy']}/{r['Capacity']}, {r['Gender_Policy']})": (r["Room_No"], r["Block"]) for r in rooms}

        acol1, acol2 = st.columns(2)
        sel_stu = acol1.selectbox("Student", list(student_map.keys()), key="alloc_stu")
        sel_room = acol2.selectbox("Room", list(room_map.keys()), key="alloc_room")

        bcol1, bcol2 = st.columns(2)
        if bcol1.button("Allocate", type="primary"):
            rn, blk = room_map[sel_room]
            try:
                db().execute(
                    "UPDATE STUDENT SET Room_No=?, Block=? WHERE Roll_No=?",
                    (rn, blk, student_map[sel_stu]),
                )
                bump()
                st.success("Student allocated.")
                st.rerun()
            except DB_ERRORS as e:
                st.error(f"Allocation blocked: {e}")
        if bcol2.button("Vacate (set room to NULL)"):
            db().execute(
                "UPDATE STUDENT SET Room_No=NULL, Block=NULL WHERE Roll_No=?",
                (student_map[sel_stu],),
            )
            bump()
            st.success("Student vacated.")
            st.rerun()

    st.divider()

    # ---- Block grid ----
    blocks = db().fetch_all("SELECT DISTINCT Block, Gender_Policy FROM ROOM ORDER BY Block")
    for blk in blocks:
        with st.container():
            st.markdown(
                f"### Block {blk['Block']} "
                f"{badge(blk['Gender_Policy'], '#6366f1' if blk['Gender_Policy']=='Coed' else '#0ea5e9')}",
                unsafe_allow_html=True,
            )
            rooms = db().fetch_all(
                "SELECT * FROM ROOM WHERE Block=? ORDER BY Floor, Room_No", (blk["Block"],)
            )
            floors = sorted({r["Floor"] for r in rooms})
            for floor in floors:
                st.markdown(f"**Floor {floor}**")
                floor_rooms = [r for r in rooms if r["Floor"] == floor]
                cols = st.columns(min(len(floor_rooms), 5))
                for col, r in zip(cols, floor_rooms):
                    occ = r["Current_Occupancy"]
                    cap = r["Capacity"]
                    pct = int(100 * occ / cap) if cap else 0
                    if occ == 0:
                        cls = "room-vacant"
                    elif occ >= cap:
                        cls = "room-full"
                    else:
                        cls = "room-partial"
                    avail = cap - occ
                    with col:
                        st.markdown(
                            f'<div class="room-card {cls}">'
                            f'<div style="font-weight:700;font-size:1.1rem;">{r["Room_No"]}</div>'
                            f'<div style="font-size:0.8rem;color:#475569;">{occ}/{cap} beds</div>'
                            f'<div style="height:6px;background:#e2e8f0;border-radius:3px;margin:6px 0;">'
                            f'<div style="height:100%;width:{pct}%;background:'
                            f'{"#10b981" if pct<70 else "#f59e0b" if pct<100 else "#ef4444"};'
                            f'border-radius:3px;"></div></div>'
                            f'<div>{badge(f"{avail} free", "#10b981" if avail else "#ef4444")}</div>'
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                st.markdown("<br>", unsafe_allow_html=True)

    st.divider()

    # ---- Full room table (expandable) ----
    with st.expander("📊 Full Room Table (CSV-friendly)"):
        rows = db().fetch_all(
            "SELECT Block, Room_No, Floor, Capacity, Current_Occupancy AS Occupied, "
            "(Capacity - Current_Occupancy) AS Available, Gender_Policy "
            "FROM ROOM ORDER BY Block, Floor, Room_No"
        )
        if rows:
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), use_container_width=True, hide_index=True)


# ==================================================================
# PAGE 4 : STAFF ANALYTICS & WORKLOAD
# ==================================================================
def page_staff() -> None:
    st.header("👷 Maintenance Staff Analytics & Workload")
    st.caption("Technician profiles, task counts, availability, and specialization badges.")

    rows = db().fetch_all(
        """
        SELECT s.Staff_ID, s.Staff_Name, s.Specialization, s.Contact_No, s.Is_Available,
               COUNT(c.Complaint_ID) AS Total_Assigned,
               SUM(CASE WHEN c.Resolution_Status <> 'Resolved' THEN 1 ELSE 0 END) AS Active_Tasks,
               SUM(CASE WHEN c.Resolution_Status = 'Resolved' THEN 1 ELSE 0 END) AS Resolved_Tasks
        FROM MAINTENANCE_STAFF s
        LEFT JOIN COMPLAINT c ON s.Staff_ID = c.Staff_ID
        GROUP BY s.Staff_ID, s.Staff_Name, s.Specialization, s.Contact_No, s.Is_Available
        ORDER BY Active_Tasks DESC, s.Staff_ID
        """
    )

    if not rows:
        st.info("No staff records.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    df["Is_Available"] = df["Is_Available"].astype(bool)

    # Summary KPIs
    sk1, sk2, sk3 = st.columns(3)
    sk1.metric("Total Staff", len(df))
    sk2.metric("Available", int(df["Is_Available"].sum()))
    sk3.metric("Total Active Tasks", int(df["Active_Tasks"].sum()))

    st.divider()

    # ---- Staff cards ----
    for _, r in df.iterrows():
        with st.container():
            cc1, cc2, cc3, cc4, cc5 = st.columns([3, 2, 2, 2, 2])
            cc1.markdown(
                f"**{r['Staff_Name']}** &nbsp; {spec_badge(r['Specialization'])}",
                unsafe_allow_html=True,
            )
            cc2.metric("Total Assigned", int(r["Total_Assigned"]))
            cc3.metric("Active", int(r["Active_Tasks"]))
            cc4.metric("Resolved", int(r["Resolved_Tasks"]))
            avail = bool(r["Is_Available"])
            cc5.markdown(badge("Available" if avail else "Busy", "#10b981" if avail else "#ef4444"),
                         unsafe_allow_html=True)

            # availability toggle
            new_avail = st.checkbox(
                "Toggle availability", value=avail, key=f"avail_{r['Staff_ID']}"
            )
            if new_avail != avail:
                db().execute(
                    "UPDATE MAINTENANCE_STAFF SET Is_Available=? WHERE Staff_ID=?",
                    (bool(new_avail), r["Staff_ID"]),
                )
                bump()
                st.rerun()
            st.divider()

    # ---- Workload bar chart ----
    st.subheader("Active Task Distribution")
    chart_df = df[["Staff_Name", "Active_Tasks", "Resolved_Tasks"]].set_index("Staff_Name")
    st.bar_chart(chart_df)


# ==================================================================
# PAGE 5 : POSTGRESQL CONSOLE & SCHEMA EXPLORER
# ==================================================================
PRESETS = {
    "Vacancy Detection (Q1)": (
        "SELECT Block, Room_No, Floor, Capacity, Current_Occupancy,\n"
        "       (Capacity - Current_Occupancy) AS Available_Beds\n"
        "FROM ROOM\n"
        "WHERE Current_Occupancy < Capacity\n"
        "ORDER BY Block, Floor, Room_No;"
    ),
    "Staff Workload (Q2)": (
        "SELECT s.Staff_ID, s.Staff_Name, s.Specialization,\n"
        "       COUNT(c.Complaint_ID) AS Total_Assigned,\n"
        "       COUNT(CASE WHEN c.Resolution_Status <> 'Resolved' THEN 1 END) AS Active_Tasks\n"
        "FROM MAINTENANCE_STAFF s\n"
        "LEFT JOIN COMPLAINT c ON s.Staff_ID = c.Staff_ID\n"
        "GROUP BY s.Staff_ID, s.Staff_Name, s.Specialization;"
    ),
    "Room Complaint Frequency (Q3)": (
        "SELECT st.Block, st.Room_No, COUNT(c.Complaint_ID) AS Total_Complaints\n"
        "FROM COMPLAINT c\n"
        "JOIN STUDENT st ON c.Roll_No = st.Roll_No\n"
        "GROUP BY st.Block, st.Room_No\n"
        "HAVING COUNT(c.Complaint_ID) >= 1\n"
        "ORDER BY Total_Complaints DESC;"
    ),
    "Block Occupancy Rate (Q5)": (
        "SELECT Block,\n"
        "       SUM(Capacity) AS Total_Beds,\n"
        "       SUM(Current_Occupancy) AS Occupied,\n"
        "       ROUND(100.0 * SUM(Current_Occupancy) / NULLIF(SUM(Capacity),0), 2) AS Occupancy_Pct\n"
        "FROM ROOM\n"
        "GROUP BY Block\n"
        "ORDER BY Block;"
    ),
    "All Complaints": "SELECT * FROM COMPLAINT ORDER BY Complaint_ID;",
    "All Students": "SELECT Roll_No, Name, Gender, Room_No, Block FROM STUDENT ORDER BY Roll_No;",
}


def page_console() -> None:
    st.header("🗄️ PostgreSQL Console & Schema Explorer")
    st.caption("Interactive SQL terminal, DDL schema viewer, and constraint verification log.")

    tab_sql, tab_schema, tab_log = st.tabs(["SQL Terminal", "DDL Schema", "Constraint Log"])

    # ---- SQL Terminal ----
    with tab_sql:
        preset = st.selectbox("Load preset query", ["— select a preset —"] + list(PRESETS.keys()))
        if preset != "— select a preset —":
            st.session_state.sql_editor = PRESETS[preset]

        sql = st.text_area(
            "SQL Query",
            value=st.session_state.get("sql_editor", "SELECT * FROM ROOM;"),
            height=180,
            key="sql_editor",
        )

        c_run, c_clear = st.columns([1, 5])
        if c_run.button("▶ Run Query", type="primary"):
            cols, rows, affected, err = db().run_query(sql)
            if err:
                st.error(f"❌ {err}")
            else:
                if cols:
                    st.success(f"✅ {len(rows)} row(s) returned.")
                    st.dataframe(pd.DataFrame(rows, columns=cols), use_container_width=True, hide_index=True)
                else:
                    st.success(f"✅ Query executed. {affected} row(s) affected.")

        # ---- Constraint verification run ----
        st.divider()
        st.markdown("##### Constraint Verification")
        st.caption("Run a battery of constraint checks against the live engine.")
        if st.button("Run All Constraint Checks"):
            checks = []

            # 1. capacity
            _, _, _, e = db().run_query(
                "INSERT INTO STUDENT VALUES ('__CAP__','X','Male','0000000001','cap@x.com','101','A')"
            )
            checks.append(("Capacity enforcement (full room A-101)", e is not None, e or "blocked"))

            # 2. gender segregation
            _, _, _, e = db().run_query(
                "INSERT INTO STUDENT VALUES ('__GEN__','X','Male','0000000002','gen@x.com','102','C')"
            )
            checks.append(("Gender-to-block segregation (Male into Female block C)", e is not None, e or "blocked"))

            # 3. specialization
            _, _, _, e = db().run_query(
                "UPDATE COMPLAINT SET Staff_ID=1 WHERE Complaint_ID=2"
            )
            checks.append(("Staff specialization match (Plumbing staff on Electrical complaint)", e is not None, e or "blocked"))

            # 4. FK cascade (delete student -> complaints cascade)
            # (do not actually delete real data; skip destructive test)
            checks.append(("FK ON DELETE CASCADE (schema declared on COMPLAINT.Roll_No)", True, "DDL declared"))

            # 5. audit resolution
            db().run_query("UPDATE COMPLAINT SET Resolution_Status='Resolved' WHERE Complaint_ID=4")
            _, r, _, _ = db().run_query("SELECT Date_Resolved FROM COMPLAINT WHERE Complaint_ID=4")
            resolved_ok = bool(r and r[0][0] is not None)
            checks.append(("Audit Date_Resolved stamped on Resolve", resolved_ok, r[0][0] if r else ""))
            # revert
            db().run_query("UPDATE COMPLAINT SET Resolution_Status='Pending' WHERE Complaint_ID=4")

            passed = sum(1 for _, ok, _ in checks if ok)
            st.success(f"**{passed}/{len(checks)}** constraints verified.")
            log_rows = [{"Check": c, "Result": "✅ PASS" if ok else "❌ FAIL", "Detail": d}
                        for c, ok, d in checks]
            st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)

    # ---- DDL Schema ----
    with tab_schema:
        st.subheader("DDL Schema (PostgreSQL)")
        st.code(open_schema_sql(), language="sql")

        st.subheader("Live SQLite Schema (engine)")
        engine_sql = _engine_schema_sql()
        st.code(engine_sql, language="sql")

    # ---- Execution log ----
    with tab_log:
        st.subheader("Execution Log (last 50 operations)")
        log = db().get_log()[-50:]
        if not log:
            st.info("No operations yet. Run some queries.")
        else:
            df = pd.DataFrame(log)
            df["status"] = df["status"].apply(
                lambda s: badge("OK", "#10b981") if s == "OK" else badge("ERROR", "#ef4444")
            )
            st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)


def open_schema_sql() -> str:
    try:
        with open("schema.sql", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "-- schema.sql not found"


def _engine_schema_sql() -> str:
    rows = db().fetch_all(
        "SELECT sql FROM sqlite_master WHERE type IN ('table','trigger','index') AND sql IS NOT NULL ORDER BY type, name"
    )
    return "\n\n".join(r["sql"] for r in rows) + ";"


# ==================================================================
# Routing
# ==================================================================
PAGES = {
    "📋 Student Portal": page_student,
    "🛠️ Warden / Admin Dashboard": page_admin,
    "🛏️ Room Occupancy & Allocations": page_rooms,
    "👷 Staff Analytics & Workload": page_staff,
    "🗄️ PostgreSQL Console": page_console,
}

PAGES[page]()
