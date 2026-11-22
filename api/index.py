"""
api/index.py - GROUP 2: the backend API ("the waiter").

The pages never touch the database. They ask this API, and the API does
the work. On Vercel, every address that starts with /api comes here
(see vercel.json). On your own computer, local_server.py runs it.

    GET    /api/status                    signed in? database connected?
    POST   /api/login  /api/logout        teacher password
    GET    /api/classes                   the subjects and their classes
    POST   /api/checkin                   record one scan
    GET    /api/attendance/class          who is in one class on a date
    GET    /api/attendance/summary        every class at a glance
    GET    /api/late-times                the late times for one date
    GET    /api/late-times/changes        every day with changed times
    PUT    /api/late-times/<date>         change one day's late times
    DELETE /api/late-times/<date>         put one day back to the usual times
    GET    /api/students                  everyone, with their classes
    GET    /api/students/<code>           one student: classes, today, history
    POST   /api/students                  add or update a student
    DELETE /api/students/<code>           remove a student
    POST   /api/students/sample           load the fake students
"""

import hashlib
import hmac
import os
import re
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

# Let this file find the attendance/ folder next to api/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, jsonify, request, session  # noqa: E402

from attendance import config, database  # noqa: E402

app = Flask(__name__)

# ------------------------------------------------------------ the password
# On Vercel, set TEACHER_PASSWORD in Settings -> Environment Variables.
# On your own computer no password is needed unless you set one.
PASSWORD = os.environ.get("TEACHER_PASSWORD", "")
LOCAL_MODE = not database.USE_POSTGRES and not database.ON_VERCEL
NEEDS_PASSWORD = bool(PASSWORD) or not LOCAL_MODE

# Sign-ins are kept in a signed cookie. The signing key comes from the
# password, so changing the password signs everyone out.
if PASSWORD:
    app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
        ("qr-attendance|" + PASSWORD + "|" + database.DATABASE_URL).encode()).hexdigest()
else:
    app.secret_key = os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=database.ON_VERCEL,     # Vercel is always https
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

NO_PASSWORD_MESSAGE = (
    "No teacher password is set yet. In your Vercel project, open Settings, then "
    "Environment Variables, add TEACHER_PASSWORD, then redeploy."
)

ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,39}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ------------------------------------------------------------ helpers

def now_local():
    return datetime.now(ZoneInfo(config.TIMEZONE))


