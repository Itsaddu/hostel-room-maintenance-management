"""
Hostel Room & Maintenance Management System (HRMMS)
Tkinter GUI Application (SQLite backend)

Tabs:
  1. Student : Log Maintenance Complaint
  2. Admin   : Complaint Triage & Staff Assignment
  3. Warden  : Room Allocation & Occupancy Tracker

Run:  python tkinter_app.py
"""
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from datetime import date
from pathlib import Path

DATABASE_NAME = str(Path(__file__).resolve().with_name("hostel_management.db"))

CATEGORIES = ["Electrical", "Plumbing", "Carpentry", "Cleaning", "Network"]
STATUSES   = ["Pending", "In Progress", "Resolved", "Reopened"]


def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ROOM (
            Room_No TEXT,
            Block TEXT,
            Floor INTEGER NOT NULL,
            Capacity INTEGER NOT NULL,
            Current_Occupancy INTEGER DEFAULT 0,
            Gender_Policy TEXT NOT NULL DEFAULT 'Male',
            PRIMARY KEY (Room_No, Block)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS STUDENT (
            Roll_No TEXT PRIMARY KEY,
            Name TEXT NOT NULL,
            Gender TEXT NOT NULL CHECK(Gender IN ('Male','Female','Other')),
            Phone TEXT UNIQUE NOT NULL,
            Email TEXT UNIQUE NOT NULL,
            Room_No TEXT,
            Block TEXT,
            FOREIGN KEY (Room_No, Block) REFERENCES ROOM(Room_No, Block) ON DELETE SET NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS MAINTENANCE_STAFF (
            Staff_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Staff_Name TEXT NOT NULL,
            Specialization TEXT NOT NULL,
            Contact_No TEXT UNIQUE NOT NULL,
            Is_Available INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS COMPLAINT (
            Complaint_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Roll_No TEXT NOT NULL,
            Staff_ID INTEGER,
            Issue_Category TEXT NOT NULL,
            Description TEXT NOT NULL,
            Date_Logged TEXT DEFAULT (DATE('now')),
            Date_Resolved TEXT,
            Resolution_Status TEXT DEFAULT 'Pending',
            FOREIGN KEY (Roll_No) REFERENCES STUDENT(Roll_No) ON DELETE CASCADE,
            FOREIGN KEY (Staff_ID) REFERENCES MAINTENANCE_STAFF(Staff_ID) ON DELETE SET NULL
        )
    """)

    cur.execute("SELECT COUNT(*) FROM ROOM")
    if cur.fetchone()[0] == 0:
        rooms = [
            ('101', 'A', 1, 2, 0, 'Male'),
            ('102', 'A', 1, 2, 0, 'Male'),
            ('201', 'A', 2, 3, 0, 'Male'),
            ('101', 'B', 1, 2, 0, 'Male'),
            ('101', 'C', 1, 2, 0, 'Female'),
            ('102', 'C', 1, 2, 0, 'Female'),
        ]
        cur.executemany("INSERT INTO ROOM VALUES (?,?,?,?,?,?)", rooms)

        students = [
            ('AM.EN.U4CSE23001', 'Aditya Verma', 'Male',   '9876543210', 'aditya@example.com', '101', 'A'),
            ('AM.EN.U4CSE23002', 'Pooja Nair',   'Female', '9876543211', 'pooja@example.com',  '101', 'C'),
            ('AM.EN.U4CSE23003', 'Kiran Das',    'Male',   '9876543212', 'kiran@example.com',  '101', 'A'),
            ('AM.EN.U4CSE23004', 'Rahul Menon',  'Male',   '9876543213', 'rahul@example.com',  '102', 'A'),
        ]
        cur.executemany("INSERT INTO STUDENT VALUES (?,?,?,?,?,?,?)", students)

        staff = [
            ('Ramesh Kumar', 'Plumbing',   '9811122233', 1),
            ('Suresh Babu',  'Electrical', '9822233344', 1),
            ('Manoj Pillai', 'Carpentry',  '9833344455', 1),
            ('Lakshmi Devi', 'Cleaning',   '9844455566', 1),
            ('Vijay Kumar',  'Network',    '9855566677', 1),
        ]
        cur.executemany("INSERT INTO MAINTENANCE_STAFF (Staff_Name, Specialization, Contact_No, Is_Available) VALUES (?,?,?,?)", staff)

        complaints = [
            ('AM.EN.U4CSE23001', 1, 'Plumbing',   'Washroom faucet dripping', '2025-01-01', None, 'In Progress'),
            ('AM.EN.U4CSE23002', 2, 'Electrical', 'Tube light starter failure', '2025-01-05', None, 'Pending'),
            ('AM.EN.U4CSE23003', 1, 'Plumbing',   'Shower drain clogged', '2024-12-28', '2024-12-30', 'Resolved'),
        ]
        cur.executemany(
            "INSERT INTO COMPLAINT (Roll_No, Staff_ID, Issue_Category, Description, Date_Logged, Date_Resolved, Resolution_Status) VALUES (?,?,?,?,?,?,?)",
            complaints,
        )

        # Sync occupancy to match allocated students
        cur.execute("""
            UPDATE ROOM SET Current_Occupancy = (
                SELECT COUNT(*) FROM STUDENT s
                WHERE s.Room_No = ROOM.Room_No AND s.Block = ROOM.Block
            )
        """)

    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ----------------- Trigger emulations (Python side) -----------------

def recalc_occupancy(conn, room_no, block):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM STUDENT WHERE Room_No=? AND Block=?", (room_no, block))
    occ = cur.fetchone()[0]
    cur.execute("UPDATE ROOM SET Current_Occupancy=? WHERE Room_No=? AND Block=?", (occ, room_no, block))


def submit_complaint():
    roll = entry_roll.get().strip()
    category = combo_category.get().strip()
    desc = text_desc.get("1.0", tk.END).strip()
    if not (roll and category and desc):
        messagebox.showerror("Error", "All fields are required!")
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT Roll_No FROM STUDENT WHERE Roll_No=?", (roll,))
    if not cur.fetchone():
        messagebox.showerror("Invalid Student", f"Student '{roll}' does not exist.")
        conn.close()
        return
    cur.execute(
        "INSERT INTO COMPLAINT (Roll_No, Issue_Category, Description, Resolution_Status) VALUES (?,?,?,'Pending')",
        (roll, category, desc),
    )
    conn.commit()
    conn.close()
    messagebox.showinfo("Success", "Complaint lodged successfully!")
    entry_roll.delete(0, tk.END)
    text_desc.delete("1.0", tk.END)
    refresh_all()


def update_status(new_status):
    sel = tree_complaints.selection()
    if not sel:
        messagebox.showwarning("Warning", "Select a complaint first.")
        return
    cid = tree_complaints.item(sel[0])["values"][0]
    conn = get_conn()
    cur = conn.cursor()
    resolved = date.today().isoformat() if new_status == "Resolved" else None
    cur.execute("UPDATE COMPLAINT SET Resolution_Status=?, Date_Resolved=? WHERE Complaint_ID=?",
                (new_status, resolved, cid))
    conn.commit()
    conn.close()
    refresh_all()


def assign_staff():
    sel = tree_complaints.selection()
    if not sel:
        messagebox.showwarning("Warning", "Select a complaint first.")
        return
    cid = tree_complaints.item(sel[0])["values"][0]
    raw = combo_staff.get()
    if not raw:
        messagebox.showerror("Error", "Select a staff member.")
        return
    staff_id = int(raw.split(" - ")[0])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT Issue_Category FROM COMPLAINT WHERE Complaint_ID=?", (cid,))
    cat = cur.fetchone()[0]
    cur.execute("SELECT Specialization FROM MAINTENANCE_STAFF WHERE Staff_ID=?", (staff_id,))
    spec = cur.fetchone()[0]
    if spec != cat:
        messagebox.showerror(
            "Specialization Mismatch",
            f"Cannot assign {spec} staff to a {cat} complaint.",
        )
        conn.close()
        return
    cur.execute("UPDATE COMPLAINT SET Staff_ID=?, Resolution_Status='In Progress' WHERE Complaint_ID=?",
                (staff_id, cid))
    conn.commit()
    conn.close()
    refresh_all()


def allocate_student():
    roll = entry_alloc_roll.get().strip()
    room = entry_alloc_room.get().strip()
    block = entry_alloc_block.get().strip()
    if not (roll and room and block):
        messagebox.showerror("Error", "Roll No, Room No and Block are required.")
        return
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM STUDENT WHERE Roll_No=?", (roll,))
    stu = cur.fetchone()
    if not stu:
        messagebox.showerror("Error", "Student not found.")
        conn.close()
        return
    cur.execute("SELECT * FROM ROOM WHERE Room_No=? AND Block=?", (room, block))
    r = cur.fetchone()
    if not r:
        messagebox.showerror("Error", "Room not found.")
        conn.close()
        return
    if r["Gender_Policy"] != "Coed" and r["Gender_Policy"] != stu["Gender"]:
        messagebox.showerror("Gender Restriction", f"Block {block} is {r['Gender_Policy']} only.")
        conn.close()
        return
    if r["Current_Occupancy"] >= r["Capacity"]:
        messagebox.showerror("Full", f"Room {block}-{room} is at full capacity.")
        conn.close()
        return
    old_room, old_block = stu["Room_No"], stu["Block"]
    cur.execute("UPDATE STUDENT SET Room_No=?, Block=? WHERE Roll_No=?", (room, block, roll))
    recalc_occupancy(conn, room, block)
    if old_room:
        recalc_occupancy(conn, old_room, old_block)
    conn.commit()
    conn.close()
    messagebox.showinfo("Success", "Student allocated.")
    entry_alloc_roll.delete(0, tk.END)
    entry_alloc_room.delete(0, tk.END)
    entry_alloc_block.delete(0, tk.END)
    refresh_all()


def vacate_student():
    roll = entry_vacate_roll.get().strip()
    if not roll:
        messagebox.showerror("Error", "Roll No is required.")
        return
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT Room_No, Block FROM STUDENT WHERE Roll_No=?", (roll,))
    s = cur.fetchone()
    if not s:
        messagebox.showerror("Error", "Student not found.")
        conn.close()
        return
    room, block = s["Room_No"], s["Block"]
    cur.execute("UPDATE STUDENT SET Room_No=NULL, Block=NULL WHERE Roll_No=?", (roll,))
    if room:
        recalc_occupancy(conn, room, block)
    conn.commit()
    conn.close()
    messagebox.showinfo("Success", "Student vacated.")
    entry_vacate_roll.delete(0, tk.END)
    refresh_all()


def refresh_all():
    for row in tree_complaints.get_children():
        tree_complaints.delete(row)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.Complaint_ID, c.Roll_No, s.Name, c.Issue_Category,
               COALESCE(st.Staff_Name, 'Unassigned'), c.Resolution_Status, c.Description
        FROM COMPLAINT c
        JOIN STUDENT s ON c.Roll_No = s.Roll_No
        LEFT JOIN MAINTENANCE_STAFF st ON c.Staff_ID = st.Staff_ID
        ORDER BY c.Complaint_ID
    """)
    for row in cur.fetchall():
        tree_complaints.insert("", tk.END, values=row)

    for row in tree_rooms.get_children():
        tree_rooms.delete(row)
    cur.execute("""
        SELECT Block, Room_No, Floor, Capacity, Current_Occupancy,
               (Capacity - Current_Occupancy) AS Available, Gender_Policy
        FROM ROOM ORDER BY Block, Floor, Room_No
    """)
    for row in cur.fetchall():
        tree_rooms.insert("", tk.END, values=row)

    cur.execute("SELECT Staff_ID, Staff_Name, Specialization FROM MAINTENANCE_STAFF WHERE Is_Available=1")
    staff_list = [f"{sid} - {name} ({spec})" for sid, name, spec in cur.fetchall()]
    combo_staff['values'] = staff_list
    if staff_list:
        combo_staff.current(0)
    conn.close()


# ----------------- UI Layout -----------------
init_db()
root = tk.Tk()
root.title("Hostel Room & Maintenance Management System (HRMMS)")
root.geometry("980x640")

notebook = ttk.Notebook(root)
notebook.pack(fill="both", expand=True, padx=10, pady=10)

# TAB 1 : Student Complaint Portal
tab1 = ttk.Frame(notebook)
notebook.add(tab1, text="Student: Log Issue")

f1 = ttk.LabelFrame(tab1, text="Register Maintenance Request", padding=15)
f1.pack(fill="both", expand=True, padx=20, pady=20)

ttk.Label(f1, text="Roll Number:").grid(row=0, column=0, sticky="w", pady=6)
entry_roll = ttk.Entry(f1, width=30)
entry_roll.grid(row=0, column=1, sticky="w", pady=6)

ttk.Label(f1, text="Category:").grid(row=1, column=0, sticky="w", pady=6)
combo_category = ttk.Combobox(f1, values=CATEGORIES, width=28, state="readonly")
combo_category.current(0)
combo_category.grid(row=1, column=1, sticky="w", pady=6)

ttk.Label(f1, text="Problem Details:").grid(row=2, column=0, sticky="nw", pady=6)
text_desc = tk.Text(f1, width=45, height=6)
text_desc.grid(row=2, column=1, sticky="w", pady=6)

ttk.Button(f1, text="Submit Complaint", command=submit_complaint).grid(row=3, column=1, sticky="e", pady=12)

# TAB 2 : Admin Dashboard
tab2 = ttk.Frame(notebook)
notebook.add(tab2, text="Admin: Issue Triage")

cols = ("ID", "Roll No", "Student Name", "Category", "Technician", "Status", "Description")
tree_complaints = ttk.Treeview(tab2, columns=cols, show="headings", height=12)
for col in cols:
    tree_complaints.heading(col, text=col)
    tree_complaints.column(col, width=110)
tree_complaints.pack(fill="both", expand=True, padx=10, pady=10)

action_bar = ttk.Frame(tab2, padding=5)
action_bar.pack(fill="x", padx=10, pady=5)
combo_staff = ttk.Combobox(action_bar, width=34, state="readonly")
combo_staff.pack(side="left", padx=5)
ttk.Button(action_bar, text="Assign Staff", command=assign_staff).pack(side="left", padx=5)
ttk.Button(action_bar, text="Set In Progress", command=lambda: update_status("In Progress")).pack(side="left", padx=5)
ttk.Button(action_bar, text="Mark Resolved", command=lambda: update_status("Resolved")).pack(side="left", padx=5)
ttk.Button(action_bar, text="Reopen", command=lambda: update_status("Reopened")).pack(side="left", padx=5)
ttk.Button(action_bar, text="Refresh", command=refresh_all).pack(side="right", padx=5)

# TAB 3 : Room Allocation & Occupancy
tab3 = ttk.Frame(notebook)
notebook.add(tab3, text="Warden: Room Capacity Tracker")

room_cols = ("Block", "Room No", "Floor", "Capacity", "Occupied", "Available", "Policy")
tree_rooms = ttk.Treeview(tab3, columns=room_cols, show="headings", height=10)
for col in room_cols:
    tree_rooms.heading(col, text=col)
    tree_rooms.column(col, width=100)
tree_rooms.pack(fill="both", expand=True, padx=15, pady=10)

alloc_frame = ttk.LabelFrame(tab3, text="Allocate / Vacate", padding=10)
alloc_frame.pack(fill="x", padx=15, pady=5)

ttk.Label(alloc_frame, text="Roll No:").grid(row=0, column=0, padx=4)
entry_alloc_roll = ttk.Entry(alloc_frame, width=18)
entry_alloc_roll.grid(row=0, column=1, padx=4)
ttk.Label(alloc_frame, text="Room No:").grid(row=0, column=2, padx=4)
entry_alloc_room = ttk.Entry(alloc_frame, width=8)
entry_alloc_room.grid(row=0, column=3, padx=4)
ttk.Label(alloc_frame, text="Block:").grid(row=0, column=4, padx=4)
entry_alloc_block = ttk.Entry(alloc_frame, width=8)
entry_alloc_block.grid(row=0, column=5, padx=4)
ttk.Button(alloc_frame, text="Allocate", command=allocate_student).grid(row=0, column=6, padx=6)

ttk.Label(alloc_frame, text="Vacate Roll No:").grid(row=0, column=7, padx=4)
entry_vacate_roll = ttk.Entry(alloc_frame, width=18)
entry_vacate_roll.grid(row=0, column=8, padx=4)
ttk.Button(alloc_frame, text="Vacate", command=vacate_student).grid(row=0, column=9, padx=6)

refresh_all()
root.mainloop()
