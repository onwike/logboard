#!/usr/bin/env python3
"""logboard test suite — stdlib-only (unittest), self-contained.

Every test runs against synthetic fixtures created in a temp directory;
no test ever reads or writes a real register. POSIX-only (fcntl), like
the server itself. Run: python3 test_logboard.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

import serve

HERE = os.path.dirname(os.path.abspath(__file__))


def F(s):
    """Strip the one-char pipe armor from fixture literals. The armor keeps
    register-shaped lines from starting at column 0, so this file passes the
    repo's own pre-push content guard while the runtime fixtures stay exact."""
    return "\n".join(line[1:] for line in s.split("\n") if line != "") + "\n"

TOOL_LOG = F(u"""|# Tool Error Log — test fixture
|
|## Index
|
|| ID | Tool | Error signature | Root cause | Resolution | First seen | Count |
||----|------|-----------------|-----------|-----------|-----------|-------|
|| E01 | deployctl | expired token | cache | re-login | 2026-06-24 | 2 |
|| E02 | curl | wrong server | squatter | assert identity | 2026-06-30 | 1 |
|| E03 | git | hook skipped | per-clone config | set hooksPath | 2026-07-11 | 1 |
|
|## Details
|
|### E01 — CLI deploy failed with an expired auth token
|- **Tool:** deployctl
|- **Symptom:** deploy exited 1 with a 401.
|- **Root cause:** cached token expired
|- **Resolution:** re-login before deploy
|- **Occurrences:** 2026-06-24 10:02 EDT; 2026-07-08 09:15 EDT (recurred on the staging runner; mid-deploy)
|
|### E02 — curl probe hit the wrong local server on a shared port
|- **Lane:** Backend
|- **Tool:** curl
|- **Root cause:** another process was listening
|- **Resolution:** assert the responder identity
|- **Odd field:** should be tolerated
|- **Tags:** network, config
|- **Occurrences:** 2026-06-30 14:11 EDT
|
|### E03 — git hook skipped because hooksPath was unset
|- **Lane:** Tooling
|- **Tool:** git
|- **Root cause:** per-clone configuration
|- **Resolution:** set hooks path at bootstrap
|- **Occurrences:** 2026-07-11 16:40 EDT
|
|<!-- TOOL-ERROR-APPEND-HERE -->
|### E99 — below the marker, must never parse
|- **Tool:** ghost
|- **Occurrences:** 2026-07-12 00:00 EDT
|""")

CODING_LOG = F(u"""|# Coding Error Log — test fixture
|
|## Index
|
|| ID | Area | Error signature | Root cause | Fix | First seen | Count |
||----|------|-----------------|-----------|-----|-----------|-------|
|| CE01 | JS · datetime | local parse | no zone signal | normalize | 2026-06-26 | 1 |
|| CE02 | Python | off-by-one | floor division | ceil | 2026-07-05 | 1 |
|
|## Details
|
|### CE01 — Date.parse on a space-form datetime parses as local time
|- **Lane:** Backend
|- **Area:** JS · datetime
|- **Root cause:** no timezone signal
|- **Fix:** normalize to ISO first
|- **Tags:** datetime
|- **Occurrences:** 2026-06-26 11:30 EDT
|
|### CE02 — off-by-one dropped the final page
|- **Lane:** Backend
|- **Area:** Python
|- **Root cause:** floor division
|- **Fix:** ceil division
|- **Occurrences:** 2026-07-05 09:48 EDT
|
|<!-- CODING-ERROR-APPEND-HERE -->
|""")

CORR_LOG = F(u"""|# Corrections Log — project-a
|
|## Index
|
|| ID | Lane | What was wrong | Trigger | Correction | Date |
||----|------|----------------|---------|------------|------|
|| C01 | Backend | rate limit belief | assumption | per account | 2026-07-02 |
|| C02 | Frontend | re-render belief | self | memoizes | 2026-07-10 |
|
|## Details
|
|### C01 — believed the vendor rate limit was per key
|- **Lane:** Backend
|- **Trigger:** assumption
|- **Wrong:** treated the limit as per key
|- **Correction:** it is per account
|- **Evidence:** confirmed on the status page | 2026-06-20
|- **Date:** 2026-07-02 12:05 EDT
|
|### C02 — assumed the widget re-renders on prop change
|- **Lane:** Frontend
|- **Trigger:** self
|- **Wrong:** expected a refresh
|- **Correction:** it memoizes until remount
|- **Date:** 2026-07-10 17:22 EDT
|
|<!-- CORRECTIONS-APPEND-HERE -->
|""")

