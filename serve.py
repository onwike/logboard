#!/usr/bin/env python3
"""logboard — a local dashboard over markdown issue registers.

Serves a single-page dashboard and a JSON API on 127.0.0.1 only. The
registers are re-parsed on every request, so the page is always fresh.
Writes are confined to: roots.json (the browser setup screen), the
tag-edits.log journal, and — only through the guarded tag editor — the
single Tags line of one register entry at a time (plus its .lock and
transient .logboard-tmp siblings). Nothing else in a register is ever
touched.

Usage:
  python3 serve.py            start the server (port 8799, or $LOGBOARD_PORT)
  python3 serve.py --check    parse everything and run self-checks; exit 1 on failure
  python3 serve.py --audit    strict tag audit; exit 1 on any debt or canon problem
"""

import fcntl
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

APP = "logboard"
BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "roots.json")
GOLDEN_PATH = os.path.join(BASE, "golden.local.json")
AUDIT_LOG = os.path.join(BASE, "tag-edits.log")
INDEX_PATH = os.path.join(BASE, "index.html")
PORT = int(os.environ.get("LOGBOARD_PORT", "8799"))

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
HEAD_RE = re.compile(u"^### ([A-Z]+)(\\d+) — (.*)$")
FIELD_RE = re.compile(r"^- \*\*([^:]+):\*\* ?(.*)$")
MARKER_RE = re.compile(r"^<!--\s*\S*-APPEND-HERE\s*-->")
EVENT_RE = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2})\s*$")

PREFIX = {"tool_error": "E", "coding_error": "CE",
          "correction": "C", "miscalculation": "M"}

# Raw field label -> normalized slot, per register type. Unknown labels are
# tolerated (one warning each); values on unknown labels are ignored.
FIELD_MAPS = {
    "tool_error": {"Lane": "lane", "Tool": "category", "Root cause": "cause",
                   "Resolution": "fix", "Detail": "detail", "Symptom": "symptom",
                   "Occurrences": "occurrences_raw", "Tags": "tags_raw"},
    "coding_error": {"Lane": "lane", "Area": "category", "Root cause": "cause",
                     "Fix": "fix", "Detail": "detail",
                     "Occurrences": "occurrences_raw", "Tags": "tags_raw"},
    "correction": {"Lane": "lane", "Trigger": "category", "Wrong": "cause",
                   "Correction": "fix", "Evidence": "evidence",
                   "Date": "date_logged_raw", "Tags": "tags_raw"},
    "miscalculation": {"Lane": "lane", "How caught": "category", "Wrong": "cause",
                       "Correct": "fix", "Miscalculation": "summary_dup",
                       "Evidence": "evidence", "Date": "date_logged_raw",
                       "Tags": "tags_raw"},
}

ALLOWED_KEYS = {"global_logs", "project_roots", "tags_file", "allowed_origins",
                "allowed_hosts"}


def expand(p):
    return os.path.expanduser(p) if isinstance(p, str) else p


def normalize(cur, log_type, project, path, warnings):
    """Build one flat entry record. Dates stay plain YYYY-MM-DD strings —
    no datetime objects and no timezone math anywhere in this program."""
    f = cur["fields"]
    summary = cur["summary"] or f.get("summary_dup") or ""
    if not summary:
        warnings.append("%s: empty summary" % cur["id"])

    detail_parts = []
    if f.get("detail"):
        detail_parts.append(f["detail"])
    if f.get("symptom"):
        detail_parts.append("Symptom: " + f["symptom"])
    detail = u" · ".join(detail_parts) if detail_parts else None

    tags = []
    if f.get("tags_raw"):
        tags = [t.strip().lower() for t in f["tags_raw"].split(",") if t.strip()]

    occurrences_raw = f.get("occurrences_raw")
    date_logged_raw = f.get("date_logged_raw")
    occurrence_dates = []
    date_event = None
    if log_type in ("tool_error", "coding_error"):
        if occurrences_raw:
            # Bare ";" split mirrors the registers' own index semantics
            # (a parenthetical semicolon counts as a segment there too).
            count = len(occurrences_raw.split(";"))
            occurrence_dates = DATE_RE.findall(occurrences_raw)
            date_logged = occurrence_dates[0] if occurrence_dates else None
            if date_logged is None:
                warnings.append("%s: no date in Occurrences" % cur["id"])
        else:
            count = 0
            date_logged = None
            warnings.append("%s: missing Occurrences" % cur["id"])
    else:
        count = 1
        date_logged = None
        if date_logged_raw:
            dm = DATE_RE.search(date_logged_raw)
            date_logged = dm.group(0) if dm else None
        else:
            warnings.append("%s: missing Date" % cur["id"])
        ev = f.get("evidence")
        if ev:
            em = EVENT_RE.search(ev)
            if em:
                date_event = em.group(1)

    return {
        "uid": "%s:%s" % (project, cur["id"]),
        "id": cur["id"],
        "log_type": log_type,
        "project": project,
        "source_log": path,
        "summary": summary,
        "lane": f.get("lane"),
        "category": f.get("category"),
        "cause": f.get("cause"),
        "fix": f.get("fix"),
        "detail": detail,
        "evidence": f.get("evidence"),
        "tags": tags,
        "untagged": len(tags) == 0,
        "date_logged": date_logged,
        "date_event": date_event,
        "date_best": date_event or date_logged,
        "occurrence_dates": occurrence_dates,
        "count": count,
        "occurrences_raw": occurrences_raw,
        "date_logged_raw": date_logged_raw,
    }


