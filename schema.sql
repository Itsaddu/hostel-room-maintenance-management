-- ============================================================
--  Hostel Room & Maintenance Management System (HRMMS)
--  PostgreSQL Schema: DDL, Constraints, Triggers, Seed Data,
--  and Analytical Queries (Amrita DBMS Submission)
-- ============================================================

-- ==========================================================
-- 1. DDL : TABLE CREATION
-- ==========================================================

DROP TABLE IF EXISTS COMPLAINT CASCADE;
DROP TABLE IF EXISTS MAINTENANCE_STAFF CASCADE;
DROP TABLE IF EXISTS STUDENT CASCADE;
DROP TABLE IF EXISTS ROOM CASCADE;

-- ROOM TABLE
CREATE TABLE ROOM (
    Room_No           VARCHAR(10) NOT NULL,
    Block             VARCHAR(10) NOT NULL,
    Floor             INT NOT NULL CHECK (Floor >= 0),
    Capacity          INT NOT NULL CHECK (Capacity > 0),
    Current_Occupancy INT DEFAULT 0,
    Gender_Policy     VARCHAR(10) NOT NULL DEFAULT 'Male'
        CHECK (Gender_Policy IN ('Male', 'Female', 'Coed')),
    CONSTRAINT PK_Room PRIMARY KEY (Room_No, Block),
    CONSTRAINT CHK_Occupancy
        CHECK (Current_Occupancy <= Capacity AND Current_Occupancy >= 0)
);

-- STUDENT TABLE
CREATE TABLE STUDENT (
    Roll_No  VARCHAR(20) PRIMARY KEY,
    Name     VARCHAR(60)  NOT NULL,
    Gender   VARCHAR(10)  NOT NULL CHECK (Gender IN ('Male', 'Female', 'Other')),
    Phone    VARCHAR(15)  UNIQUE NOT NULL,
    Email    VARCHAR(100) UNIQUE NOT NULL,
    Room_No  VARCHAR(10),
    Block    VARCHAR(10),
    CONSTRAINT FK_Student_Room FOREIGN KEY (Room_No, Block)
        REFERENCES ROOM(Room_No, Block) ON DELETE SET NULL
);

-- MAINTENANCE STAFF TABLE
CREATE TABLE MAINTENANCE_STAFF (
    Staff_ID        SERIAL PRIMARY KEY,
    Staff_Name      VARCHAR(60) NOT NULL,
    Specialization  VARCHAR(30) NOT NULL
        CHECK (Specialization IN ('Electrical', 'Plumbing', 'Carpentry', 'Cleaning', 'Network')),
    Contact_No      VARCHAR(15) UNIQUE NOT NULL,
    Is_Available    BOOLEAN DEFAULT TRUE
);

-- COMPLAINT TABLE
CREATE TABLE COMPLAINT (
    Complaint_ID      SERIAL PRIMARY KEY,
    Roll_No           VARCHAR(20) NOT NULL,
    Staff_ID          INT,
    Issue_Category    VARCHAR(30) NOT NULL
        CHECK (Issue_Category IN ('Electrical', 'Plumbing', 'Carpentry', 'Cleaning', 'Network')),
    Description       TEXT NOT NULL,
    Date_Logged       DATE DEFAULT CURRENT_DATE,
    Date_Resolved     DATE,
    Resolution_Status VARCHAR(20) DEFAULT 'Pending'
        CHECK (Resolution_Status IN ('Pending', 'In Progress', 'Resolved', 'Reopened')),
    CONSTRAINT FK_Complaint_Student FOREIGN KEY (Roll_No)
        REFERENCES STUDENT(Roll_No) ON DELETE CASCADE,
    CONSTRAINT FK_Complaint_Staff FOREIGN KEY (Staff_ID)
        REFERENCES MAINTENANCE_STAFF(Staff_ID) ON DELETE SET NULL
);

-- Indexes for query performance
CREATE INDEX idx_student_room   ON STUDENT(Room_No, Block);
CREATE INDEX idx_complaint_roll ON COMPLAINT(Roll_No);
CREATE INDEX idx_complaint_staff ON COMPLAINT(Staff_ID);
CREATE INDEX idx_complaint_status ON COMPLAINT(Resolution_Status);

-- ==========================================================
-- 2. TRIGGER : AUTO-UPDATE ROOM OCCUPANCY
--    Increments on INSERT/room-change, decrements on
--    old-room vacate / DELETE. Enforces capacity.
-- ==========================================================

CREATE OR REPLACE FUNCTION update_room_occupancy_fn()
RETURNS TRIGGER AS $$
DECLARE
    v_capacity INT;
    v_current  INT;