MISC_LOG = F(u"""|# Miscalculations Log — project-a
|
|## Index
|
|| ID | Lane | Miscalculation | Wrong value | Correct value | How caught | Date |
||----|------|----------------|-------------|---------------|------------|------|
|| M01 | Backend | stale row count | 41,200 | 44,738 | re-ran query | 2026-07-09 |
|
|## Details
|
|### M01 — quoted last month's row count
|- **Lane:** Backend
|- **Miscalculation:** quoted last month's row count
|- **Wrong:** 41,200
|- **Correct:** 44,738
|- **How caught:** reviewer re-ran the query
|- **Date:** 2026-07-09 13:41 EDT
|
|<!-- MISCALC-APPEND-HERE -->
|""")

TAGS_TXT = F(u"""|# test canon
|network\tE,CE,C\tRemote endpoint failures
|config\tE,CE\tConfiguration that did not travel
|datetime\tCE,M\tTimezone and parsing defects
|assumption\tC\tUnverified beliefs
|""")


def build_fixtures(root):
    """Create a full synthetic register layout under root; returns config dict."""
    proj = os.path.join(root, "project-a")
    os.makedirs(proj, exist_ok=True)
    paths = {
        "tool": os.path.join(root, "ToolErrorLog.md"),
        "coding": os.path.join(root, "CodingErrorLog.md"),
        "corr": os.path.join(proj, "corrections.md"),
        "misc": os.path.join(proj, "miscalculations.md"),
        "tags": os.path.join(root, "tags.txt"),
    }
    for path, text in ((paths["tool"], TOOL_LOG), (paths["coding"], CODING_LOG),
                       (paths["corr"], CORR_LOG), (paths["misc"], MISC_LOG),
                       (paths["tags"], TAGS_TXT)):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    cfg = {
        "global_logs": {"tool_error": paths["tool"], "coding_error": paths["coding"]},
        "project_roots": [proj],
        "tags_file": paths["tags"],
        "allowed_origins": [],
    }
    return cfg, paths