def valid_date(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%d").strftime("%Y-%m-%d") == str(text)
    except ValueError:
        return False


def date_from(value):
    """A YYYY-MM-DD date from the request, or today at the school."""
    return value if valid_date(value) else now_local().strftime("%Y-%m-%d")


def pretty_time(hhmm):
    """ "10:02" -> "10:02 AM", "14:30" -> "2:30 PM" """
    hours, minutes = map(int, hhmm.split(":"))
    return f"{(hours % 12) or 12}:{minutes:02d} {'AM' if hours < 12 else 'PM'}"


def normalize_code(raw):
    """Tidy a typed or scanned code: " stu014 " -> "STU-014", "14" -> "STU-014"."""
    code = re.sub(r"\s+", "", str(raw or "")).upper()
    if re.fullmatch(r"\d{1,4}", code):
        code = "STU-" + code.zfill(3)
    elif re.fullmatch(r"STU\d+", code):
        code = "STU-" + code[3:]
    return code


def class_json(class_id):
    c = config.CLASS_BY_ID[class_id]
    subject = config.SUBJECT_BY_KEY[c["subject"]]
    return {"class_id": class_id, "subject": subject["key"],
            "subject_name": subject["name"], "name": c["name"]}


def bad_request(message):
    return jsonify(status="bad_request", message=message), 400


def teacher_only(view):
    """Wrap a route: require the teacher password, and turn database
    problems into a clear message instead of a crash."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if NEEDS_PASSWORD and not PASSWORD:
            return jsonify(status="setup_needed", message=NO_PASSWORD_MESSAGE), 503
        if NEEDS_PASSWORD and not session.get("teacher"):
            return jsonify(status="signed_out", message="Sign in with the teacher password."), 401
        try:
            database.setup()
            return view(*args, **kwargs)
        except database.SetupNeeded as problem:
            return jsonify(status="setup_needed", message=str(problem)), 503
        except database.CONNECTION_ERRORS as problem:
            print("Database problem:", repr(problem), file=sys.stderr)
            return jsonify(status="db_unreachable",
                           message="Can't reach the database right now. Try again in a moment."), 503
    return wrapper


# ------------------------------------------------------------ sign in

@app.get("/api/status")
def status():
    setup_message = ""
    if NEEDS_PASSWORD and not PASSWORD:
        setup_message = NO_PASSWORD_MESSAGE
    elif database.ON_VERCEL and not database.USE_POSTGRES:
        setup_message = database.NO_DATABASE_MESSAGE
    return jsonify(
        signed_in=(not NEEDS_PASSWORD) or bool(session.get("teacher")),
        password_required=NEEDS_PASSWORD,
        storage="postgres" if database.USE_POSTGRES else ("none" if database.ON_VERCEL else "file"),
        setup_message=setup_message,
    )


@app.post("/api/login")
def login():
    if not NEEDS_PASSWORD:
        return jsonify(status="ok")
    if not PASSWORD:
        return jsonify(status="setup_needed", message=NO_PASSWORD_MESSAGE), 503
    given = str((request.get_json(silent=True) or {}).get("password", ""))
    if hmac.compare_digest(given.encode(), PASSWORD.encode()):
        session.permanent = True
        session["teacher"] = True
        return jsonify(status="ok")
    time.sleep(1)    # slows down anyone guessing passwords
    return jsonify(status="wrong_password", message="That password isn't right."), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(status="ok")


# ------------------------------------------------------------ classes

@app.get("/api/classes")
@teacher_only
def classes():
    return jsonify(subjects=[
        {"key": s["key"], "name": s["name"], "pa": s["pa"], "late_after": s["late_after"],
         "classes": [{"class_id": config.class_id(s["key"], name), "name": name}
                     for name in s["classes"]]}
        for s in config.SUBJECTS
    ])


# ------------------------------------------------------------ check in

@app.post("/api/checkin")
@teacher_only
def checkin():
    """Record one scan.

    Request:  {"student_id": "STU-014", "class_id": "gurmat-level-3b",
               "date": "2026-11-22", "scanned_at": "10:02"}
    Replies:
      200 checked_in          {name, time, late, class}
      409 already_checked_in  {name, time}        (the first scan counts)
      409 not_in_class        {name, belongs_in}  (belongs_in may be null)
      404 unknown_id          {student_id, message}
      400 bad_request         {message}
    """
    data = request.get_json(silent=True) or {}
    code = normalize_code(data.get("student_id"))
    class_id = str(data.get("class_id", ""))
    if not code:
        return bad_request("student_id is required")
    if class_id not in config.CLASS_BY_ID:
        return bad_request("class_id is missing or not a real class")

    # Use the scanner's own date and clock (the school's local time).
    date = date_from(data.get("date"))
    scanned_at = str(data.get("scanned_at", ""))
    if not TIME_RE.match(scanned_at):
        scanned_at = now_local().strftime("%H:%M")

    student = database.get_student(code) if ID_RE.match(code) else None
    if student is None:
        return jsonify(status="unknown_id", student_id=code,
                       message=f"No student has the code {code}"), 404

    the_class = config.CLASS_BY_ID[class_id]
    subject = config.SUBJECT_BY_KEY[the_class["subject"]]
    enrolled = student["classes"].get(subject["key"])
    if enrolled != class_id:
        return jsonify(status="not_in_class", student_id=code, name=student["name"],
                       belongs_in=config.CLASS_BY_ID[enrolled]["name"] if enrolled else None), 409

    # The day's late time (usually from config.py, unless changed for this day).
    # "HH:MM" text compares correctly: "10:21" > "10:20".
    late_after = database.late_times(date)[subject["key"]][0]
    late = scanned_at > late_after
    saved, first = database.add_check_in(code, class_id, date, scanned_at,
                                         "late" if late else "present")
    if saved:
        return jsonify(status="checked_in", student_id=code, name=student["name"],
                       time=pretty_time(scanned_at), late=late, **{"class": class_json(class_id)})
    return jsonify(status="already_checked_in", student_id=code, name=student["name"],
                   time=pretty_time(first["scanned_at"])), 409


# ------------------------------------------------------------ attendance

@app.get("/api/attendance/class")
@teacher_only
def attendance_class():
    """Who is in one class on a date.

    GET /api/attendance/class?class_id=gurmat-level-3b&date=2026-11-22
      {date, class, count, total,
       present: [{student_id, name, time, late}], missing: [{student_id, name}]}
    """
    class_id = request.args.get("class_id", "")
    if class_id not in config.CLASS_BY_ID:
        return bad_request("class_id is missing or not a real class")
    date = date_from(request.args.get("date"))
    present, missing = database.class_attendance(class_id, date)
    present = [{"student_id": r["student_id"], "name": r["name"],
                "time": pretty_time(r["scanned_at"]), "late": r["status"] == "late"}
               for r in present]
    missing = [{"student_id": r["student_id"], "name": r["name"]} for r in missing]
    return jsonify(date=date, count=len(present), total=len(present) + len(missing),
                   present=present, missing=missing, **{"class": class_json(class_id)})


@app.get("/api/attendance/summary")
@teacher_only
def attendance_summary():
    """Every class at a glance.

    GET /api/attendance/summary?date=2026-11-22
      {date, students_checked_in, total_students,
       classes: [{class_id, subject, name, total, here, late, missing}]}
    """
    date = date_from(request.args.get("date"))
    rows, came, total = database.summary(date)
    return jsonify(
        date=date, students_checked_in=came, total_students=total,
        classes=[{"class_id": r["class_id"], "subject": r["subject"], "name": r["name"],
                  "total": int(r["total"]), "here": int(r["here"]), "late": int(r["late"]),
                  "missing": int(r["missing"])}
                 for r in rows if r["class_id"] in config.CLASS_BY_ID],
    )


# ------------------------------------------------------------ late times

def late_times_json(date):
    times = database.late_times(date)
    return [{"subject": s["key"], "name": s["name"], "late_after": times[s["key"]][0],
             "usual": s["late_after"], "changed": times[s["key"]][1]}
            for s in config.SUBJECTS]


@app.get("/api/late-times")
@teacher_only
def get_late_times():
    """The late time for each subject on one date.

    GET /api/late-times?date=2026-11-29
      {date, times: [{subject, name, late_after, usual, changed}]}
    """
    date = date_from(request.args.get("date"))
    return jsonify(date=date, times=late_times_json(date))


@app.get("/api/late-times/changes")
@teacher_only
def late_time_changes():
    """Every day whose late times were changed, newest first.

      {changes: [{date, times: {gurmat: "10:40"}}]}
    """
    return jsonify(changes=[{"date": d, "times": t} for d, t in database.all_late_time_changes()])


@app.put("/api/late-times/<date>")
@teacher_only
def change_late_times(date):
    """Set one day's late times. Request: {"times": {"gurmat": "10:40", ...}}
    A subject left out (or set to its usual time) goes back to the usual time.
    Check-ins already made that day are re-marked with the new times."""
    if not valid_date(date):
        return bad_request("Use a date like 2026-11-29.")
    times = (request.get_json(silent=True) or {}).get("times") or {}
    clean = {}
    for s in config.SUBJECTS:
        value = str(times.get(s["key"]) or "")
        if value and not TIME_RE.match(value):
            return bad_request(f"{s['name']}: use a time like 10:20.")
        clean[s["key"]] = value
    database.set_late_times(date, clean)
    return jsonify(status="ok", date=date, times=late_times_json(date))


@app.delete("/api/late-times/<date>")
@teacher_only
def reset_late_times(date):
    """Put one day back to the usual late times."""
    if not valid_date(date):
        return bad_request("Use a date like 2026-11-29.")
    database.set_late_times(date, {})
    return jsonify(status="ok", date=date, times=late_times_json(date))


# ------------------------------------------------------------ students

@app.get("/api/students")
@teacher_only
def students():
    return jsonify(students=database.list_students())


@app.get("/api/students/<code>")
@teacher_only
def student_detail(code):
    """One student: their classes, today's check-ins and recent days.

    GET /api/students/STU-014?date=2026-11-22
    """
    code = normalize_code(code)
    student = database.get_student(code) if ID_RE.match(code) else None
    if student is None:
        return jsonify(status="unknown_id", student_id=code,
                       message=f"No student has the code {code}"), 404
    date = date_from(request.args.get("date"))
    days = {}
    for r in database.student_check_ins(code):
        entry = {"class_id": r["class_id"], "class_name": r["name"],
                 "time": pretty_time(r["scanned_at"]), "late": r["status"] == "late"}
        days.setdefault(r["date"], {"date": r["date"]})[r["subject"]] = entry
    history = sorted(days.values(), key=lambda d: d["date"], reverse=True)
    today = days.get(date, {})
    return jsonify(
        student=student, date=date,
        today={s["key"]: today.get(s["key"]) for s in config.SUBJECTS},
        history=history,
    )


@app.post("/api/students")
@teacher_only
def save_student():
    """Add or update a student.

    Request: {"student_id": "STU-023", "name": "...", "grade": 7, "mode": "add",
              "classes": {"gurmat": "gurmat-level-2", "gurmukhi": "", "elective": "elective-tabla"}}
    mode "add" refuses a code that is already taken; mode "edit" updates it.
    """
    data = request.get_json(silent=True) or {}
    code = normalize_code(data.get("student_id"))
    name = re.sub(r"\s+", " ", str(data.get("name", ""))).strip()
    if not ID_RE.match(code):
        return bad_request("Use letters, numbers and dashes for the code, like STU-023.")
    if not name or len(name) > 80:
        return bad_request("Type the student's name (80 characters at most).")
    grade = data.get("grade")
    try:
        grade = int(grade) if grade not in (None, "") else None
    except (TypeError, ValueError):
        return bad_request("Grade must be a number.")
    if grade is not None and not 1 <= grade <= 12:
        return bad_request("Grade must be between 1 and 12.")
    chosen = data.get("classes") or {}
    class_ids = []
    for s in config.SUBJECTS:
        class_id = str(chosen.get(s["key"]) or "")
        if class_id:
            if config.CLASS_BY_ID.get(class_id, {}).get("subject") != s["key"]:
                return bad_request(f"That isn't one of the {s['name']} classes.")
            class_ids.append(class_id)
    if not database.save_student(code, name, grade, class_ids, must_be_new=data.get("mode") == "add"):
        taken = database.get_student(code)
        return jsonify(status="taken", message=f"{code} already belongs to {taken['name']}. Pick another code."), 409
    return jsonify(status="ok", student=database.get_student(code))


@app.delete("/api/students/<code>")
@teacher_only
def remove_student(code):
    code = normalize_code(code)
    if not ID_RE.match(code) or not database.delete_student(code):
        return jsonify(status="unknown_id", message=f"No student has the code {code}"), 404
    return jsonify(status="ok")


@app.post("/api/students/sample")
@teacher_only
def sample_students():
    return jsonify(status="ok", loaded=database.load_sample_students())
