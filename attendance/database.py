"""
database.py - GROUP 1: the memory of the system.

Four tables:

    students      who exists                      (student_id, name, grade)
    classes       every class, by subject         (class_id, subject, name)
    enrollments   which student is in which class (student_id, class_id)
    check_ins     who showed up, when             (student_id, class_id, date,
                                                   scanned_at, status)

The same code talks to two kinds of database:
  - On Vercel: an online Postgres database. Vercel gives the site its address
    in the DATABASE_URL setting when you connect the database.
  - On your own computer: the file attendance.db (SQLite), like before.

The SQL is written once with ? placeholders. For Postgres, run() swaps each ?
for %s, which is the placeholder Postgres uses.
"""

import os
import sqlite3
from contextlib import contextmanager

from attendance import config

DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
ON_VERCEL = bool(os.environ.get("VERCEL"))

if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row
    CONNECTION_ERRORS = (psycopg.OperationalError,)
else:
    CONNECTION_ERRORS = (sqlite3.OperationalError,)


class SetupNeeded(Exception):
    """The site is running on Vercel but no database is connected yet."""


NO_DATABASE_MESSAGE = (
    "The database isn't connected yet. In your Vercel project, open the Storage tab, "
    "create a Postgres database (Neon), connect it to this project, then redeploy."
)


def _connect():
    if USE_POSTGRES:
        # prepare_threshold=None: Vercel's database sits behind a connection
        # pooler that can't keep prepared statements, so don't make any.
        return psycopg.connect(DATABASE_URL, row_factory=dict_row,
                               connect_timeout=10, prepare_threshold=None)
    if ON_VERCEL:
        # Vercel's disk is wiped all the time, so a file database would lose
        # everything. Refuse instead of pretending to save.
        raise SetupNeeded(NO_DATABASE_MESSAGE)
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row          # read columns by name: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite leaves these off by default
    return conn


class _Runner:
    """Wraps one connection so the rest of the file writes SQL only once."""

    def __init__(self, conn):
        self.conn = conn

    def run(self, sql, params=()):
        if USE_POSTGRES:
            sql = sql.replace("?", "%s")
        return self.conn.execute(sql, params)

    def one(self, sql, params=()):
        return self.run(sql, params).fetchone()

    def all(self, sql, params=()):
        return self.run(sql, params).fetchall()


