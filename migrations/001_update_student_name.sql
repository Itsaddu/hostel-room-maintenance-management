-- Repeatable migration requested for the seeded student record.
UPDATE STUDENT
SET Name = 'Adwaith',
    Email = 'adwaithjs2003@gmail.com'
WHERE Roll_No = 'AM.EN.U4CSE23001';
