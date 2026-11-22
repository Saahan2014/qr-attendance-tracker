# QR Attendance Tracker

Every student gets a QR badge holding their student code (like `STU-014`).
They hold it up to a phone or laptop camera at the door, the scanner beeps,
and the teacher dashboard shows who is here, late or missing in each
Gurmat, Gurmukhi and Elective class.

## Pages

| Page | What it's for |
|---|---|
| `/scan` | Pick a class, then scan badges with the camera, scan a photo, or type a code |
| `/lookup` | Type a student code to see that student's classes, today's check-ins and recent days |
| `/dashboard` | Here / late / missing for every class on any date, refreshing every few seconds |
| `/badges` | Print QR badges, save one as a picture, add / edit / remove students |
| `/times` | The usual late times, and changing them for one day (a late start, an assembly) |
| `/login` | The teacher password (only asked for on the online site) |

## Run it on your own computer

Double-click `start.bat` (Windows), or run:

    pip install -r requirements.txt
    python local_server.py

It opens `http://localhost:5000` and saves to `attendance.db` in this folder.
No password is needed on your own computer. On the Badges page, click
**Load 12 sample students** to get fake students to test with.

## Put it online with Vercel

1. Push this folder to GitHub.
2. On vercel.com: **Add New → Project**, import the GitHub repository, leave
   every setting as it is, and click **Deploy**.
3. In the new project, open **Storage → Create Database → Neon (Postgres)**,
   and connect it to the project. This gives the site a `DATABASE_URL`.
4. Open **Settings → Environment Variables** and add `TEACHER_PASSWORD`
   with the password teachers will use.
5. Open **Deployments**, click the **⋯** on the newest one, and choose
   **Redeploy** so the site picks up the database and password.

After that, every push to GitHub updates the site by itself.

## How the code is split (the four groups)

| Group | Part | Files |
|---|---|---|
| 1 | Database | `attendance/database.py` (tables and queries), `attendance/config.py` (classes, late times, sample students) |
| 2 | Backend API | `api/index.py` |
| 3 | Screens | `public/*.html`, `public/assets/style.css`, `public/assets/app.js` |
| 4 | Badges and decoder | `public/badges.html` (makes badges), the camera code in `public/scan.html` (reads them) |

The QR libraries in `public/assets/vendor/` are
[jsQR](https://github.com/cozmo/jsQR) (Apache 2.0) for reading codes and
[qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) (MIT)
for making them.

### Database (Group 1)

| Table | Columns | Notes |
|---|---|---|
| `students` | `student_id` (key), `name`, `grade` | The code is text because `STU-014` has letters. |
| `classes` | `class_id` (key), `subject`, `name`, `sort_order` | Filled from `config.py`. `class_id` looks like `gurmat-level-3a`. |
| `enrollments` | `student_id`, `class_id` | One row per subject a student takes. |
| `check_ins` | `student_id`, `class_id`, `date`, `scanned_at`, `status` | The key is (student, class, date), so a second scan of the same class on the same day is refused and the first one counts. |
| `late_time_changes` | `date`, `subject`, `late_after` | Only days with their own late time get a row; every other day uses the usual time in `config.py`. |

Usual late times: Gurmat after 10:20 AM, Elective after 11:20 AM, Gurmukhi
after 12:20 PM. Changing a day's times also re-marks check-ins already made
that day.

Nobody scans in as absent: **missing** means enrolled in the class with no
check-in for that date.

### API (Group 2)

Everything except `/api/status` and `/api/login` needs the teacher to be
signed in on the online site.

| Request | Reply |
|---|---|
| `POST /api/checkin` `{"student_id": "STU-014", "class_id": "gurmat-level-3b", "date": "2026-11-22", "scanned_at": "10:02"}` | `200 checked_in` with `name`, `time`, `late` · `409 already_checked_in` with the first `time` · `409 not_in_class` with `belongs_in` · `404 unknown_id` · `400 bad_request` |
| `GET /api/attendance/class?class_id=gurmat-level-3b&date=2026-11-22` | `present` (name, time, late) and `missing` lists |
| `GET /api/attendance/summary?date=2026-11-22` | here / late / missing / enrolled for every class |
| `GET /api/students` | every student with their three classes |
| `GET /api/students/STU-014` | one student: classes, today's check-ins, recent days |
| `POST /api/students` | add (`"mode": "add"`) or update a student |
| `DELETE /api/students/STU-014` | remove a student and their attendance |
| `POST /api/students/sample` | load the 12 fake students from `config.py` |
| `GET /api/classes` | the subjects, their classes and usual late times |
| `GET /api/late-times?date=2026-11-29` | each subject's late time that day, and whether it was changed |
| `PUT /api/late-times/2026-11-29` `{"times": {"gurmat": "10:40"}}` | give that day its own times (subjects left out go back to usual) |
| `DELETE /api/late-times/2026-11-29` | put that day back to the usual times |
| `GET /api/late-times/changes` | every day with its own times |

### Changing things

- **Late time for one day:** the Late times page.
- **Usual late times, classes, time zone:** `attendance/config.py`.
- **Student list:** the Badges page.
- **Password:** change `TEACHER_PASSWORD` in Vercel and redeploy. Everyone is signed out.
