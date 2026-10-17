"""
db_engine.py — Simulated PostgreSQL Engine for HRMMS
=====================================================
A stateful relational layer that emulates PostgreSQL behaviour on top of
SQLite, including:

  * Real database-level triggers (SQLite) that mirror the PostgreSQL
    triggers in schema.sql:
        - trg_sync_room_occupancy   (auto-update room occupancy)
        - trg_staff_specialization  (staff specialization match)
        - trg_gender_block          (gender-to-block segregation)
        - trg_audit_resolution      (stamp Date_Resolved on 'Resolved')
        - trg_capacity_enforcement  (prevent over-allocation)
  * Foreign-key cascades (ON DELETE CASCADE / SET NULL)
  * An execution log that records every DML statement with timestamps
  * A generic run_query() SQL console that supports SELECT / INSERT /
    UPDATE / DELETE and returns tabular results for SELECT.

This module is importable by both the Streamlit app and any test script.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hrmms_streamlit.db")
DB_BACKEND = os.getenv("HRMMS_DB_BACKEND", "sqlite").strip().lower()
DB_ERRORS = (sqlite3.Error, psycopg.Error)

CATEGORIES = ["Electrical", "Plumbing", "Carpentry", "Cleaning", "Network"]
STATUSES = ["Pending", "In Progress", "Resolved", "Reopened"]
GENDERS = ["Male", "Female", "Other"]
GENDER_POLICIES = ["Male", "Female", "Coed"]

# ------------------------------------------------------------------
# Schema DDL (SQLite dialect) + Triggers
# ------------------------------------------------------------------
SCHEMA_SQL = """
DROP TABLE IF EXISTS COMPLAINT;
DROP TABLE IF EXISTS MAINTENANCE_STAFF;
DROP TABLE IF EXISTS STUDENT;
DROP TABLE IF EXISTS ROOM;

CREATE TABLE ROOM (
    Room_No           TEXT NOT NULL,
    Block             TEXT NOT NULL,
    Floor             INTEGER NOT NULL CHECK (Floor >= 0),
    Capacity          INTEGER NOT NULL CHECK (Capacity > 0),
    Current_Occupancy INTEGER DEFAULT 0,
    Gender_Policy     TEXT NOT NULL DEFAULT 'Male'
        CHECK (Gender_Policy IN ('Male','Female','Coed')),
    PRIMARY KEY (Room_No, Block),
    CHECK (Current_Occupancy <= Capacity AND Current_Occupancy >= 0)
);

CREATE TABLE STUDENT (
    Roll_No TEXT PRIMARY KEY,
    Name    TEXT NOT NULL,
    Gender  TEXT NOT NULL CHECK (Gender IN ('Male','Female','Other')),
    Phone   TEXT UNIQUE NOT NULL,
    Email   TEXT UNIQUE NOT NULL,
    Room_No TEXT,
    Block   TEXT,
    FOREIGN KEY (Room_No, Block) REFERENCES ROOM(Room_No, Block) ON DELETE SET NULL
);

CREATE TABLE MAINTENANCE_STAFF (
    Staff_ID       INTEGER PRIMARY KEY AUTOINCREMENT,
    Staff_Name     TEXT NOT NULL,
    Specialization TEXT NOT NULL
        CHECK (Specialization IN ('Electrical','Plumbing','Carpentry','Cleaning','Network')),
    Contact_No     TEXT UNIQUE NOT NULL,
    Is_Available   INTEGER DEFAULT 1
);

CREATE TABLE COMPLAINT (
    Complaint_ID      INTEGER PRIMARY KEY AUTOINCREMENT,
    Roll_No           TEXT NOT NULL,
    Staff_ID          INTEGER,
    Issue_Category    TEXT NOT NULL
        CHECK (Issue_Category IN ('Electrical','Plumbing','Carpentry','Cleaning','Network')),
    Description       TEXT NOT NULL,
    Date_Logged       TEXT DEFAULT (DATE('now')),
    Date_Resolved     TEXT,
    Resolution_Status TEXT DEFAULT 'Pending'
        CHECK (Resolution_Status IN ('Pending','In Progress','Resolved','Reopened')),
    FOREIGN KEY (Roll_No)  REFERENCES STUDENT(Roll_No) ON DELETE CASCADE,
    FOREIGN KEY (Staff_ID) REFERENCES MAINTENANCE_STAFF(Staff_ID) ON DELETE SET NULL
);

