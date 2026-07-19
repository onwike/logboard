# logboard

A local dashboard over markdown issue registers — tool errors, coding errors, corrections, and miscalculations. One small Python server, one HTML page, no cloud service of its own. Your registers stay on your machine — the one exception is the optional Tagging help feature, and only if you point it at a cloud model (see Privacy posture).

I log every resolved tool failure, coding defect, corrected assumption, and numeric slip into running markdown registers, so a mistake paid for once is never paid for twice. logboard turns those files into trends, hot-spots, and a searchable console — and, optionally, uses a language model (offline, or your own cloud CLI) to help bulk-tag entries.

![Dashboard in light mode — a live system with 259 entries; register text is redacted in the capture](docs/demo-light.png)

## Quickstart

```
python3 serve.py
```

Open http://127.0.0.1:8799 and enter the paths to your register files in the setup screen:

![First-run setup screen](docs/demo-setup.png)

That's it. The config is saved to `roots.json` next to serve.py — gitignored, so your paths and data are never tracked. Prefer a file? Copy `roots.example.json` to `roots.json` and edit. The port is `LOGBOARD_PORT` (default 8799), bound to 127.0.0.1 only.

Dark mode follows your system:

![Dashboard in dark mode — same live system, register text redacted](docs/demo-dark.png)

## What it shows

- Recency-first counts per register: last 7 days, delta vs the prior 7, sparkline
- Entries per day (auto-buckets to weeks on long ranges), stacked by register; picking a tag switches to an emphasis view
- Lane and project breakdowns
- Hot-spots: top tags, top tools and areas, and repeat offenders (signatures with more than one occurrence)
- Tagging debt: an untagged entry is an open defect, tracked in its own chart until it decays to zero
- A searchable, filterable table of every entry with full drill-down — deep-linkable by id (`#E13`) or tag (`#tag=network`)
- Tag editing in the drill-down: remove a tag with its ×, add one from the canon-filtered picker — edits land in the register file itself (see the privacy notes for the guardrails)
- **App health**: logboard logs its own runtime errors (server exceptions and client-side JS errors) into a separate panel, kept out of your engineering analytics — the tool watches its own health
- **Tagging help**: describe the entries you want tagged, and a local model proposes the matches for you to confirm before anything is written (see below)

Everything re-parses on every request, so the page is always current — edit a register, refresh the page.

## Tagging help (local, optional)

Bulk-tagging with a human gate. Describe what you want tagged ("anything about timezone or UTC/local parsing drift"), pick a scope (log types, projects, sessions — empty means all), and the model returns which entries match. You review the matches, untick any false positives, and confirm — only then is the tag written, through the same guarded single-line editor used everywhere else. A tag new to the canon is added (name + applies-to + definition) as part of the same confirmed step.

The model is **advisory**: it receives `{uid, summary, cause, fix}` — never file paths — and returns only IDs, which the server intersects against the real corpus, so a hallucinated or injected id can never reach a register. Two providers, chosen in settings:

- **Ollama** — fully offline (`http://127.0.0.1:11434`); the corpus never leaves the machine. This is the default; name the model in settings.
- `claude -p` — runs through your own Claude Code CLI, but the CLI sends the entry text to **Anthropic's cloud model** (on your subscription). Stronger matching, but the in-scope entry text leaves your machine — use it deliberately.

logboard itself holds no API key and calls no cloud service directly; the only egress is whatever your chosen CLI/endpoint does. Match quality tracks the model — a small offline model will be noisier, which is exactly what the confirmation step is for.

## The register format