def parse_log(path, log_type, project):
    """Parse one register file. Returns (entries, warnings)."""
    warnings = []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return [], ["unreadable: %s" % exc]

    fmap = FIELD_MAPS[log_type]
    prefix = PREFIX[log_type]
    unknown_keys = set()
    entries = []
    cur = None

    def flush():
        if cur is not None:
            entries.append(normalize(cur, log_type, project, path, warnings))

    for line in text.splitlines():
        if MARKER_RE.match(line):
            break
        m = HEAD_RE.match(line)
        if m:
            flush()
            cur = None
            if m.group(1) != prefix:
                warnings.append("heading %s%s does not match expected prefix %s; block skipped"
                                % (m.group(1), m.group(2), prefix))
                continue
            cur = {"id": m.group(1) + m.group(2),
                   "summary": m.group(3).strip(), "fields": {}}
            continue
        if line.startswith("### ") and cur is not None:
            warnings.append("unparseable heading terminates a block: %r" % line[:80])
            flush()
            cur = None
            continue
        if cur is None:
            continue
        fm = FIELD_RE.match(line)
        if fm:
            key = fm.group(1).strip()
            slot = fmap.get(key)
            if slot is None:
                if key not in unknown_keys:
                    unknown_keys.add(key)
                    warnings.append("%s: unknown field '%s' ignored" % (cur["id"], key))
            else:
                cur["fields"][slot] = fm.group(2).strip()
    flush()

    ids = [e["id"] for e in entries]
    seen = set()
    for i in ids:
        if i in seen:
            warnings.append("duplicate id %s" % i)
        seen.add(i)
    return entries, warnings


def parse_canon(path):
    """Parse the tag canon file. Returns (tags, warnings)."""
    tags = []
    warnings = []
    if not path:
        return tags, warnings
    xp = expand(path)
    if not os.path.isfile(xp):
        return tags, ["tags file not found: %s" % path]
    with open(xp, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                warnings.append("tags line %d: expected 3 tab-separated columns" % lineno)
                continue
            applies = [a.strip().upper() for a in parts[1].split(",") if a.strip()]
            bad = [a for a in applies if a not in ("E", "CE", "C", "M")]
            if bad:
                warnings.append("tags line %d: unknown register prefix %s" % (lineno, ",".join(bad)))
            tags.append({"tag": parts[0].strip().lower(),
                         "applies_to": applies,
                         "definition": parts[2].strip()})
    return tags, warnings


def load_config():
    if not os.path.isfile(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) else None


def file_meta(display_path, real_path, log_type, project):
    meta = {"path": display_path, "project": project, "log_type": log_type,
            "present": os.path.isfile(real_path), "mtime": None, "size": None,
            "entry_count": 0, "warnings": []}
    if meta["present"]:
        st = os.stat(real_path)
        meta["mtime"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))
        meta["size"] = st.st_size
    return meta


