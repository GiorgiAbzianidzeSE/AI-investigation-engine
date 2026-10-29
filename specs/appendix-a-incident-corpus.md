# Appendix A — Synthetic incident corpus ("Northwind Payments", March 2026)

Purpose: the brief's investigation scenario (changes → incidents → affected services), in **several file
formats**, with **planted contradictions** and **deliberate gaps**. HotpotQA supplies the scale; this corpus
supplies the story. `scripts/make_incidents.py` holds the text and renders the files into `data/incidents/`.

Rules for writing the documents:
- Realistic prose (headings, paragraphs, tables as text). Not just the facts below as bullet points.
- ASCII only (PDF core fonts).
- Each fact appears only in the documents listed for it. Don't add extra facts that would answer the
  "gaps" questions or quietly settle a contradiction.
- `doc_id` = `incidents:<slug(filename)>` (e.g. `INC-2041-incident-report.pdf` → `incidents:inc-2041-incident-report-pdf`).

## World facts

**Company:** Northwind Payments (card payments processor).

**Services and owners** (source: service catalog, except where noted):

| Service | Owner | Notes |
|---|---|---|
| payments-gateway | Payments Core team | entry point for card authorizations |
| fraud-scorer | Risk Engineering (catalog) — **ML Platform team (runbook)** | contradiction C4 |
| ledger-service | Core Banking team | PostgreSQL "ledger DB", connection pool |
| settlement-batch | Treasury Engineering | nightly merchant payouts |
| reconciliation-job | Finance Ops Engineering | nightly, 00:00–01:30 UTC |
| notification-service | Customer Comms team | emails/SMS via external provider MailRelay |
| auth-service | Identity team | **no SLA documented anywhere** (gap) |

**Authorization flow** (architecture doc): payments-gateway → fraud-scorer (synchronous call) → ledger-service
(writes an authorization hold through the ledger DB connection pool) → notification-service (async).
The gateway's end-to-end timeout is 1,200 ms. Nightly: reconciliation-job 00:00–01:30 UTC; settlement-batch
at 02:00 UTC. Both write to the ledger DB.

**Changes:**

| ID | Date | Service | Change | Requested by | Approver |
|---|---|---|---|---|---|
| CHG-0311 | 2026-03-03 | ledger-service | DB connection pool max 200 → 50 (cost reduction) | Core Banking | J. Okafor |
| CHG-0314 | 2026-03-05 09:00 UTC | fraud-scorer | model v4 rollout; p99 latency 80 ms → ~900 ms | Risk Engineering | **blank** (gap) |
| CHG-0320 | 2026-03-10 | notification-service | TLS certificate rotation; no impact | Customer Comms | L. Haddad |
| CHG-0327 | 2026-03-18 | settlement-batch | schedule 02:00 → 00:30 UTC (earlier EU payouts) | Treasury Engineering | M. Silva |
| CHG-0331 | 2026-03-24 | ledger-service | pool 50 → 200, rollback of CHG-0311 (INC-2041 action item) | Core Banking | J. Okafor |

**Incidents:**

| ID | When | What | Root cause (per incident report) | Affected services |
|---|---|---|---|---|
| INC-2041 | 2026-03-05 09:40–13:20 UTC (3 h 40 min), SEV-1 | card authorizations delayed/timing out, ~18% failed | CHG-0314 made fraud-scorer slow → requests held ledger DB connections longer → pool (cut to 50 by CHG-0311) exhausted → gateway timeouts. fraud-scorer rolled back to v3 at 13:05. | payments-gateway, fraud-scorer, ledger-service |
| INC-2047 | 2026-03-19 00:30–03:15 UTC (2 h 45 min), SEV-2 | merchant payouts delayed | CHG-0327 made settlement-batch overlap reconciliation-job → row-lock contention on ledger DB; schedule moved to 01:45 UTC on 2026-03-20 | settlement-batch, ledger-service, reconciliation-job; **1,200 merchants** affected |
| INC-2052 | 2026-03-26, ~20 min | notification emails delayed | outage at external provider MailRelay; **no internal change involved** | notification-service |

**Planted contradictions:**