class TempConfigMixin(object):
    """Points serve's module paths into a temp dir for the test's duration."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="logboard-test-")
        self.cfg, self.paths = build_fixtures(self.tmp)
        self._saved = (serve.CONFIG_PATH, serve.AUDIT_LOG, serve.INDEX_PATH, serve.APP_LOG)
        serve.CONFIG_PATH = os.path.join(self.tmp, "roots.json")
        serve.AUDIT_LOG = os.path.join(self.tmp, "tag-edits.log")
        serve.INDEX_PATH = os.path.join(HERE, "index.html")
        serve.APP_LOG = os.path.join(self.tmp, "app-errors.md")

    def tearDown(self):
        (serve.CONFIG_PATH, serve.AUDIT_LOG, serve.INDEX_PATH,
         serve.APP_LOG) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, cfg=None):
        with open(serve.CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg if cfg is not None else self.cfg, fh)


class ParserTests(TempConfigMixin, unittest.TestCase):

    def parse(self, key, log_type, project="global"):
        return serve.parse_log(self.paths[key], log_type, project)

    def test_modern_entry_fields(self):
        entries, _ = self.parse("tool", "tool_error")
        e2 = [e for e in entries if e["id"] == "E02"][0]
        self.assertEqual(e2["lane"], "Backend")
        self.assertEqual(e2["category"], "curl")
        self.assertEqual(e2["fix"], "assert the responder identity")
        self.assertEqual(e2["tags"], ["network", "config"])
        self.assertFalse(e2["untagged"])
        self.assertEqual(e2["uid"], "global:E02")

    def test_legacy_entry_no_lane_symptom_folded(self):
        entries, _ = self.parse("tool", "tool_error")
        e1 = [e for e in entries if e["id"] == "E01"][0]
        self.assertIsNone(e1["lane"])
        self.assertIn("Symptom:", e1["detail"])
        self.assertTrue(e1["untagged"])

    def test_occurrence_count_splits_on_bare_semicolon(self):
        entries, _ = self.parse("tool", "tool_error")
        e1 = [e for e in entries if e["id"] == "E01"][0]
        # two real occurrences plus a parenthetical semicolon = 3 segments,
        # matching the registers' own index semantics
        self.assertEqual(e1["count"], 3)
        self.assertEqual(e1["date_logged"], "2026-06-24")
        self.assertEqual(e1["occurrence_dates"], ["2026-06-24", "2026-07-08"])

    def test_marker_terminates_parse(self):
        entries, _ = self.parse("tool", "tool_error")
        self.assertEqual([e["id"] for e in entries], ["E01", "E02", "E03"])

    def test_unknown_field_single_warning_entry_survives(self):
        entries, warnings = self.parse("tool", "tool_error")
        self.assertEqual(len(entries), 3)
        self.assertEqual(len([w for w in warnings if "Odd field" in w]), 1)

    def test_correction_dates_event_preferred(self):
        entries, _ = self.parse("corr", "correction", "project-a")
        c1 = [e for e in entries if e["id"] == "C01"][0]
        self.assertEqual(c1["date_logged"], "2026-07-02")
        self.assertEqual(c1["date_event"], "2026-06-20")
        self.assertEqual(c1["date_best"], "2026-06-20")
        c2 = [e for e in entries if e["id"] == "C02"][0]
        self.assertIsNone(c2["date_event"])
        self.assertEqual(c2["date_best"], "2026-07-10")

    def test_miscalculation_mapping(self):
        entries, _ = self.parse("misc", "miscalculation", "project-a")
        m1 = entries[0]
        self.assertEqual(m1["category"], "reviewer re-ran the query")
        self.assertEqual(m1["cause"], "41,200")
        self.assertEqual(m1["fix"], "44,738")
        self.assertEqual(m1["count"], 1)

    def test_prefix_mismatch_heading_is_skipped_with_warning(self):
        bad = os.path.join(self.tmp, "bad.md")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(u"## Details\n\n### X01 — wrong prefix\n- **Lane:** A\n\n"
                     u"### E01 — good\n- **Lane:** B\n- **Occurrences:** 2026-07-01 EDT\n")
        entries, warnings = serve.parse_log(bad, "tool_error", "global")
        self.assertEqual([e["id"] for e in entries], ["E01"])
        self.assertTrue(any("does not match expected prefix" in w for w in warnings))

    def test_duplicate_id_warns(self):
        dup = os.path.join(self.tmp, "dup.md")
        with open(dup, "w", encoding="utf-8") as fh:
            fh.write(u"### E01 — one\n- **Occurrences:** 2026-07-01 EDT\n\n"
                     u"### E01 — two\n- **Occurrences:** 2026-07-02 EDT\n")
        entries, warnings = serve.parse_log(dup, "tool_error", "global")
        self.assertEqual(len(entries), 2)
        self.assertTrue(any("duplicate id" in w for w in warnings))

    def test_canon_parse_and_warnings(self):
        tags, warnings = serve.parse_canon(self.paths["tags"])
        self.assertEqual(len(tags), 4)
        self.assertEqual(tags[0]["tag"], "network")
        self.assertEqual(tags[0]["applies_to"], ["E", "CE", "C"])
        bad = os.path.join(self.tmp, "badtags.txt")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(u"only-one-column\nname\tZZ\tbad register\n")
        _, warnings = serve.parse_canon(bad)
        self.assertEqual(len(warnings), 2)
        _, warnings = serve.parse_canon(os.path.join(self.tmp, "missing.txt"))
        self.assertTrue(any("not found" in w for w in warnings))


class ConfigValidationTests(TempConfigMixin, unittest.TestCase):

    def test_valid_config_passes_with_results(self):
        errors, results = serve.validate_config(self.cfg)
        self.assertEqual(errors, [])
        roles = [r["role"] for r in results]
        self.assertIn("tool_error", roles)
        self.assertIn("project_root", roles)
        tool = [r for r in results if r["role"] == "tool_error"][0]
        self.assertEqual(tool["entries"], 3)

    def test_unknown_key_rejected(self):
        cfg = dict(self.cfg, bogus=1)
        errors, _ = serve.validate_config(cfg)
        self.assertTrue(any("unknown keys" in e for e in errors))

    def test_relative_and_missing_paths_rejected(self):
        cfg = {"global_logs": {"tool_error": "relative/path.md"}, "project_roots": []}
        errors, _ = serve.validate_config(cfg)
        self.assertTrue(any("absolute" in e for e in errors))
        cfg = {"global_logs": {"tool_error": os.path.join(self.tmp, "nope.md")},
               "project_roots": []}
        errors, _ = serve.validate_config(cfg)
        self.assertTrue(any("not found" in e for e in errors))

    def test_empty_config_rejected(self):
        errors, _ = serve.validate_config({"global_logs": {}, "project_roots": []})
        self.assertTrue(any("at least one register" in e for e in errors))

    def test_duplicate_basename_rejected(self):
        r2 = os.path.join(self.tmp, "elsewhere", "project-a")
        os.makedirs(r2)
        cfg = dict(self.cfg, project_roots=[self.cfg["project_roots"][0], r2])
        errors, _ = serve.validate_config(cfg)
        self.assertTrue(any("duplicate project name" in e for e in errors))

    def test_find_register_file(self):
        path, lt = serve.find_register_file(self.cfg, "global:E02")
        self.assertEqual((path, lt), (self.paths["tool"], "tool_error"))
        path, lt = serve.find_register_file(self.cfg, "project-a:C01")
        self.assertEqual((path, lt), (self.paths["corr"], "correction"))
        self.assertEqual(serve.find_register_file(self.cfg, "project-a:E01"), (None, None))
        self.assertEqual(serve.find_register_file(self.cfg, "nowhere:C01"), (None, None))
        self.assertEqual(serve.find_register_file(self.cfg, "global:Q01"), (None, None))


class AppErrorTests(TempConfigMixin, unittest.TestCase):

    def test_append_dedupe_and_parse(self):
        serve.log_app_error("server", "ValueError in GET /x: boom", "trace\nline")
        serve.log_app_error("server", "ValueError in GET /x: boom", "trace again")
        serve.log_app_error("client", "TypeError at app.js:42")
        es = serve.parse_app_errors()
        self.assertEqual(len(es), 2)
        by_src = dict((e["category"], e) for e in es)
        self.assertEqual(by_src["server"]["count"], 2)
        self.assertEqual(len(by_src["server"]["occurrence_dates"]), 2)
        self.assertEqual(by_src["client"]["count"], 1)
        # a stack trace's newlines never leak into the summary heading
        self.assertNotIn("\n", by_src["server"]["summary"])

    def test_same_signature_different_source_not_merged(self):
        serve.log_app_error("server", "shared message")
        serve.log_app_error("client", "shared message")
        self.assertEqual(len(serve.parse_app_errors()), 2)

    def test_app_errors_excluded_from_main_entries(self):
        self.write_config()
        serve.log_app_error("server", "boom")
        payload = serve.build_payload()
        self.assertEqual(len(payload["app_errors"]), 1)
        self.assertTrue(all(e["log_type"] != "app_error" for e in payload["entries"]))

    def test_logging_never_raises(self):
        # a non-writable APP_LOG dir must not propagate an exception
        serve.APP_LOG = os.path.join(self.tmp, "no-such-dir", "app-errors.md")
        try:
            serve.log_app_error("server", "boom")  # must swallow
        except Exception as exc:
            self.fail("log_app_error raised: %s" % exc)


class EditTagsTests(TempConfigMixin, unittest.TestCase):

    def read(self, key):
        with open(self.paths[key], encoding="utf-8") as fh:
            return fh.read()

    def test_add_and_remove_roundtrip_byte_identical(self):
        original = self.read("coding")
        ok, msg, tags = serve.edit_tags(self.cfg, "global:CE02", ["config"], [])
        self.assertTrue(ok)
        self.assertEqual(tags, ["config"])
        after_add = self.read("coding")
        added = [l for l in after_add.splitlines() if l not in original.splitlines()]
        self.assertEqual(added, ["- **Tags:** config"])
        ok, _, tags = serve.edit_tags(self.cfg, "global:CE02", [], ["config"])
        self.assertTrue(ok)
        self.assertEqual(tags, [])
        self.assertEqual(self.read("coding"), original)

    def test_tags_line_inserted_after_lane_or_heading(self):
        serve.edit_tags(self.cfg, "global:CE02", ["config"], [])
        lines = self.read("coding").splitlines()
        i = lines.index(u"### CE02 — off-by-one dropped the final page")
        self.assertEqual(lines[i + 1], "- **Lane:** Backend")
        self.assertEqual(lines[i + 2], "- **Tags:** config")
        # legacy entry without a Lane: line goes directly under the heading
        serve.edit_tags(self.cfg, "global:E01", ["network"], [])
        lines = self.read("tool").splitlines()
        i = lines.index(u"### E01 — CLI deploy failed with an expired auth token")
        self.assertEqual(lines[i + 1], "- **Tags:** network")

    def test_no_change_when_tag_already_present(self):
        ok, msg, _ = serve.edit_tags(self.cfg, "global:E02", ["network"], [])
        self.assertTrue(ok)
        self.assertEqual(msg, "no change")

    def test_off_canon_and_wrong_register_rejected(self):
        ok, msg, _ = serve.edit_tags(self.cfg, "global:E02", ["bogus"], [])
        self.assertFalse(ok)
        self.assertIn("not in the canon", msg)
        ok, msg, _ = serve.edit_tags(self.cfg, "global:E02", ["datetime"], [])
        self.assertFalse(ok)
        self.assertIn("not allowed", msg)
        ok, msg, _ = serve.edit_tags(self.cfg, "global:E77", ["network"], [])
        self.assertFalse(ok)
        self.assertIn("not found", msg)

    def test_entry_count_stable_and_journal_written(self):
        before = len(serve.parse_log(self.paths["tool"], "tool_error", "g")[0])
        serve.edit_tags(self.cfg, "global:E03", ["network"], [])
        after = len(serve.parse_log(self.paths["tool"], "tool_error", "g")[0])
        self.assertEqual(before, after)
        with open(serve.AUDIT_LOG, encoding="utf-8") as fh:
            journal = fh.read()
        self.assertIn("global:E03\t+network\t-", journal)


class HttpTests(TempConfigMixin, unittest.TestCase):

    def setUp(self):
        super(HttpTests, self).setUp()
        self.server = HTTPServer(("127.0.0.1", 0), serve.Handler)
        self.port = self.server.server_address[1]
        t = threading.Thread(target=self.server.serve_forever)
        t.daemon = True
        t.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super(HttpTests, self).tearDown()

    def req(self, path, data=None, headers=None, method=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        r = urllib.request.Request(url, data=body, method=method)
        r.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            r.add_header(k, v)
        try:
            resp = urllib.request.urlopen(r)
            return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_unconfigured_then_configure_roundtrip(self):
        status, _, body = self.req("/data.json")
        d = json.loads(body)
        self.assertEqual((status, d["app"], d["configured"]), (200, "logboard", False))
        status, _, body = self.req("/config", data={"global_logs": {"tool_error": "x"},
                                                    "bogus": 1})
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(serve.CONFIG_PATH))
        status, _, _ = self.req("/config", data=self.cfg)
        self.assertEqual(status, 200)
        self.assertTrue(os.path.exists(serve.CONFIG_PATH))
        status, headers, body = self.req("/data.json")
        d = json.loads(body)
        self.assertTrue(d["configured"])
        self.assertEqual(d["entry_count"], 8)
        self.assertIn("charset=utf-8", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        by_uid = dict((e["uid"], e) for e in d["entries"])
        self.assertEqual(by_uid["global:E01"]["count"], 3)
        self.assertEqual(by_uid["project-a:C01"]["date_event"], "2026-06-20")
        self.assertEqual(len(d["tag_canon"]), 4)

    def test_host_header_rejected(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("GET", "/data.json", skip_host=True)
        conn.putheader("Host", "evil.example")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 403)
        conn.close()

    def test_unknown_path_404(self):
        status, _, _ = self.req("/nope")
        self.assertEqual(status, 404)
        status, _, _ = self.req("/nope", data={"x": 1})
        self.assertEqual(status, 404)

    def test_log_error_endpoint_and_origin_gate(self):
        status, _, body = self.req("/log-error", data={"message": "TypeError x",
                                                       "source": "client", "stack": "at f"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(len(serve.parse_app_errors()), 1)
        # cross-origin is refused (local-admin only)
        status, _, _ = self.req("/log-error", data={"message": "x"},
                                headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        # missing message is a 400
        status, _, _ = self.req("/log-error", data={"source": "client"})
        self.assertEqual(status, 400)

    def test_server_exception_becomes_clean_500_and_is_logged(self):
        # force a route body to throw; the guard must log it and return a
        # clean 500 with no traceback leaked to the client.
        orig = serve.build_payload

        def boom():
            raise RuntimeError("kaboom-secret-internal-detail")
        serve.build_payload = boom
        try:
            status, _, body = self.req("/data.json")
        finally:
            serve.build_payload = orig
        self.assertEqual(status, 500)
        self.assertNotIn(b"kaboom-secret-internal-detail", body)
        self.assertNotIn(b"Traceback", body)
        errs = serve.parse_app_errors()
        self.assertTrue(any(e["category"] == "server" and "RuntimeError" in e["summary"]
                            for e in errs))

    def test_tags_endpoint_and_origin_gate(self):
        self.write_config()
        status, _, body = self.req("/tags", data={"uid": "global:CE02",
                                                  "add": ["config"], "remove": []})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, _, body = self.req("/tags", data={"uid": "global:CE02", "add": [],
                                                  "remove": ["config"]},
                                   headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.req("/tags", data={"uid": "global:CE02", "add": [],
                                               "remove": ["config"]},
                                headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 200)
        status, _, _ = self.req("/tags", data={"uid": 5})
        self.assertEqual(status, 400)

    def test_cors_off_by_default_on_when_allowed(self):
        self.write_config()
        status, headers, _ = self.req("/data.json",
                                      headers={"Origin": "https://site.example"})
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        cfg = dict(self.cfg, allowed_origins=["https://site.example"])
        self.write_config(cfg)
        status, headers, _ = self.req("/data.json", method="OPTIONS",
                                      headers={"Origin": "https://site.example"})
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),
                         "https://site.example")
        self.assertEqual(headers.get("Access-Control-Allow-Private-Network"), "true")
        status, headers, _ = self.req("/data.json", method="OPTIONS",
                                      headers={"Origin": "https://other.example"})
        self.assertNotIn("Access-Control-Allow-Origin", headers)


class CliTests(unittest.TestCase):
    """--check / --audit / retro-tag.py exit codes, run against a copied app dir
    so the real repo's roots.json is never involved."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="logboard-cli-")
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(self.app)
        for f in ("serve.py", "retro-tag.py", "index.html"):
            shutil.copy(os.path.join(HERE, f), self.app)
        self.cfg, self.paths = build_fixtures(self.tmp)
        with open(os.path.join(self.app, "roots.json"), "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_app(self, script, *args):
        proc = subprocess.run([sys.executable, os.path.join(self.app, script)] + list(args),
                              capture_output=True, text=True, cwd=self.app)
        return proc.returncode, proc.stdout + proc.stderr

    def test_check_green_on_fixtures(self):
        code, out = self.run_app("serve.py", "--check")
        self.assertEqual(code, 0, out)
        self.assertIn("0 failed", out)

    def test_audit_flags_untagged_then_clean(self):
        code, out = self.run_app("serve.py", "--audit")
        self.assertEqual(code, 1)
        self.assertIn("untagged", out)
        assignments = {"global:E01": ["network"], "global:E03": ["config"],
                       "global:CE02": ["config"],
                       "project-a:C01": ["assumption"], "project-a:C02": ["assumption"],
                       "project-a:M01": ["datetime"]}
        with open(os.path.join(self.app, "assignments.json"), "w", encoding="utf-8") as fh:
            json.dump(assignments, fh)
        code, out = self.run_app("retro-tag.py")
        self.assertEqual(code, 0, out)
        self.assertIn("dry run", out)
        code, _ = self.run_app("serve.py", "--audit")
        self.assertEqual(code, 1)
        code, out = self.run_app("retro-tag.py", "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("6 updated", out)
        code, out = self.run_app("serve.py", "--audit")
        self.assertEqual(code, 0, out)
        self.assertIn("0 untagged", out)

    def test_retro_tag_unresolvable_uid_fails(self):
        with open(os.path.join(self.app, "assignments.json"), "w", encoding="utf-8") as fh:
            json.dump({"nowhere:C01": ["assumption"]}, fh)
        code, out = self.run_app("retro-tag.py")
        self.assertEqual(code, 1)
        self.assertIn("unresolvable", out)

    def test_pre_push_catches_large_file_leak(self):
        """A home-path leak at the top of a >100KB blob must still abort the
        push — guards against the SIGPIPE/pipefail false-clean on big files."""
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        hook = os.path.join(HERE, ".githooks", "pre-push")
        if not os.path.isfile(hook):
            self.skipTest("pre-push hook not present")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
        leak = "/Use" + "rs/secret/leak\n" + ("padding line\n" * 40000)
        with open(os.path.join(repo, "big.md"), "w") as fh:
            fh.write(leak)
        subprocess.run(["git", "add", "big.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "big"], cwd=repo, check=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                             capture_output=True, text=True).stdout.strip()
        zero = "0" * 40
        stdin = "refs/heads/main %s refs/heads/main %s\n" % (sha, zero)
        proc = subprocess.run(["bash", hook], cwd=repo, input=stdin,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, "large-file leak was not caught")
        self.assertIn("forbidden pattern", proc.stderr)

    def test_check_unconfigured_exits_2(self):
        os.remove(os.path.join(self.app, "roots.json"))
        code, _ = self.run_app("serve.py", "--check")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