def collect(cfg):
    """Parse every configured register. Returns (entries, files, canon, canon_warnings)."""
    entries = []
    files = []
    gl = (cfg or {}).get("global_logs") or {}
    for lt in ("tool_error", "coding_error"):
        p = gl.get(lt)
        if not p:
            continue
        xp = expand(p)
        meta = file_meta(p, xp, lt, "global")
        if meta["present"]:
            es, ws = parse_log(xp, lt, "global")
            meta["entry_count"] = len(es)
            meta["warnings"] = ws
            entries.extend(es)
        else:
            meta["warnings"] = ["configured but missing"]
        files.append(meta)

    for root in (cfg or {}).get("project_roots") or []:
        xr = expand(root)
        project = os.path.basename(xr.rstrip("/")) or xr
        for lt, fname in (("correction", "corrections.md"),
                          ("miscalculation", "miscalculations.md")):
            fp = os.path.join(xr, fname)
            meta = file_meta(fp, fp, lt, project)
            if meta["present"]:
                es, ws = parse_log(fp, lt, project)
                meta["entry_count"] = len(es)
                meta["warnings"] = ws
                entries.extend(es)
            files.append(meta)

    canon, canon_warnings = parse_canon((cfg or {}).get("tags_file"))
    return entries, files, canon, canon_warnings


def build_payload():
    cfg = load_config()
    configured = bool(cfg and ((cfg.get("global_logs") or {}) or cfg.get("project_roots")))
    if configured:
        entries, files, canon, canon_warnings = collect(cfg)
    else:
        entries, files, canon, canon_warnings = [], [], [], []
    return {
        "app": APP,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "port": PORT,
        "configured": configured,
        "entry_count": len(entries),
        "entries": entries,
        "files": files,
        "tag_canon": canon,
        "canon_warnings": canon_warnings,
    }


def validate_config(cfg):
    """Validate a submitted config. Returns (errors, results); any error
    means nothing gets written."""
    errors = []
    results = []
    if not isinstance(cfg, dict):
        return ["config must be a JSON object"], []
    unknown = sorted(set(cfg) - ALLOWED_KEYS)
    if unknown:
        errors.append("unknown keys: %s" % ", ".join(unknown))

    gl = cfg.get("global_logs") or {}
    if not isinstance(gl, dict) or set(gl) - {"tool_error", "coding_error"}:
        errors.append("global_logs must be an object with keys tool_error / coding_error")
        gl = {}
    for lt in ("tool_error", "coding_error"):
        p = gl.get(lt)
        if not p:
            continue
        if not isinstance(p, str) or not os.path.isabs(expand(p)):
            errors.append("%s: path must be absolute (~ allowed)" % lt)
            continue
        xp = expand(p)
        if not os.path.isfile(xp):
            errors.append("%s: file not found: %s" % (lt, p))
            continue
        es, ws = parse_log(xp, lt, "probe")
        results.append({"path": p, "role": lt, "ok": True,
                        "entries": len(es), "warnings": len(ws)})

    roots = cfg.get("project_roots") if cfg.get("project_roots") is not None else []
    if not isinstance(roots, list) or any(not isinstance(r, str) for r in roots):
        errors.append("project_roots must be a list of paths")
        roots = []
    for r in roots:
        xr = expand(r)
        if not os.path.isabs(xr):
            errors.append("project root must be absolute (~ allowed): %s" % r)
        elif not os.path.isdir(xr):
            errors.append("project root not found: %s" % r)
        else:
            found = [n for n in ("corrections.md", "miscalculations.md")
                     if os.path.isfile(os.path.join(xr, n))]
            results.append({"path": r, "role": "project_root", "ok": True, "found": found})

    tf = cfg.get("tags_file")
    if tf:
        if not isinstance(tf, str) or not os.path.isabs(expand(tf)):
            errors.append("tags_file must be an absolute path (~ allowed)")
        elif not os.path.isfile(expand(tf)):
            results.append({"path": tf, "role": "tags_file", "ok": False,
                            "note": "not found yet (fine before the canon exists)"})
        else:
            _, cws = parse_canon(tf)
            results.append({"path": tf, "role": "tags_file", "ok": True,
                            "warnings": len(cws)})

    ao = cfg.get("allowed_origins") if cfg.get("allowed_origins") is not None else []
    if not isinstance(ao, list) or any(not isinstance(o, str) for o in ao):
        errors.append("allowed_origins must be a list of origin strings")
    ah = cfg.get("allowed_hosts") if cfg.get("allowed_hosts") is not None else []
    if not isinstance(ah, list) or any(not isinstance(h, str) for h in ah):
        errors.append("allowed_hosts must be a list of host names")

    names = {}
    for r in roots:
        b = os.path.basename(expand(r).rstrip("/"))
        if b in names:
            errors.append("duplicate project name %r (%s and %s) — tag edits could target the wrong file"
                          % (b, names[b], r))
        names[b] = r

    if not any(gl.get(lt) for lt in ("tool_error", "coding_error")) and not roots:
        errors.append("configure at least one register (a global log or a project root)")
    return errors, results