CREATE INDEX idx_student_room    ON STUDENT(Room_No, Block);
CREATE INDEX idx_complaint_roll  ON COMPLAINT(Roll_No);
CREATE INDEX idx_complaint_staff ON COMPLAINT(Staff_ID);
CREATE INDEX idx_complaint_status ON COMPLAINT(Resolution_Status);

-- ----------------------------------------------------------
-- TRIGGER 1: Sync room occupancy on student insert/update/delete
-- ----------------------------------------------------------
CREATE TRIGGER trg_student_occupancy_insert
AFTER INSERT ON STUDENT
FOR EACH ROW
WHEN NEW.Room_No IS NOT NULL
BEGIN
    UPDATE ROOM SET Current_Occupancy = Current_Occupancy + 1
     WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
END;

CREATE TRIGGER trg_student_occupancy_update
AFTER UPDATE OF Room_No, Block ON STUDENT
FOR EACH ROW
BEGIN
    UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
     WHERE Room_No = OLD.Room_No AND Block = OLD.Block AND OLD.Room_No IS NOT NULL;
    UPDATE ROOM SET Current_Occupancy = Current_Occupancy + 1
     WHERE Room_No = NEW.Room_No AND Block = NEW.Block AND NEW.Room_No IS NOT NULL;
END;

CREATE TRIGGER trg_student_occupancy_delete
AFTER DELETE ON STUDENT
FOR EACH ROW
WHEN OLD.Room_No IS NOT NULL
BEGIN
    UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
     WHERE Room_No = OLD.Room_No AND Block = OLD.Block;
END;

-- ----------------------------------------------------------
-- TRIGGER 2: Gender-to-block segregation
-- ----------------------------------------------------------
CREATE TRIGGER trg_gender_block_insert
BEFORE INSERT ON STUDENT
FOR EACH ROW
WHEN NEW.Room_No IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Gender policy violation: student gender does not match room policy.')
    WHERE (SELECT Gender_Policy FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block)
          NOT IN ('Coed', NEW.Gender);
END;

CREATE TRIGGER trg_gender_block_update
BEFORE UPDATE OF Room_No, Block ON STUDENT
FOR EACH ROW
WHEN NEW.Room_No IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Gender policy violation: student gender does not match room policy.')
    WHERE (SELECT Gender_Policy FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block)
          NOT IN ('Coed', NEW.Gender);
END;

-- ----------------------------------------------------------
-- TRIGGER 3: Capacity enforcement (no over-allocation)
-- ----------------------------------------------------------
CREATE TRIGGER trg_capacity_enforce_insert
BEFORE INSERT ON STUDENT
FOR EACH ROW
WHEN NEW.Room_No IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Room is full.')
    WHERE (SELECT Current_Occupancy FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block)
          >= (SELECT Capacity FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block);
END;

CREATE TRIGGER trg_capacity_enforce_update
BEFORE UPDATE OF Room_No, Block ON STUDENT
FOR EACH ROW
WHEN NEW.Room_No IS NOT NULL AND
     (OLD.Room_No IS NOT NEW.Room_No OR OLD.Block IS NOT NEW.Block)
BEGIN
    SELECT RAISE(ABORT, 'Room is full.')
    WHERE (SELECT Current_Occupancy FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block)
          >= (SELECT Capacity FROM ROOM WHERE Room_No=NEW.Room_No AND Block=NEW.Block);
END;

-- ----------------------------------------------------------
-- TRIGGER 4: Staff specialization match
-- ----------------------------------------------------------
CREATE TRIGGER trg_staff_spec_insert
BEFORE INSERT ON COMPLAINT
FOR EACH ROW
WHEN NEW.Staff_ID IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Staff specialization does not match complaint category.')
    WHERE (SELECT Specialization FROM MAINTENANCE_STAFF WHERE Staff_ID=NEW.Staff_ID)
          IS NOT NEW.Issue_Category;