| ID | Topic | Side 1 | Side 2 |
|---|---|---|---|
| C1 | INC-2041 root cause | incident report: CHG-0314 + CHG-0311 | status page: "outage at a third-party card network"; postmortem: CHG-0311 **only** |
| C2 | INC-2041 duration | incident report + postmortem: 3 h 40 min | status page: "about 2 hours" |
| C3 | INC-2047 merchants affected | incident report: 1,200 | finance summary: 4,500 |
| C4 | fraud-scorer owner | service catalog: Risk Engineering | runbook: ML Platform team |
| C5 | fraud-scorer's role in INC-2041 | incident report: contributing cause | postmortem: "fraud-scorer was not a contributing factor" |

**Deliberate gaps** (nothing in the corpus answers these): the cost of INC-2041 in euros (the finance summary says
"cost impact under review"); who approved CHG-0314; any April 2026 incident; the auth-service SLA;
a "mobile-app" service (doesn't exist); the company's CEO.

## Documents

| # | Filename | Format | Content (facts it must contain) |
|---|---|---|---|
| 1 | `changelog-march-2026.md` | MD | all five changes, one section each: date, service, summary, requester (no approvers) |
| 2 | `CHG-0311-change-request.docx` | DOCX | CHG-0311 form: description, reason, risk "low", rollback plan, approver J. Okafor |
| 3 | `CHG-0314-change-request.docx` | DOCX | CHG-0314 form: v4 model, expected p99 ≤ 120 ms in testing, approver field **empty** |
| 4 | `CHG-0320-change-request.docx` | DOCX | TLS rotation; post-change note "no customer impact" |
| 5 | `CHG-0327-change-request.docx` | DOCX | schedule change and reason; doesn't mention reconciliation-job |
| 6 | `CHG-0331-change-request.docx` | DOCX | pool restored to 200; "rollback of CHG-0311, action item from INC-2041" |
| 7 | `INC-2041-incident-report.pdf` | PDF | INC-2041 row above: timeline, impact (~18% failed), root cause CHG-0314 + CHG-0311, affected services, observed p99 ~900 ms |
| 8 | `INC-2047-incident-report.pdf` | PDF | INC-2047 row above, 1,200 merchants, the lock contention explanation, fix on 03-20 |
| 9 | `INC-2052-incident-report.pdf` | PDF | INC-2052 row; "no internal change was involved" |
| 10 | `PM-2041-postmortem.pdf` | PDF | **long** (≥1,200 words) with sections Summary, Impact, Timeline (10+ timestamped entries), Root cause (CHG-0311 only), Contributing factors ("fraud-scorer was not a contributing factor"), What went well, Action items (CHG-0331, pool alerts, model load testing). Written by Core Banking. |
| 11 | `status-page-march-2026.html` | HTML | public notices: INC-2041 "about 2 hours", "third-party card network"; INC-2047 "delayed payouts"; INC-2052 "email delays" |
| 12 | `finance-summary-march-2026.html` | HTML | table of the month's incidents; INC-2047: 4,500 merchants; INC-2041 "cost impact under review" |
| 13 | `service-catalog.html` | HTML | the services table (owners incl. fraud-scorer = Risk Engineering), short description each, no auth-service SLA |
| 14 | `fraud-scorer-runbook.md` | MD | owner: ML Platform team; on-call; latency SLO p99 < 150 ms; how to roll back a model version |
| 15 | `payments-architecture.md` | MD | **long** (≥1,000 words): authorization flow, sync fraud-scorer call, 1,200 ms gateway timeout, ledger DB pool, nightly job schedule (recon 00:00–01:30, settlement 02:00) |
| 16 | `ops-review-march-2026.pdf` | PDF | monthly summary: 5 changes, 3 incidents; CHG-0320 had no customer impact; INC-2052 was external; INC-2041 linked to CHG-0314 and CHG-0311; INC-2047 linked to CHG-0327 |

**Dedup demo files** (in `data/incidents/dedup-demo/`; upload them through the UI during the demo, not part of bulk ingest):

| Filename | Expected result |
|---|---|
| `fraud-scorer-runbook-copy.md` | byte-identical copy of #14 → `status: duplicate` |
| `payments-architecture-v2.md` | #15 plus one line `Last reviewed: 2026-03-28` → added, `near_duplicate_of` = #15 |
| `edited/payments-architecture-v2.md` (same filename, adds a "Changelog" section) | upload after the one above with "replace" ticked → `status: updated`, version 2 |