Each register is a plain markdown file. Entries live under a `## Details` heading; each entry is a heading plus labeled bullet lines (shown indented here; don't indent yours):

```
 ### E01 — one-line summary of the failure signature
 - **Lane:** who hit it
 - **Tool:** what broke
 - **Root cause:** why it really happened
 - **Resolution:** the reusable fix
 - **Tags:** network, config
 - **Occurrences:** 2026-06-24 10:02 EDT; 2026-07-08 09:15 EDT
```

Four register types, one grammar:

| Register | IDs | Scope | Category field | Fix field | Date field |
|---|---|---|---|---|---|
| Tool errors | E | global | Tool | Resolution | Occurrences |
| Coding errors | CE | global | Area | Fix | Occurrences |
| Corrections | C | per project (`corrections.md`) | Trigger | Correction | Date |
| Miscalculations | M | per project (`miscalculations.md`) | How caught | Correct | Date |

Semantics worth knowing:

- A recurrence is not a new entry — append a `; `-separated segment to the existing entry's Occurrences line. The segment count is the occurrence count.
- Corrections and miscalculations carry the date they were logged (`Date`) and, optionally, the date the event actually happened — a trailing `| YYYY-MM-DD` at the end of the Evidence line. Charts prefer the event date.
- `Tags` is optional. Entries without it show up as tagging debt, not errors.
- An `## Index` table at the top of each file is treated as a derived view; only the Details blocks are parsed.
- Entries end at an HTML append-marker comment — a line like `<!-- TOOL-ERROR-APPEND-HERE -->` (any `…-APPEND-HERE` comment works) — or end of file. Anything below the marker is ignored.

## Tags

`tags.txt` is the controlled vocabulary: one tag per line, three tab-separated columns — name, which registers it applies to (comma list of E,CE,C,M), definition. Comment lines start with `#`. See `tags.example.txt`. Point the setup screen's tag-canon field at yours; tags in entries that aren't in the canon are flagged on the dashboard.

## Checks and audit

- `python3 serve.py --check` — parser self-checks: per-file parsed count must equal the heading count and the Index row count, plus payload sanity. Drop a `golden.local.json` next to serve.py (gitignored) to pin absolute counts and per-entry expectations.
- `python3 serve.py --audit` — strict tagging audit: exits nonzero listing every untagged entry, every off-canon tag, and canon syntax problems. Schedule it daily (cron, or launchd on macOS) and append to a log:

```
0 18 * * * cd /path/to/logboard && python3 serve.py --audit >> audit.log 2>&1
```

The audit is also **actionable in the dashboard**: the **Tag audit** panel lists every untagged entry (with a jump to its tag editor) and every off-canon or wrong-register tag with inline resolution — pick a canon tag to replace it, or click "allow \<tag\> in \<register\>" to extend the canon's applies-to (that's a `POST /canon` write: local-admin-only, lock-guarded, journaled). So the audit doesn't just flag problems, it drives them to zero.

## Hosting the page elsewhere (optional)

The frontend is one static file. Host `index.html` anywhere, open its settings panel and point the data-endpoint field at your local server, and add the page's origin to `allowed_origins` in `roots.json`. serve.py answers CORS and private-network preflights only for origins you list (default: none). If you reach the server through a tunnel hostname rather than `127.0.0.1`, also add that hostname to `allowed_hosts` (the Host-header gate rejects everything else). Your registers still live only on the machine running serve.py — the remote page just reads them.

## Privacy posture

**Your data stays in tools you control.** The server binds 127.0.0.1 and holds no API key; it never calls a cloud service directly. The only way any register content leaves your machine is if you use Tagging help *and* choose the `claude -p` provider — then your own logged-in CLI forwards the in-scope entries' `{uid, summary, cause, fix}` (never file paths) to Anthropic's cloud model, exactly as any `claude -p` call would. The default provider is **Ollama**, which runs fully offline and sends nothing anywhere. Leave Tagging help unused, or keep it on Ollama, and no register content ever leaves the machine.

- The server binds 127.0.0.1 and rejects requests whose `Host` header doesn't name this machine (anti-DNS-rebinding; add a tunnel hostname to `allowed_hosts` in `roots.json` if you ever front it deliberately). It writes its own `roots.json`, its `tag-edits.log` journal, its gitignored `app-errors.md` (self-logged runtime errors), and — only through the tag editor or Tagging help — the `Tags` line of one register entry at a time plus, when you create one, a single new line in your tag canon: lock-guarded, written atomically, re-parsed after every write with automatic restore on any anomaly, and journaled (each edited file also gains a persistent `.lock` sibling and a transient `.logboard-tmp` during the write). Nothing else in a register is ever touched. Register writes are refused for cross-site origins even when `allowed_origins` grants read access.
- This repo ships layered leak guards: a pre-commit hook that enforces the tracked-path allowlist, pre-commit and pre-push content scans that refuse any home-directory path or register entry heading (**opt-in per clone**: `git config core.hooksPath .githooks`), and a CI workflow that re-scans the full pushed history server-side. The patterns catch structure, not arbitrary prose — treat them as a net, not a proof.
- The dashboard screenshots are captures of a live system with all register text (summaries, causes, notices) blurred before publishing — a manual pre-publish step, reviewed by eye; the setup screenshot uses synthetic demo data. Numbers, charts, tags, and lane/project labels are shown as-is.

MIT license.