BEGIN
    IF (TG_OP = 'INSERT' AND NEW.Room_No IS NOT NULL) THEN
        SELECT Capacity, Current_Occupancy INTO v_capacity, v_current
          FROM ROOM WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
        IF v_current + 1 > v_capacity THEN
            RAISE EXCEPTION 'Room %-% is full (capacity %).', NEW.Block, NEW.Room_No, v_capacity;
        END IF;
        UPDATE ROOM SET Current_Occupancy = Current_Occupancy + 1
         WHERE Room_No = NEW.Room_No AND Block = NEW.Block;

    ELSIF (TG_OP = 'UPDATE') THEN
        IF (OLD.Room_No IS DISTINCT FROM NEW.Room_No OR OLD.Block IS DISTINCT FROM NEW.Block) THEN
            IF OLD.Room_No IS NOT NULL THEN
                UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
                 WHERE Room_No = OLD.Room_No AND Block = OLD.Block;
            END IF;
            IF NEW.Room_No IS NOT NULL THEN
                SELECT Capacity, Current_Occupancy INTO v_capacity, v_current
                  FROM ROOM WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
                IF v_current + 1 > v_capacity THEN
                    RAISE EXCEPTION 'Room %-% is full (capacity %).', NEW.Block, NEW.Room_No, v_capacity;
                END IF;
                UPDATE ROOM SET Current_Occupancy = Current_Occupancy + 1
                 WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
            END IF;
        END IF;

    ELSIF (TG_OP = 'DELETE' AND OLD.Room_No IS NOT NULL) THEN
        UPDATE ROOM SET Current_Occupancy = Current_Occupancy - 1
         WHERE Room_No = OLD.Room_No AND Block = OLD.Block;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_sync_room_occupancy
AFTER INSERT OR UPDATE OR DELETE ON STUDENT
FOR EACH ROW EXECUTE FUNCTION update_room_occupancy_fn();

-- ==========================================================
-- 3. TRIGGER : AUDIT DATE_RESOLVED
--    Stamps Date_Resolved when status becomes 'Resolved',
--    clears it when reopened.
-- ==========================================================

CREATE OR REPLACE FUNCTION audit_resolution_fn()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.Resolution_Status = 'Resolved' THEN
        NEW.Date_Resolved := CURRENT_DATE;
    ELSIF NEW.Resolution_Status IN ('Pending', 'In Progress', 'Reopened') THEN
        NEW.Date_Resolved := NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_resolution
BEFORE UPDATE OF Resolution_Status ON COMPLAINT
FOR EACH ROW EXECUTE FUNCTION audit_resolution_fn();

-- ==========================================================
-- 4. TRIGGER : STAFF SPECIALIZATION MATCH
--    A complaint can only be assigned to a staff member whose
--    Specialization equals the complaint's Issue_Category.
-- ==========================================================

CREATE OR REPLACE FUNCTION enforce_staff_specialization_fn()
RETURNS TRIGGER AS $$
DECLARE
    v_spec VARCHAR(30);
BEGIN
    IF NEW.Staff_ID IS NOT NULL THEN
        SELECT Specialization INTO v_spec FROM MAINTENANCE_STAFF WHERE Staff_ID = NEW.Staff_ID;
        IF v_spec IS DISTINCT FROM NEW.Issue_Category THEN
            RAISE EXCEPTION 'Staff % is specialized in % but complaint is %%.',
                  NEW.Staff_ID, v_spec, NEW.Issue_Category;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_staff_specialization
BEFORE INSERT OR UPDATE OF Staff_ID, Issue_Category ON COMPLAINT
FOR EACH ROW EXECUTE FUNCTION enforce_staff_specialization_fn();

-- ==========================================================
-- 5. TRIGGER : GENDER-TO-BLOCK SEGREGATION
--    A student may only be allocated to a room whose
--    Gender_Policy matches their gender (Coed allows both).
-- ==========================================================

CREATE OR REPLACE FUNCTION enforce_gender_block_fn()
RETURNS TRIGGER AS $$
DECLARE
    v_policy VARCHAR(10);
BEGIN
    IF NEW.Room_No IS NOT NULL THEN
        SELECT Gender_Policy INTO v_policy
          FROM ROOM WHERE Room_No = NEW.Room_No AND Block = NEW.Block;
        IF v_policy <> 'Coed' AND v_policy <> NEW.Gender THEN
            RAISE EXCEPTION 'Block % is restricted to % students; cannot allocate % student.',
                  NEW.Block, v_policy, NEW.Gender;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_gender_block
BEFORE INSERT OR UPDATE OF Room_No, Block ON STUDENT
FOR EACH ROW EXECUTE FUNCTION enforce_gender_block_fn();

-- ==========================================================
-- 6. SEED DATA
-- ==========================================================

