"""
config.py - settings you can change without touching the rest of the code.

After changing anything here, push to GitHub and Vercel redeploys by itself.
"""

import re

# The subjects and the classes inside each one. To add a class, add its name
# to a list. Each class gets a permanent id made from its subject and name
# ("gurmat-level-3a"), so renaming a class starts it fresh.
#
# late_after: the usual time (24-hour HH:MM). A scan AFTER it is marked late.
# To change the time for just one day, use the Late times page instead.
SUBJECTS = [
    {"key": "gurmat", "name": "Gurmat", "pa": "ਗੁਰਮਤਿ", "late_after": "10:20",
     "classes": ["Level 1", "Level 2", "Level 3A", "Level 3B", "Level 4", "Level 5"]},
    {"key": "gurmukhi", "name": "Gurmukhi", "pa": "ਗੁਰਮੁਖੀ", "late_after": "12:20",
     "classes": ["Level 1", "Level 2", "Level 3", "Level 4",
                 "Level 5", "Level 6", "Level 7", "Level 8"]},
    {"key": "elective", "name": "Elective", "pa": "", "late_after": "11:20",
     "classes": ["Computer Class", "Life Skills", "Kirtan", "Tabla", "Math Class"]},
]

# The school's time zone. Used when the scanner doesn't send its own clock.
TIMEZONE = "America/Los_Angeles"

# The database file used when you run the site on your own computer.
# (On Vercel the site uses the online Postgres database instead.)
DB_FILE = "attendance.db"

# Fake students for testing. The Badges page has a button that loads them.
# (code, name, grade, gurmat class, gurmukhi class, elective)
SAMPLE_STUDENTS = [
    ("STU-011", "Maya Okafor", 6, "Level 2", "Level 3", "Kirtan"),
    ("STU-012", "Liam Nguyen", 6, "Level 2", "Level 3", "Tabla"),
    ("STU-013", "Sofia Ramirez", 7, "Level 3A", "Level 4", "Kirtan"),
    ("STU-014", "Aman Gill", 7, "Level 3B", "Level 4", "Tabla"),
    ("STU-015", "Aisha Rahman", 8, "Level 3B", "Level 5", "Computer Class"),
    ("STU-016", "Noah Lindqvist", 8, "Level 3A", "Level 5", "Math Class"),
    ("STU-017", "Simran Sandhu", 6, "Level 2", "Level 3", "Kirtan"),
    ("STU-018", "Harjot Dhillon", 6, "Level 2", "Level 3", "Tabla"),
    ("STU-019", "Jasleen Brar", 7, "Level 3A", "Level 4", "Life Skills"),
    ("STU-020", "Gurveer Sidhu", 7, "Level 3B", "Level 4", "Computer Class"),
    ("STU-021", "Navneet Bains", 8, "Level 3B", "Level 5", "Computer Class"),
    ("STU-022", "Karan Grewal", 8, "Level 3A", "Level 5", "Tabla"),
]


# ---------------------------------------------------------------------------
# Built from the lists above - no need to edit below this line.

def class_id(subject_key, class_name):
    """("gurmat", "Level 3A") -> "gurmat-level-3a" """
    return subject_key + "-" + re.sub(r"[^a-z0-9]+", "-", class_name.lower()).strip("-")


SUBJECT_BY_KEY = {s["key"]: s for s in SUBJECTS}

CLASSES = []          # every class, in order
CLASS_BY_ID = {}      # "gurmat-level-3a" -> that class
for subject_number, subject in enumerate(SUBJECTS):
    for class_number, name in enumerate(subject["classes"]):
        info = {
            "class_id": class_id(subject["key"], name),
            "subject": subject["key"],
            "name": name,
            "sort_order": subject_number * 100 + class_number,
        }
        CLASSES.append(info)
        CLASS_BY_ID[info["class_id"]] = info
