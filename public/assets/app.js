// app.js - GROUP 3: helpers every page shares.
//
// Every page calls startPage() first. It checks the teacher is signed in
// (sending them to /login if not), loads the subjects and classes, then
// lets the page draw itself.
"use strict";

var SUBJECTS = [];          // filled in by startPage() from GET /api/classes

// ------------------------------------------------------------ small helpers

function $(id) { return document.getElementById(id); }

// el("li", {class: "x", text: "hi"}, [child, child]) builds an element.
// It uses textContent, so names can never run as code in the page.
function el(tag, attrs, kids) {
  var node = document.createElement(tag);
  Object.keys(attrs || {}).forEach(function (key) {
    var value = attrs[key];
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.indexOf("on") === 0) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  });
  (kids || []).forEach(function (kid) { if (kid != null) node.append(kid); });
  return node;
}

function pad(n) { return String(n).padStart(2, "0"); }
function todayStr() { var d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
function nowHHMM() { var d = new Date(); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
function prettyTime(hhmm) {
  var parts = String(hhmm || "").split(":"), h = +parts[0];
  if (isNaN(h) || !parts[1]) return hhmm || "";
  return ((h % 12) || 12) + ":" + parts[1] + (h < 12 ? " AM" : " PM");
}
function prettyDate(ds) {
  var p = String(ds).split("-");
  return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString(undefined,
    { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

// Tidy a typed or scanned code: " stu014 " -> "STU-014", "14" -> "STU-014".
function normalizeCode(raw) {
  var c = String(raw || "").trim().toUpperCase().replace(/\s+/g, "");
  if (/^\d{1,4}$/.test(c)) c = "STU-" + c.padStart(3, "0");
  else if (/^STU\d+$/.test(c)) c = "STU-" + c.slice(3);
  return c;
}

// Remember small choices (like the last class picked) on this device only.
function recall(key) { try { return localStorage.getItem("qat-" + key) || ""; } catch (e) { return ""; } }
function remember(key, value) { try { localStorage.setItem("qat-" + key, value); } catch (e) { /* blocked */ } }

var toastTimer = null;
function toast(message) {
  var t = $("toast");
  if (!t) { t = el("div", { class: "toast", id: "toast", role: "status" }); document.body.append(t); }
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
}

function subjectBy(key) { return SUBJECTS.find(function (s) { return s.key === key; }); }
function classById(classId) {
  for (var i = 0; i < SUBJECTS.length; i++) {
    var found = SUBJECTS[i].classes.find(function (c) { return c.class_id === classId; });
    if (found) return { subject: SUBJECTS[i], class_id: found.class_id, name: found.name };
  }
  return null;
}

// ------------------------------------------------------------ talking to the API

function goToLogin() {
  location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
}

// api("/checkin", {method: "POST", body: {...}}) -> {ok, status, data}
async function api(path, options) {
  options = options || {};
  var init = { method: options.method || "GET", credentials: "same-origin", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  var response;
  try {
    response = await fetch("/api" + path, init);
  } catch (e) {
    return { ok: false, status: 0, data: { status: "offline", message: "Can't reach the server. Check the internet connection." } };
  }
  var data = {};
  try { data = await response.json(); } catch (e) { data = {}; }
  if (response.status === 401 && data.status === "signed_out") goToLogin();
  if (response.status === 503 && data.status === "setup_needed") showSetup(data.message);
  return { ok: response.ok, status: response.status, data: data };
}

// Replace the page with a "finish setting up" message.
function showSetup(message) {
  var inner = document.querySelector("main .inner");
  if (!inner || $("setup-panel")) return;
  inner.replaceChildren(el("div", { class: "panel setup-panel", id: "setup-panel" }, [
    el("h2", { text: "Almost ready" }),
    el("p", { text: message || "The site isn't fully set up yet." }),
    el("p", { class: "hint", text: "After changing a setting in Vercel, open Deployments and choose Redeploy so the site picks it up." })
  ]));
}

// ------------------------------------------------------------ page start

async function startPage() {
  var status = await api("/status");
  if (!status.ok) { showSetup(status.data.message || "Can't reach the server right now."); throw new Error("no server"); }
  if (status.data.setup_message) { showSetup(status.data.setup_message); throw new Error("setup"); }
  if (!status.data.signed_in) { goToLogin(); throw new Error("signed out"); }

  var signout = $("signout");
  if (signout && status.data.password_required) {
    signout.hidden = false;
    signout.addEventListener("click", async function () {
      await api("/logout", { method: "POST" });
      location.href = "/login";
    });
  }
  var classes = await api("/classes");
  if (!classes.ok) throw new Error("no classes");
  SUBJECTS = classes.data.subjects;
  return status.data;
}

// Subject buttons ("Gurmat ਗੁਰਮਤਿ") used on the check-in screen and dashboard.
function subjectButtons(container, includeAll, current, onPick) {
  container.replaceChildren();
  var list = includeAll ? [{ key: "all", name: "All", pa: "" }].concat(SUBJECTS) : SUBJECTS;
  list.forEach(function (s) {
    container.append(el("button", {
      type: "button", "aria-pressed": String(s.key === current), "data-key": s.key,
      onclick: function () { onPick(s.key); }
    }, [s.name, s.pa ? el("span", { class: "pa", lang: "pa", text: s.pa }) : null]));
  });
}

// ------------------------------------------------------------ QR codes (GROUP 4)

var qrCache = new Map();

// A QR code picture (as an image URL) holding just the student code.
function qrDataUrl(text) {
  if (qrCache.has(text)) return qrCache.get(text);
  var qr = qrcode(0, "H");     // "H" = still scans with ~30% smudged or creased
  qr.addData(text);
  qr.make();
  var n = qr.getModuleCount(), quiet = 4, cell = 8, size = (n + quiet * 2) * cell;
  var canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  var pen = canvas.getContext("2d");
  pen.fillStyle = "#ffffff"; pen.fillRect(0, 0, size, size);
  pen.fillStyle = "#000000";
  for (var r = 0; r < n; r++) for (var c = 0; c < n; c++) {
    if (qr.isDark(r, c)) pen.fillRect((c + quiet) * cell, (r + quiet) * cell, cell, cell);
  }
  var url = canvas.toDataURL("image/png");
  qrCache.set(text, url);
  return url;
}

// Look for a QR code in what's drawn on a canvas. Returns its text or "".
// tryInverted also looks for light-on-dark codes (slower, so not every frame).
function qrFromCanvas(pen, width, height, tryInverted) {
  var found = jsQR(pen.getImageData(0, 0, width, height).data, width, height,
                   { inversionAttempts: tryInverted ? "attemptBoth" : "dontInvert" });
  return found && found.data ? found.data.trim() : "";
}

// Draw a picture (like a photo) onto a canvas, then look for a QR code in it.
function readQr(source, width, height, pen) {
  pen.drawImage(source, 0, 0, width, height);
  return qrFromCanvas(pen, width, height, true);
}
