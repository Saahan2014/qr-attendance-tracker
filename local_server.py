"""
local_server.py - run the whole site on your own computer.

    python local_server.py

On Vercel this file isn't used: Vercel serves the public/ folder itself and
sends /api requests to api/index.py. Here, one small server does both, and
saves to attendance.db in this folder. No password is needed unless you set
TEACHER_PASSWORD.
"""

import os
import threading
import webbrowser

from flask import abort, send_from_directory

from api.index import app

PUBLIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
PORT = 5000


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def pages(path):
    """Serve public/ the way Vercel does: /scan shows public/scan.html."""
    if path.startswith("api/"):
        abort(404)
    if path == "":
        return send_from_directory(PUBLIC, "index.html")
    if os.path.isfile(os.path.join(PUBLIC, path)):
        return send_from_directory(PUBLIC, path)
    if os.path.isfile(os.path.join(PUBLIC, path + ".html")):
        return send_from_directory(PUBLIC, path + ".html")
    abort(404)


if __name__ == "__main__":
    url = f"http://localhost:{PORT}/"
    print(f"QR Attendance Tracker running at {url}  (Ctrl+C to stop)")
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host="127.0.0.1", port=PORT)