def count_entries(text, prefix):
    """Heading count with the same below-marker semantics as parse_log:
    anything after the append marker does not exist."""
    kept = []
    for line in text.splitlines():
        if MARKER_RE.match(line):
            break
        kept.append(line)
    return len(re.findall(r"(?m)^### %s\d+ " % prefix, "\n".join(kept)))


def find_register_file(cfg, uid):
    """Resolve a uid (project:ID) to (path, log_type)."""
    project, _, eid = uid.partition(":")
    m = re.match(r"([A-Z]+)\d+$", eid)
    if not m:
        return None, None
    lt = None
    for k, v in PREFIX.items():
        if v == m.group(1):
            lt = k
    if lt is None:
        return None, None
    if project == "global":
        p = (cfg.get("global_logs") or {}).get(lt)
        return (expand(p), lt) if p else (None, None)
    if lt not in ("correction", "miscalculation"):
        return None, None
    for root in cfg.get("project_roots") or []:
        xr = expand(root)
        if (os.path.basename(xr.rstrip("/")) or xr) == project:
            fname = "corrections.md" if lt == "correction" else "miscalculations.md"
            return os.path.join(xr, fname), lt
    return None, None


def edit_tags(cfg, uid, add, remove):
    """Add/remove tags on ONE entry's Tags line — the only register write this
    program can perform. Lockf-guarded, atomic, verified after write, journaled.
    Returns (ok, message, tags_after)."""
    path, lt = find_register_file(cfg, uid)
    if not path or not os.path.isfile(path):
        return False, "unknown uid or register file: %s" % uid, None
    eid = uid.partition(":")[2]
    pre = PREFIX[lt]
    canon, _cw = parse_canon(cfg.get("tags_file"))
    allowed = dict((t["tag"], set(t["applies_to"])) for t in canon)
    for t in add:
        if t not in allowed:
            return False, "tag %r is not in the canon" % t, None
        if pre not in allowed[t]:
            return False, "tag %r is not allowed in the %s register" % (t, pre), None
    with open(path + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
            pre_count = count_entries(original, pre)
            lines = original.split("\n")
            head_re = re.compile(u"^### %s — " % re.escape(eid))
            start = None
            for i, ln in enumerate(lines):
                if head_re.match(ln):
                    start = i
                    break
            if start is None:
                return False, "entry %s not found in %s" % (eid, os.path.basename(path)), None
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if lines[j].startswith("### ") or MARKER_RE.match(lines[j]):
                    end = j
                    break
            tags_i = None
            lane_i = None
            cur = []
            for j in range(start + 1, end):
                fm = FIELD_RE.match(lines[j])
                if not fm:
                    continue
                key = fm.group(1).strip()
                if key == "Tags":
                    tags_i = j
                    cur = [t.strip().lower() for t in fm.group(2).split(",") if t.strip()]
                elif key == "Lane":
                    lane_i = j
            new = [t for t in cur if t not in set(remove)]
            for t in add:
                if t not in new:
                    new.append(t)
            if new == cur:
                return True, "no change", new
            if tags_i is not None:
                if new:
                    lines[tags_i] = "- **Tags:** " + ", ".join(new)
                else:
                    del lines[tags_i]
            elif new:
                at = (lane_i + 1) if lane_i is not None else (start + 1)
                lines.insert(at, "- **Tags:** " + ", ".join(new))
            candidate = "\n".join(lines)
            if count_entries(candidate, pre) != pre_count:
                return False, "refused: edit would change the entry count", None
            tmp = path + ".logboard-tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(candidate)
            os.replace(tmp, path)
            es, _ws = parse_log(path, lt, "verify")
            if len(es) != pre_count:
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(original)
                os.replace(tmp, path)
                return False, "post-write verify failed; original content restored", None
            with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
                fh.write("%s\t%s\t+%s\t-%s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), uid,
                    ",".join(add), ",".join(remove)))
            return True, "updated", new
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