END;

CREATE TRIGGER trg_staff_spec_update
BEFORE UPDATE OF Staff_ID, Issue_Category ON COMPLAINT
FOR EACH ROW
WHEN NEW.Staff_ID IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Staff specialization does not match complaint category.')
    WHERE (SELECT Specialization FROM MAINTENANCE_STAFF WHERE Staff_ID=NEW.Staff_ID)
          IS NOT NEW.Issue_Category;
END;

-- ----------------------------------------------------------
-- TRIGGER 5: Audit Date_Resolved
-- ----------------------------------------------------------
CREATE TRIGGER trg_audit_resolution
BEFORE UPDATE OF Resolution_Status ON COMPLAINT
FOR EACH ROW
BEGIN
    UPDATE COMPLAINT SET Date_Resolved =
        CASE WHEN NEW.Resolution_Status = 'Resolved' THEN DATE('now') ELSE NULL END
     WHERE Complaint_ID = NEW.Complaint_ID;
END;
"""

SEED_SQL = """
INSERT INTO ROOM (Room_No, Block, Floor, Capacity, Gender_Policy) VALUES
('101','A',1,2,'Male'),
('102','A',1,2,'Male'),
('201','A',2,3,'Male'),
('101','B',1,2,'Male'),
('101','C',1,2,'Female'),
('102','C',1,2,'Female'),
('201','D',2,3,'Female');

INSERT INTO STUDENT (Roll_No, Name, Gender, Phone, Email, Room_No, Block) VALUES
('AM.EN.U4CSE23001','Aditya Verma', 'Male',  '9876543210','aditya@example.com','101','A'),
('AM.EN.U4CSE23002','Pooja Nair',   'Female','9876543211','pooja@example.com', '101','C'),
('AM.EN.U4CSE23003','Kiran Das',    'Male',  '9876543212','kiran@example.com', '101','A'),
('AM.EN.U4CSE23004','Rahul Menon',  'Male',  '9876543213','rahul@example.com', '102','A'),
('AM.EN.U4CSE23005','Ananya Iyer',  'Female','9876543214','ananya@example.com','102','C');

INSERT INTO MAINTENANCE_STAFF (Staff_Name, Specialization, Contact_No) VALUES
('Ramesh Kumar','Plumbing',  '9811122233'),
('Suresh Babu', 'Electrical','9822233344'),
('Manoj Pillai','Carpentry', '9833344455'),
('Lakshmi Devi','Cleaning',  '9844455566'),
('Vijay Kumar', 'Network',   '9855566677');