@contextmanager
def transaction():
    """Open the database, do some work, save it all (or none of it), close.

        with transaction() as db:
            db.run("INSERT ...", (...))
    """
    conn = _connect()
    try:
        yield _Runner(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------ tables

TABLES = [
    # student_id is TEXT: "STU-014" has letters. It holds no personal
    # information, so it is safe to print inside a QR code.
    """CREATE TABLE IF NOT EXISTS students (
        student_id  TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        grade       INTEGER
    )""",
    # One row per class. class_id looks like "gurmat-level-3a".
    """CREATE TABLE IF NOT EXISTS classes (
        class_id    TEXT PRIMARY KEY,
        subject     TEXT NOT NULL,
        name        TEXT NOT NULL,
        sort_order  INTEGER NOT NULL
    )""",
    # Which student is in which class: one row per subject they take.
    # ON DELETE CASCADE: removing a student removes their rows here too.
    """CREATE TABLE IF NOT EXISTS enrollments (
        student_id  TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
        class_id    TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
        PRIMARY KEY (student_id, class_id)
    )""",
    # The primary key (student, class, date) means one check-in per student,
    # per class, per day: the database itself refuses a second scan.
    """CREATE TABLE IF NOT EXISTS check_ins (
        student_id  TEXT NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
        class_id    TEXT NOT NULL REFERENCES classes(class_id) ON DELETE CASCADE,
        date        TEXT NOT NULL,
        scanned_at  TEXT NOT NULL,
        status      TEXT NOT NULL,
        PRIMARY KEY (student_id, class_id, date)
    )""",
    # A different late time for one subject on one day (a late start, an
    # assembly...). Days with no row here use the usual time from config.py.
    """CREATE TABLE IF NOT EXISTS late_time_changes (
        date        TEXT NOT NULL,
        subject     TEXT NOT NULL,
        late_after  TEXT NOT NULL,
        PRIMARY KEY (date, subject)
    )""",
]

_ready = False


def setup():
    """Create the tables and fill in the classes. Runs once per server start."""
    global _ready
    if _ready:
        return
    with transaction() as db:
        if USE_POSTGRES:
            # Several copies of the site can start at the same moment on
            # Vercel. This lock makes them take turns creating the tables.
            db.run("SELECT pg_advisory_xact_lock(724101)")
        for ddl in TABLES:
            db.run(ddl)
        for c in config.CLASSES:
            db.run("""
                INSERT INTO classes (class_id, subject, name, sort_order) VALUES (?, ?, ?, ?)
                ON CONFLICT (class_id) DO UPDATE SET
                    subject = excluded.subject, name = excluded.name, sort_order = excluded.sort_order
            """, (c["class_id"], c["subject"], c["name"], c["sort_order"]))
    _ready = True


# ---------------------------------------------------------------- students

def _student_dicts(db, where="", params=()):
    """Students with their classes: {student_id, name, grade, classes: {gurmat: id, ...}}"""
    rows = db.all("SELECT student_id, name, grade FROM students " + where +
                  " ORDER BY student_id", params)
    students = {}
    for r in rows:
        students[r["student_id"]] = {
            "student_id": r["student_id"], "name": r["name"], "grade": r["grade"],
            "classes": {s["key"]: None for s in config.SUBJECTS},
        }
    if students:
        for e in db.all("""
            SELECT enrollments.student_id, classes.class_id, classes.subject
            FROM enrollments JOIN classes ON classes.class_id = enrollments.class_id
        """):
            if e["student_id"] in students and e["subject"] in config.SUBJECT_BY_KEY:
                students[e["student_id"]]["classes"][e["subject"]] = e["class_id"]
    return list(students.values())


def list_students():
    with transaction() as db:
        return _student_dicts(db)


def get_student(student_id):
    """One student with their classes, or None."""
    with transaction() as db:
        found = _student_dicts(db, "WHERE student_id = ?", (student_id,))
    return found[0] if found else None


def _save_student(db, student_id, name, grade, class_ids):
    db.run("""
        INSERT INTO students (student_id, name, grade) VALUES (?, ?, ?)
        ON CONFLICT (student_id) DO UPDATE SET name = excluded.name, grade = excluded.grade
    """, (student_id, name, grade))
    db.run("DELETE FROM enrollments WHERE student_id = ?", (student_id,))
    for class_id in class_ids:
        if class_id:
            db.run("INSERT INTO enrollments (student_id, class_id) VALUES (?, ?)",
                   (student_id, class_id))


def save_student(student_id, name, grade, class_ids, must_be_new=False):
    """Add or update a student. Returns False if must_be_new and the code is taken."""
    with transaction() as db:
        if must_be_new and db.one("SELECT 1 AS taken FROM students WHERE student_id = ?",
                                  (student_id,)):
            return False
        _save_student(db, student_id, name, grade, class_ids)
    return True


def delete_student(student_id):
    """Remove a student, their classes and their check-ins. True if they existed."""
    with transaction() as db:
        return db.run("DELETE FROM students WHERE student_id = ?", (student_id,)).rowcount > 0


def load_sample_students():
    """Add (or reset) the fake students in config.py."""
    with transaction() as db:
        for code, name, grade, gurmat, gurmukhi, elective in config.SAMPLE_STUDENTS:
            _save_student(db, code, name, grade, [
                config.class_id("gurmat", gurmat),
                config.class_id("gurmukhi", gurmukhi),
                config.class_id("elective", elective),
            ])
    return len(config.SAMPLE_STUDENTS)


# --------------------------------------------------------------- check-ins

def add_check_in(student_id, class_id, date, scanned_at, status):
    """Record one scan.

    Returns (True, None) when saved, or (False, first_scan_row) when this
    student was already checked in to this class on this date.
    """
    with transaction() as db:
        saved = db.run("""
            INSERT INTO check_ins (student_id, class_id, date, scanned_at, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (student_id, class_id, date) DO NOTHING
        """, (student_id, class_id, date, scanned_at, status)).rowcount == 1
        if saved:
            return True, None
        first = db.one("""
            SELECT scanned_at, status FROM check_ins
            WHERE student_id = ? AND class_id = ? AND date = ?
        """, (student_id, class_id, date))
        return False, first


def class_attendance(class_id, date):
    """Who is in one class on one date: (present rows, missing rows)."""
    with transaction() as db:
        present = db.all("""
            SELECT check_ins.student_id, students.name, check_ins.scanned_at, check_ins.status
            FROM check_ins JOIN students ON students.student_id = check_ins.student_id
            WHERE check_ins.class_id = ? AND check_ins.date = ?
            ORDER BY check_ins.scanned_at, students.name
        """, (class_id, date))
        missing = db.all("""
            SELECT students.student_id, students.name
            FROM enrollments JOIN students ON students.student_id = enrollments.student_id
            WHERE enrollments.class_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM check_ins
                  WHERE check_ins.student_id = enrollments.student_id
                    AND check_ins.class_id = enrollments.class_id
                    AND check_ins.date = ?)
            ORDER BY students.name
        """, (class_id, date))
    return present, missing


def summary(date):
    """Every class at a glance, plus how many students came to anything."""
    with transaction() as db:
        rows = db.all("""
            SELECT classes.class_id, classes.subject, classes.name,
              (SELECT COUNT(*) FROM enrollments e
                WHERE e.class_id = classes.class_id) AS total,
              (SELECT COUNT(*) FROM check_ins c
                WHERE c.class_id = classes.class_id AND c.date = ? AND c.status = 'present') AS here,
              (SELECT COUNT(*) FROM check_ins c
                WHERE c.class_id = classes.class_id AND c.date = ? AND c.status = 'late') AS late,
              (SELECT COUNT(*) FROM enrollments e
                WHERE e.class_id = classes.class_id
                  AND NOT EXISTS (SELECT 1 FROM check_ins c
                                   WHERE c.student_id = e.student_id
                                     AND c.class_id = e.class_id AND c.date = ?)) AS missing
            FROM classes
            ORDER BY classes.sort_order
        """, (date, date, date))
        came = db.one("SELECT COUNT(DISTINCT student_id) AS n FROM check_ins WHERE date = ?",
                      (date,))["n"]
        total = db.one("SELECT COUNT(*) AS n FROM students")["n"]
    return rows, int(came), int(total)


# -------------------------------------------------------------- late times

def late_times(date):
    """{subject: (late_after, changed)} for one date."""
    with transaction() as db:
        changed = {r["subject"]: r["late_after"] for r in db.all(
            "SELECT subject, late_after FROM late_time_changes WHERE date = ?", (date,))}
    return {s["key"]: (changed.get(s["key"], s["late_after"]), s["key"] in changed)
            for s in config.SUBJECTS}


def all_late_time_changes():
    """Every changed day, newest first: [(date, {subject: late_after})]."""
    with transaction() as db:
        rows = db.all("SELECT date, subject, late_after FROM late_time_changes ORDER BY date DESC")
    days = {}
    for r in rows:
        days.setdefault(r["date"], {})[r["subject"]] = r["late_after"]
    return list(days.items())


def set_late_times(date, times):
    """Save one day's late times ({subject: "HH:MM"}). A time equal to the
    usual one is stored as "no change". Check-ins already made that day are
    marked late or on time again using the new times."""
    with transaction() as db:
        for s in config.SUBJECTS:
            new_time = times.get(s["key"]) or s["late_after"]
            if new_time == s["late_after"]:
                db.run("DELETE FROM late_time_changes WHERE date = ? AND subject = ?",
                       (date, s["key"]))
            else:
                db.run("""
                    INSERT INTO late_time_changes (date, subject, late_after) VALUES (?, ?, ?)
                    ON CONFLICT (date, subject) DO UPDATE SET late_after = excluded.late_after
                """, (date, s["key"], new_time))
            # "HH:MM" text compares correctly: "10:21" > "10:20".
            db.run("""
                UPDATE check_ins
                SET status = CASE WHEN scanned_at > ? THEN 'late' ELSE 'present' END
                WHERE date = ?
                  AND class_id IN (SELECT class_id FROM classes WHERE subject = ?)
            """, (new_time, date, s["key"]))


def student_check_ins(student_id, days=10):
    """This student's check-ins on their most recent `days` dates, newest first."""
    with transaction() as db:
        return db.all("""
            SELECT check_ins.date, check_ins.class_id, classes.subject, classes.name,
                   check_ins.scanned_at, check_ins.status
            FROM check_ins JOIN classes ON classes.class_id = check_ins.class_id
            WHERE check_ins.student_id = ?
              AND check_ins.date IN (
                  SELECT DISTINCT date FROM check_ins WHERE student_id = ?
                  ORDER BY date DESC LIMIT ?)
            ORDER BY check_ins.date DESC
        """, (student_id, student_id, days))