class Handler(BaseHTTPRequestHandler):
    server_version = APP

    def log_message(self, fmt, *args):
        pass

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return None
        cfg = load_config() or {}
        allowed = cfg.get("allowed_origins") or []
        return origin if origin in allowed else None

    def _host_ok(self):
        """Anti-DNS-rebinding: the Host header must name this machine (or an
        explicitly configured extra host, e.g. a future tunnel hostname)."""
        h = self.headers.get("Host") or ""
        if h.startswith("["):
            host = h.split("]", 1)[0] + "]"
        else:
            host = h.split(":", 1)[0]
        if host in ("127.0.0.1", "localhost", "[::1]"):
            return True
        cfg = load_config() or {}
        return host in (cfg.get("allowed_hosts") or [])

    def _local_origin(self):
        """True only for same-machine pages: no Origin header, or a
        localhost origin. Tag editing is local-admin only."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            host = origin.split("//", 1)[1].split("/")[0].rsplit(":", 1)[0]
        except IndexError:
            return False
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        origin = self._origin_ok()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if not self._host_ok():
            self._send(403, {"error": "invalid host"})
            return
        origin = self._origin_ok()
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            self._send(403, {"error": "invalid host"})
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            try:
                with open(INDEX_PATH, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, {"error": "index.html missing next to serve.py"})
        elif path == "/data.json":
            self._send(200, build_payload())
        elif path == "/config":
            cfg = load_config()
            errors, results = validate_config(cfg) if cfg else ([], [])
            self._send(200, {"config": cfg, "errors": errors, "results": results})
        else:
            self._send(404, {"error": "not found"})

    def _read_json_body(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > 65536:
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_POST(self):
        if not self._host_ok():
            self._send(403, {"error": "invalid host"})
            return
        path = self.path.split("?", 1)[0]
        if path == "/config":
            cfg = self._read_json_body()
            if cfg is None:
                self._send(400, {"errors": ["body must be JSON (max 64 KB)"]})
                return
            errors, results = validate_config(cfg)
            if errors:
                self._send(400, {"errors": errors, "results": results})
                return
            # Config write: fixed path in this server's own directory.
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
                fh.write("\n")
            self._send(200, {"ok": True, "results": results})
        elif path == "/tags":
            if not self._local_origin():
                self._send(403, {"ok": False, "message": "tag editing is local-admin only"})
                return
            body = self._read_json_body()
            if not isinstance(body, dict) or not isinstance(body.get("uid"), str):
                self._send(400, {"ok": False, "message": "body must be JSON: {uid, add[], remove[]}"})
                return
            add = body.get("add") or []
            remove = body.get("remove") or []
            if (not isinstance(add, list) or not isinstance(remove, list)
                    or any(not isinstance(t, str) for t in add + remove)):
                self._send(400, {"ok": False, "message": "add/remove must be lists of tag names"})
                return
            cfg = load_config()
            if not cfg:
                self._send(400, {"ok": False, "message": "server is not configured"})
                return
            add = [t.strip().lower() for t in add if t.strip()]
            remove = [t.strip().lower() for t in remove if t.strip()]
            ok, message, tags = edit_tags(cfg, body["uid"], add, remove)
            self._send(200 if ok else 400, {"ok": ok, "message": message, "tags": tags})
        else:
            self._send(404, {"error": "not found"})


def run_check():
    cfg = load_config()
    if not cfg:
        print("check: no roots.json — complete the setup screen (or POST /config) first")
        return 2
    failures = []
    oks = []
    entries, files, canon, canon_warnings = collect(cfg)

    by_uid = {}
    for e in entries:
        if e["uid"] in by_uid:
            failures.append("duplicate uid %s" % e["uid"])
        by_uid[e["uid"]] = e

    for meta in files:
        if not meta["present"]:
            continue
        xp = expand(meta["path"])
        with open(xp, encoding="utf-8") as fh:
            text = fh.read()
        prefix = PREFIX[meta["log_type"]]
        heads = count_entries(text, prefix)
        rows = len(re.findall(r"(?m)^\| ?%s\d+ " % prefix, text))
        line = "%s: parsed=%d headings=%d index-rows=%d" % (
            meta["path"], meta["entry_count"], heads, rows)
        if meta["entry_count"] == heads == rows:
            oks.append(line)
        else:
            failures.append(line + " MISMATCH")

    for e in entries:
        for k in ("uid", "id", "log_type", "summary"):
            if not e[k]:
                failures.append("%s: empty %s" % (e["uid"], k))

    try:
        json.dumps(build_payload())
        oks.append("payload serializes")
    except (TypeError, ValueError) as exc:
        failures.append("payload does not serialize: %s" % exc)

    totals = {}
    for e in entries:
        totals[e["log_type"]] = totals.get(e["log_type"], 0) + 1

    golden = None
    if os.path.isfile(GOLDEN_PATH):
        with open(GOLDEN_PATH, encoding="utf-8") as fh:
            golden = json.load(fh)
    if golden:
        for lt, mn in sorted((golden.get("min_totals") or {}).items()):
            got = totals.get(lt, 0)
            if got >= mn:
                oks.append("total %s=%d (min %d)" % (lt, got, mn))
            else:
                failures.append("total %s=%d BELOW pinned min %d" % (lt, got, mn))
        for uid, expect in sorted((golden.get("entries") or {}).items()):
            e = by_uid.get(uid)
            if not e:
                failures.append("pinned uid missing: %s" % uid)
                continue
            for k, v in sorted(expect.items()):
                if e.get(k) != v:
                    failures.append("%s.%s=%r expected %r" % (uid, k, e.get(k), v))
                else:
                    oks.append("%s.%s ok" % (uid, k))
        null_only = set(golden.get("lane_null_only") or [])
        for uid in sorted(null_only):
            e = by_uid.get(uid)
            if not e or e["lane"] is not None or "Symptom:" not in (e["detail"] or ""):
                failures.append("legacy pin failed for %s" % uid)
            else:
                oks.append("legacy %s: lane null + Symptom folded" % uid)
        scope = golden.get("lane_null_scope")
        if scope:
            for e in entries:
                if e["log_type"] == scope and e["lane"] is None and e["uid"] not in null_only:
                    failures.append("unexpected null lane: %s" % e["uid"])
        all_warnings = [w for m in files for w in m["warnings"]]
        for sub in golden.get("warnings_contain") or []:
            if any(sub in w for w in all_warnings):
                oks.append("warning present: %r" % sub)
            else:
                failures.append("expected a warning containing %r" % sub)
        for proj, lt in golden.get("absent_files") or []:
            hit = [m for m in files if m["project"] == proj and m["log_type"] == lt]
            if hit and not hit[0]["present"]:
                oks.append("absent as expected: %s %s" % (proj, lt))
            else:
                failures.append("expected absent file: %s %s" % (proj, lt))
    else:
        oks.append("no golden.local.json — structural checks only")

    print("check: %d ok, %d failed | entries=%d files=%d totals=%s"
          % (len(oks), len(failures),
             len(entries), len(files), json.dumps(totals, sort_keys=True)))
    for f_ in failures:
        print("FAIL %s" % f_)
    return 1 if failures else 0


def run_audit():
    cfg = load_config()
    if not cfg:
        print("audit: no roots.json — dashboard not configured")
        return 2
    entries, files, canon, canon_warnings = collect(cfg)
    problems = 0
    if not cfg.get("tags_file"):
        print("audit: no tags_file configured")
        problems += 1
    for w in canon_warnings:
        print("audit: canon: %s" % w)
        problems += 1
    untagged = [e for e in entries if e["untagged"]]
    for e in untagged:
        print("audit: untagged: %s — %s" % (e["uid"], e["summary"][:70]))
    problems += len(untagged)
    canon_names = set(t["tag"] for t in canon)
    applies = dict((t["tag"], set(t["applies_to"])) for t in canon)
    for e in entries:
        for t in e["tags"]:
            if canon_names and t not in canon_names:
                print("audit: unknown tag %r on %s" % (t, e["uid"]))
                problems += 1
            elif canon_names and PREFIX[e["log_type"]] not in applies.get(t, set()):
                print("audit: tag %r not allowed in register %s (%s)"
                      % (t, PREFIX[e["log_type"]], e["uid"]))
                problems += 1
    stamp = time.strftime("%Y-%m-%d %H:%M %Z")
    print("audit: %s — %d entries, %d untagged, %d problems"
          % (stamp, len(entries), len(untagged), problems))
    return 1 if problems else 0


def main():
    if "--check" in sys.argv:
        sys.exit(run_check())
    if "--audit" in sys.argv:
        sys.exit(run_audit())
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    state = "present" if os.path.isfile(CONFIG_PATH) else "absent — open the page to set up"
    print("%s serving on http://127.0.0.1:%d (config %s)" % (APP, PORT, state))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