INSERT INTO COMPLAINT (Roll_No, Staff_ID, Issue_Category, Description, Date_Logged, Resolution_Status) VALUES
('AM.EN.U4CSE23001',1,'Plumbing',  'Washroom faucet dripping continuously',DATE('now','-4 day'),'In Progress'),
('AM.EN.U4CSE23002',2,'Electrical','Ceiling tube light starter failure',   DATE('now','-1 day'),'Pending'),
('AM.EN.U4CSE23003',1,'Plumbing',  'Shower drain clogged',                 DATE('now','-7 day'),'Resolved'),
('AM.EN.U4CSE23004',3,'Carpentry', 'Study table hinge broken',             DATE('now','-2 day'),'Pending');
"""

# PostgreSQL uses a dedicated schema so the app never creates or drops tables
# in the shared `public` schema (the configured database may be `postgres`).
POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ROOM (
    Room_No VARCHAR(10) NOT NULL,
    Block VARCHAR(10) NOT NULL,
    Floor INT NOT NULL CHECK (Floor >= 0),
    Capacity INT NOT NULL CHECK (Capacity > 0),
    Current_Occupancy INT NOT NULL DEFAULT 0 CHECK (Current_Occupancy >= 0 AND Current_Occupancy <= Capacity),
    Gender_Policy VARCHAR(10) NOT NULL DEFAULT 'Male' CHECK (Gender_Policy IN ('Male','Female','Coed')),
    PRIMARY KEY (Room_No, Block)
);

CREATE TABLE IF NOT EXISTS STUDENT (
    Roll_No VARCHAR(20) PRIMARY KEY,
    Name VARCHAR(60) NOT NULL,
    Gender VARCHAR(10) NOT NULL CHECK (Gender IN ('Male','Female','Other')),
    Phone VARCHAR(15) UNIQUE NOT NULL,
    Email VARCHAR(100) UNIQUE NOT NULL,
    Room_No VARCHAR(10),
    Block VARCHAR(10),
    FOREIGN KEY (Room_No, Block) REFERENCES ROOM(Room_No, Block) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS MAINTENANCE_STAFF (
    Staff_ID SERIAL PRIMARY KEY,
    Staff_Name VARCHAR(60) NOT NULL,
    Specialization VARCHAR(30) NOT NULL CHECK (Specialization IN ('Electrical','Plumbing','Carpentry','Cleaning','Network')),
    Contact_No VARCHAR(15) UNIQUE NOT NULL,
    Is_Available BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS COMPLAINT (
    Complaint_ID SERIAL PRIMARY KEY,
    Roll_No VARCHAR(20) NOT NULL,
    Staff_ID INT,
    Issue_Category VARCHAR(30) NOT NULL CHECK (Issue_Category IN ('Electrical','Plumbing','Carpentry','Cleaning','Network')),
    Description TEXT NOT NULL,
    Date_Logged DATE NOT NULL DEFAULT CURRENT_DATE,
    Date_Resolved DATE,
    Resolution_Status VARCHAR(20) NOT NULL DEFAULT 'Pending' CHECK (Resolution_Status IN ('Pending','In Progress','Resolved','Reopened')),
    FOREIGN KEY (Roll_No) REFERENCES STUDENT(Roll_No) ON DELETE CASCADE,
    FOREIGN KEY (Staff_ID) REFERENCES MAINTENANCE_STAFF(Staff_ID) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_student_room ON STUDENT(Room_No, Block);
CREATE INDEX IF NOT EXISTS idx_complaint_roll ON COMPLAINT(Roll_No);
CREATE INDEX IF NOT EXISTS idx_complaint_staff ON COMPLAINT(Staff_ID);
CREATE INDEX IF NOT EXISTS idx_complaint_status ON COMPLAINT(Resolution_Status);

CREATE OR REPLACE FUNCTION hrmms_sync_room_occupancy_fn()
RETURNS TRIGGER AS $$
DECLARE
    room_capacity INT;
    room_occupancy INT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.Room_No IS NOT NULL THEN
            UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
             WHERE Room_No = OLD.Room_No AND Block = OLD.Block;
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.Room_No IS NOT DISTINCT FROM NEW.Room_No
       AND OLD.Block IS NOT DISTINCT FROM NEW.Block THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.Room_No IS NOT NULL THEN
        UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
         WHERE Room_No = OLD.Room_No AND Block = OLD.Block;
    END IF;

    IF NEW.Room_No IS NOT NULL THEN
        SELECT Capacity, Current_Occupancy INTO room_capacity, room_occupancy
          FROM ROOM WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
        IF room_occupancy >= room_capacity THEN
            RAISE EXCEPTION 'Room %-% is full.', NEW.Block, NEW.Room_No;
        END IF;
        UPDATE ROOM SET Current_Occupancy = Current_Occupancy + 1
         WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION hrmms_gender_policy_fn()
RETURNS TRIGGER AS $$
DECLARE room_policy VARCHAR(10);
BEGIN
    IF NEW.Room_No IS NOT NULL THEN
        SELECT Gender_Policy INTO room_policy FROM ROOM
         WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
        IF room_policy IS NOT NULL AND room_policy NOT IN ('Coed', NEW.Gender) THEN
            RAISE EXCEPTION 'Room gender policy does not match student gender.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION hrmms_staff_specialization_fn()
RETURNS TRIGGER AS $$
DECLARE staff_specialization VARCHAR(30);
BEGIN
    IF NEW.Staff_ID IS NOT NULL THEN
        SELECT Specialization INTO staff_specialization FROM MAINTENANCE_STAFF
         WHERE Staff_ID = NEW.Staff_ID;
        IF staff_specialization IS DISTINCT FROM NEW.Issue_Category THEN
            RAISE EXCEPTION 'Staff specialization does not match complaint category.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION hrmms_audit_resolution_fn()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.Resolution_Status = 'Resolved' THEN
        NEW.Date_Resolved := CURRENT_DATE;
    ELSE
        NEW.Date_Resolved := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_hrmms_occupancy ON STUDENT;
CREATE TRIGGER trg_hrmms_occupancy AFTER INSERT OR UPDATE OR DELETE ON STUDENT
FOR EACH ROW EXECUTE FUNCTION hrmms_sync_room_occupancy_fn();
DROP TRIGGER IF EXISTS trg_hrmms_gender_policy ON STUDENT;
CREATE TRIGGER trg_hrmms_gender_policy BEFORE INSERT OR UPDATE OF Room_No, Block ON STUDENT
FOR EACH ROW EXECUTE FUNCTION hrmms_gender_policy_fn();
DROP TRIGGER IF EXISTS trg_hrmms_staff_specialization ON COMPLAINT;
CREATE TRIGGER trg_hrmms_staff_specialization BEFORE INSERT OR UPDATE OF Staff_ID, Issue_Category ON COMPLAINT
FOR EACH ROW EXECUTE FUNCTION hrmms_staff_specialization_fn();
DROP TRIGGER IF EXISTS trg_hrmms_audit_resolution ON COMPLAINT;
CREATE TRIGGER trg_hrmms_audit_resolution BEFORE UPDATE OF Resolution_Status ON COMPLAINT
FOR EACH ROW EXECUTE FUNCTION hrmms_audit_resolution_fn();

INSERT INTO ROOM (Room_No, Block, Floor, Capacity, Gender_Policy) VALUES
('101','A',1,2,'Male'),('102','A',1,2,'Male'),('201','A',2,3,'Male'),
('101','B',1,2,'Male'),('101','C',1,2,'Female'),('102','C',1,2,'Female'),('201','D',2,3,'Female')
ON CONFLICT (Room_No, Block) DO NOTHING;

INSERT INTO STUDENT (Roll_No, Name, Gender, Phone, Email, Room_No, Block) VALUES
('AM.EN.U4CSE23001','Aditya Verma','Male','9876543210','aditya@example.com','101','A'),
('AM.EN.U4CSE23002','Pooja Nair','Female','9876543211','pooja@example.com','101','C'),
('AM.EN.U4CSE23003','Kiran Das','Male','9876543212','kiran@example.com','101','A'),
('AM.EN.U4CSE23004','Rahul Menon','Male','9876543213','rahul@example.com','102','A'),
('AM.EN.U4CSE23005','Ananya Iyer','Female','9876543214','ananya@example.com','102','C')
ON CONFLICT (Roll_No) DO NOTHING;

INSERT INTO MAINTENANCE_STAFF (Staff_Name, Specialization, Contact_No) VALUES
('Ramesh Kumar','Plumbing','9811122233'),('Suresh Babu','Electrical','9822233344'),
('Manoj Pillai','Carpentry','9833344455'),('Lakshmi Devi','Cleaning','9844455566'),
('Vijay Kumar','Network','9855566677')
ON CONFLICT (Contact_No) DO NOTHING;

INSERT INTO COMPLAINT (Complaint_ID, Roll_No, Staff_ID, Issue_Category, Description, Date_Logged, Resolution_Status) VALUES
(1,'AM.EN.U4CSE23001',1,'Plumbing','Washroom faucet dripping continuously',CURRENT_DATE - 4,'In Progress'),
(2,'AM.EN.U4CSE23002',2,'Electrical','Ceiling tube light starter failure',CURRENT_DATE - 1,'Pending'),
(3,'AM.EN.U4CSE23003',1,'Plumbing','Shower drain clogged',CURRENT_DATE - 7,'Resolved'),
(4,'AM.EN.U4CSE23004',3,'Carpentry','Study table hinge broken',CURRENT_DATE - 2,'Pending')
ON CONFLICT (Complaint_ID) DO NOTHING;

SELECT setval(pg_get_serial_sequence('MAINTENANCE_STAFF','staff_id'),
              GREATEST(COALESCE((SELECT MAX(Staff_ID) FROM MAINTENANCE_STAFF), 1), 1), TRUE);
SELECT setval(pg_get_serial_sequence('COMPLAINT','complaint_id'),
              GREATEST(COALESCE((SELECT MAX(Complaint_ID) FROM COMPLAINT), 1), 1), TRUE);
"""