INSERT INTO ROOM (Room_No, Block, Floor, Capacity, Gender_Policy) VALUES
('101', 'A', 1, 2, 'Male'),
('102', 'A', 1, 2, 'Male'),
('201', 'A', 2, 3, 'Male'),
('101', 'B', 1, 2, 'Male'),
('101', 'C', 1, 2, 'Female'),
('102', 'C', 1, 2, 'Female'),
('201', 'D', 2, 3, 'Female');

-- Trigger auto-sets Current_Occupancy on student inserts
INSERT INTO STUDENT (Roll_No, Name, Gender, Phone, Email, Room_No, Block) VALUES
('AM.EN.U4CSE23001', 'Aditya Verma',  'Male',   '9876543210', 'aditya@example.com', '101', 'A'),
('AM.EN.U4CSE23002', 'Pooja Nair',    'Female', '9876543211', 'pooja@example.com',  '101', 'C'),
('AM.EN.U4CSE23003', 'Kiran Das',     'Male',   '9876543212', 'kiran@example.com',  '101', 'A'),
('AM.EN.U4CSE23004', 'Rahul Menon',   'Male',   '9876543213', 'rahul@example.com',  '102', 'A'),
('AM.EN.U4CSE23005', 'Ananya Iyer',   'Female', '9876543214', 'ananya@example.com', '102', 'C');

INSERT INTO MAINTENANCE_STAFF (Staff_Name, Specialization, Contact_No) VALUES
('Ramesh Kumar', 'Plumbing',   '9811122233'),
('Suresh Babu',  'Electrical', '9822233344'),
('Manoj Pillai', 'Carpentry',  '9833344455'),
('Lakshmi Devi', 'Cleaning',   '9844455566'),
('Vijay Kumar',  'Network',    '9855566677');

INSERT INTO COMPLAINT (Roll_No, Staff_ID, Issue_Category, Description, Date_Logged, Resolution_Status) VALUES
('AM.EN.U4CSE23001', 1, 'Plumbing',   'Washroom faucet dripping continuously', CURRENT_DATE - 4, 'In Progress'),
('AM.EN.U4CSE23002', 2, 'Electrical', 'Ceiling tube light starter failure',    CURRENT_DATE - 1, 'Pending'),
('AM.EN.U4CSE23003', 1, 'Plumbing',   'Shower drain clogged',                  CURRENT_DATE - 7, 'Resolved'),
('AM.EN.U4CSE23004', 3, 'Carpentry',  'Study table hinge broken',              CURRENT_DATE - 2, 'Pending');

-- ==========================================================
-- 7. ANALYTICAL SQL QUERIES (Chapter 6)
-- ==========================================================

-- Q1. Vacancy Detection : available beds per room
SELECT Block, Room_No, Floor, Capacity, Current_Occupancy,
       (Capacity - Current_Occupancy) AS Available_Beds
FROM ROOM
WHERE Current_Occupancy < Capacity
ORDER BY Block, Floor, Room_No;

-- Q2. Staff Workload Metric
SELECT s.Staff_ID, s.Staff_Name, s.Specialization, s.Is_Available,
       COUNT(c.Complaint_ID) AS Total_Assigned,
       COUNT(CASE WHEN c.Resolution_Status <> 'Resolved' THEN 1 END) AS Active_Tasks
FROM MAINTENANCE_STAFF s
LEFT JOIN COMPLAINT c ON s.Staff_ID = c.Staff_ID
GROUP BY s.Staff_ID, s.Staff_Name, s.Specialization, s.Is_Available
ORDER BY Active_Tasks DESC;

-- Q3. Room-wise Complaint Frequency
SELECT st.Block, st.Room_No, COUNT(c.Complaint_ID) AS Total_Complaints
FROM COMPLAINT c
JOIN STUDENT st ON c.Roll_No = st.Roll_No
GROUP BY st.Block, st.Room_No
HAVING COUNT(c.Complaint_ID) >= 1
ORDER BY Total_Complaints DESC;

-- Q4. Pending complaints older than 3 days (aging report)
SELECT Complaint_ID, Roll_No, Issue_Category, Date_Logged,
       (CURRENT_DATE - Date_Logged) AS Days_Open
FROM COMPLAINT
WHERE Resolution_Status <> 'Resolved'
ORDER BY Days_Open DESC;

-- Q5. Occupancy rate per block
SELECT Block,
       SUM(Capacity) AS Total_Beds,
       SUM(Current_Occupancy) AS Occupied,
       ROUND(100.0 * SUM(Current_Occupancy) / NULLIF(SUM(Capacity), 0), 2) AS Occupancy_Pct
FROM ROOM
GROUP BY Block
ORDER BY Block;