class PostgresRow(dict):
    """Expose PostgreSQL's lowercase identifiers using the app's SQLite-style keys."""

    def __getitem__(self, key: str) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        folded = key.casefold()
        for name, value in self.items():
            if name.casefold() == folded:
                return value
        raise KeyError(key)


def _postgres_row(row: dict[str, Any] | None) -> PostgresRow | None:
    if row is None:
        return None
    values = {}
    for key, value in row.items():
        display_key = "ID" if key.casefold() == "id" else "_".join(part.capitalize() for part in key.split("_"))
        values[display_key] = value
    return PostgresRow(values)


class HostelDB:
    """Stateful database wrapper with execution log."""

    def __init__(self, db_file: str = DB_FILE, reset: bool = False):
        self.db_file = db_file
        self.backend = DB_BACKEND
        if self.backend not in {"sqlite", "postgres"}:
            raise ValueError("HRMMS_DB_BACKEND must be either 'sqlite' or 'postgres'.")
        if self.backend == "sqlite" and reset and os.path.exists(db_file):
            os.remove(db_file)
        self._log: list[dict[str, Any]] = []
        self._init_schema()

    # ---- low-level connection helpers ----
    def _connect(self):
        if self.backend == "postgres":
            conn = psycopg.connect(
                host=os.getenv("HRMMS_DB_HOST", "localhost"),
                port=int(os.getenv("HRMMS_DB_PORT", "5432")),
                dbname=os.getenv("HRMMS_DB_NAME", "postgres"),
                user=os.getenv("HRMMS_DB_USER", "postgres"),
                password=os.getenv("HRMMS_DB_PASSWORD") or None,
                connect_timeout=5,
                row_factory=dict_row,
            )
            conn.execute("SET search_path TO hrmms, public")
            return conn

        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            if self.backend == "postgres":
                # Use a dedicated schema; never run the destructive demo DDL in schema.sql.
                cur.execute("CREATE SCHEMA IF NOT EXISTS hrmms")
                cur.execute("SET search_path TO hrmms, public")
                cur.execute(POSTGRES_SCHEMA_SQL, prepare=False)
                conn.commit()
                return

            # check if schema already exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ROOM'")
            if not cur.fetchone():
                cur.executescript(SCHEMA_SQL)
                cur.executescript(SEED_SQL)
                conn.commit()
        finally:
            conn.close()

    # ---- execution log ----
    def log(self, sql: str, ok: bool, rows_affected: int = 0,
            error: str | None = None) -> None:
        self._log.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sql": sql.strip()[:300],
            "status": "OK" if ok else "ERROR",
            "rows": rows_affected,
            "error": error or "",
        })
        # keep the log bounded
        if len(self._log) > 500:
            self._log = self._log[-500:]

    def get_log(self) -> list[dict[str, Any]]:
        return list(self._log)

    # ---- generic SQL console (supports SELECT / INSERT / UPDATE / DELETE) ----
    def run_query(self, sql: str) -> tuple[list[str], list[tuple], int, str | None]:
        """
        Execute a single SQL statement.

        Returns (columns, rows, rows_affected, error).
        For SELECT: columns + rows populated, rows_affected = len(rows).
        For DML: columns = [], rows = [], rows_affected = count, error maybe set.
        """
        sql = sql.strip().rstrip(";")
        if not sql:
            return [], [], 0, "Empty query"
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql)
            first_word = sql.split(None, 1)[0].upper()
            if first_word == "SELECT":
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
                data = [tuple(r.values()) for r in rows] if self.backend == "postgres" else [tuple(r) for r in rows]
                self.log(sql, True, rows_affected=len(data))
                conn.commit()
                return cols, data, len(data), None
            else:
                conn.commit()
                affected = cur.rowcount
                self.log(sql, True, rows_affected=affected)
                return [], [], affected, None
        except DB_ERRORS as e:
            conn.rollback()
            err = str(e)
            self.log(sql, False, error=err)
            return [], [], 0, err
        finally:
            conn.close()

    # ---- typed helper accessors used by the Streamlit UI ----
    @staticmethod
    def _parameter_sql(sql: str) -> str:
        return sql.replace("?", "%s")

    def fetch_all(self, sql: str, params: tuple = ()) -> list[Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(self._parameter_sql(sql) if self.backend == "postgres" else sql, params)
            rows = cur.fetchall()
            return [_postgres_row(row) for row in rows] if self.backend == "postgres" else rows
        finally:
            conn.close()

    def fetch_one(self, sql: str, params: tuple = ()) -> Any:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(self._parameter_sql(sql) if self.backend == "postgres" else sql, params)
            row = cur.fetchone()
            return _postgres_row(row) if self.backend == "postgres" else row
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(self._parameter_sql(sql) if self.backend == "postgres" else sql, params)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    # ---- KPI metrics ----
    def metrics(self) -> dict[str, int | float]:
        total_rooms = self.fetch_one("SELECT COUNT(*) c FROM ROOM")["c"]
        total_beds = self.fetch_one("SELECT COALESCE(SUM(Capacity),0) s FROM ROOM")["s"]
        occupied = self.fetch_one("SELECT COALESCE(SUM(Current_Occupancy),0) s FROM ROOM")["s"]
        students = self.fetch_one("SELECT COUNT(*) c FROM STUDENT")["c"]
        staff = self.fetch_one("SELECT COUNT(*) c FROM MAINTENANCE_STAFF")["c"]
        avail_staff = self.fetch_one(
            "SELECT COUNT(*) c FROM MAINTENANCE_STAFF WHERE Is_Available=TRUE")["c"]
        complaints = self.fetch_one("SELECT COUNT(*) c FROM COMPLAINT")["c"]
        pending = self.fetch_one(
            "SELECT COUNT(*) c FROM COMPLAINT WHERE Resolution_Status='Pending'")["c"]
        in_progress = self.fetch_one(
            "SELECT COUNT(*) c FROM COMPLAINT WHERE Resolution_Status='In Progress'")["c"]
        resolved = self.fetch_one(
            "SELECT COUNT(*) c FROM COMPLAINT WHERE Resolution_Status='Resolved'")["c"]
        occupancy_pct = round(100.0 * occupied / total_beds, 1) if total_beds else 0.0
        return {
            "total_rooms": total_rooms,
            "total_beds": total_beds,
            "occupied": occupied,
            "available_beds": total_beds - occupied,
            "occupancy_pct": occupancy_pct,
            "students": students,
            "staff": staff,
            "available_staff": avail_staff,
            "complaints": complaints,
            "pending": pending,
            "in_progress": in_progress,
            "resolved": resolved,
        }


# module-level singleton used by the Streamlit app
_db: HostelDB | None = None


def get_db(reset: bool = False) -> HostelDB:
    global _db
    if _db is None or reset:
        _db = HostelDB(reset=reset)
    return _db


if __name__ == "__main__":
    # quick self-test: confirm trigger behaviour
    db = get_db(reset=True)
    cols, rows, _, err = db.run_query("SELECT Block, Room_No, Current_Occupancy, Capacity FROM ROOM ORDER BY Block, Room_No")
    print("Rooms after seed:")
    print(cols)
    for r in rows:
        print(r)
    print()
    print("Log (last 5):")
    for entry in db.get_log()[-5:]:
        print(entry)
