"""Text of the synthetic "Northwind Payments" March 2026 corpus (specs/appendix-a-incident-corpus.md).

Each document is a list of blocks:
  ("h1" | "h2", text)   heading
  ("p", text)           paragraph
  ("ul", [items])       bullet list
  ("kv", [(k, v)])      form fields, rendered as "Key: value" lines
  ("table", [header, *rows])

Rules: ASCII only (PDF core fonts); each fact only in the documents Appendix A lists for it; the
planted contradictions stay unresolved and the deliberate gaps stay unanswered.
"""

CHANGELOG = {
    "filename": "changelog-march-2026.md",
    "title": "Production Changelog - March 2026",
    "blocks": [
        ("h1", "Production Changelog - March 2026"),
        ("p", "Northwind Payments platform engineering. Period covered: 2026-03-01 to 2026-03-31. This log lists "
              "every production change that went through the change process during the month. Each entry gives "
              "the date, the service, a short summary and the requesting team. Approval records are kept on the "
              "individual change request forms, not in this log."),
        ("h2", "CHG-0311 - ledger-service connection pool resize"),
        ("kv", [("Date", "2026-03-03"), ("Service", "ledger-service"), ("Requested by", "Core Banking team")]),
        ("p", "Reduced the maximum size of the ledger DB connection pool from 200 to 50 connections. The goal is "
              "cost reduction: with fewer connections the database instance can be moved to a smaller size."),
        ("h2", "CHG-0314 - fraud-scorer model v4 rollout"),
        ("kv", [("Date", "2026-03-05, 09:00 UTC"), ("Service", "fraud-scorer"),
                ("Requested by", "Risk Engineering")]),
        ("p", "Rolled out version 4 of the card fraud model to all production traffic. Version 4 uses a larger "
              "feature set for card-not-present transactions."),
        ("h2", "CHG-0320 - notification-service TLS certificate rotation"),
        ("kv", [("Date", "2026-03-10"), ("Service", "notification-service"),
                ("Requested by", "Customer Comms team")]),
        ("p", "Rotated the TLS certificates used by notification-service for its outbound provider connection and "
              "its webhook endpoint. Routine rotation ahead of certificate expiry."),
        ("h2", "CHG-0327 - settlement-batch schedule change"),
        ("kv", [("Date", "2026-03-18"), ("Service", "settlement-batch"),
                ("Requested by", "Treasury Engineering")]),
        ("p", "Moved the nightly settlement-batch start time from 02:00 UTC to 00:30 UTC so that EU merchants "
              "receive their payouts earlier in the morning."),
        ("h2", "CHG-0331 - ledger-service connection pool restored"),
        ("kv", [("Date", "2026-03-24"), ("Service", "ledger-service"), ("Requested by", "Core Banking team")]),
        ("p", "Raised the maximum size of the ledger DB connection pool from 50 back to 200 connections. "
              "This reverts CHG-0311."),
    ],
}


def _change_request(cid, title, fields, sections):
    return {
        "filename": f"{cid}-change-request.docx",
        "title": f"{cid} Change Request - {title}",
        "blocks": [("h1", f"{cid} Change Request - {title}"), ("kv", fields)]
        + [b for heading, paras in sections for b in [("h2", heading)] + [("p", p) for p in paras]],
    }


CHG_0311 = _change_request(
    "CHG-0311", "Reduce ledger DB connection pool",
    [("Change ID", "CHG-0311"), ("Planned date", "2026-03-03"), ("Service", "ledger-service"),
     ("Requested by", "Core Banking team"), ("Risk", "low"), ("Approver", "J. Okafor"),
     ("Status", "Implemented")],
    [
        ("Description", [
            "Reduce the maximum size of the ledger-service database connection pool (ledger DB) from 200 to 50 "
            "connections. The change is a configuration update followed by a rolling restart of ledger-service."]),
        ("Reason", [
            "Cost reduction. Monitoring for February showed a typical peak of around 40 open connections, so a "
            "pool of 200 is oversized. A smaller pool allows the database instance to be moved to a cheaper size "
            "class at the next maintenance window."]),
        ("Risk assessment", [
            "Risk is assessed as low. Peak observed usage is below the new limit and the change is easy to revert."]),
        ("Rollback plan", [
            "Set the pool maximum back to 200 in the ledger-service configuration and perform a rolling restart. "
            "Expected rollback time is about 10 minutes."]),
    ],
)

CHG_0314 = _change_request(
    "CHG-0314", "fraud-scorer model v4",
    [("Change ID", "CHG-0314"), ("Planned date", "2026-03-05 09:00 UTC"), ("Service", "fraud-scorer"),
     ("Requested by", "Risk Engineering"), ("Risk", "medium"), ("Approver", ""), ("Approval date", ""),
     ("Status", "Implemented")],
    [
        ("Description", [
            "Promote fraud model version 4 to 100% of production traffic in fraud-scorer. Version 4 adds new "
            "features for card-not-present transactions, roughly 240 features compared with 90 in version 3."]),
        ("Testing", [
            "The model was load tested in staging. Expected p99 scoring latency in testing: 120 ms or lower "
            "(p99 <= 120 ms). Detection rate improved by about 6% on the March validation set."]),
        ("Rollback plan", [
            "Switch the active model alias in fraud-scorer back to version 3. The switch takes effect within "
            "a few minutes without a deployment."]),
    ],
)

CHG_0320 = _change_request(
    "CHG-0320", "notification-service TLS certificate rotation",
    [("Change ID", "CHG-0320"), ("Planned date", "2026-03-10"), ("Service", "notification-service"),
     ("Requested by", "Customer Comms team"), ("Risk", "low"), ("Approver", "L. Haddad"),
     ("Status", "Implemented")],
    [
        ("Description", [
            "Rotate the TLS certificates used by notification-service: the client certificate for the outbound "
            "connection to the email and SMS provider, and the server certificate of the delivery webhook "
            "endpoint. The current certificates expire at the end of the month."]),
        ("Rollback plan", ["Re-install the previous certificates from the secrets store."]),
        ("Post-change note", [
            "Completed on 2026-03-10 at 22:15 UTC. All health checks green. No customer impact."]),
    ],
)

CHG_0327 = _change_request(
    "CHG-0327", "settlement-batch schedule change",
    [("Change ID", "CHG-0327"), ("Planned date", "2026-03-18"), ("Service", "settlement-batch"),
     ("Requested by", "Treasury Engineering"), ("Risk", "low"), ("Approver", "M. Silva"),
     ("Status", "Implemented")],
    [
        ("Description", [
            "Change the start time of the nightly settlement-batch run from 02:00 UTC to 00:30 UTC, effective "
            "from the night of 2026-03-18 to 2026-03-19."]),
        ("Reason", [
            "Several EU merchants asked to receive payouts before the start of their business day. Starting the "
            "batch 90 minutes earlier means payout files reach the banking partner before its morning cut-off."]),
        ("Rollback plan", ["Restore the previous schedule entry (02:00 UTC) in the job scheduler."]),
    ],
)

CHG_0331 = _change_request(
    "CHG-0331", "Restore ledger DB connection pool",
    [("Change ID", "CHG-0331"), ("Planned date", "2026-03-24"), ("Service", "ledger-service"),
     ("Requested by", "Core Banking team"), ("Risk", "low"), ("Approver", "J. Okafor"),
     ("Status", "Implemented")],
    [
        ("Description", [
            "Raise the maximum size of the ledger DB connection pool from 50 back to 200 connections."]),
        ("Reason", [
            "This change is a rollback of CHG-0311 and is an action item from INC-2041. The smaller pool left no "
            "headroom when request latency increased."]),
        ("Rollback plan", ["Not applicable; this change restores the earlier configuration."]),
    ],
)

INC_2041 = {
    "filename": "INC-2041-incident-report.pdf",
    "title": "INC-2041 Incident Report - Card authorization delays",
    "blocks": [
        ("h1", "INC-2041 Incident Report - Card authorization delays"),
        ("kv", [("Date", "2026-03-05"), ("Severity", "SEV-1"), ("Status", "Resolved"),
                ("Duration", "3 h 40 min (09:40 to 13:20 UTC)")]),
        ("h2", "Summary"),
        ("p", "On 2026-03-05 card authorizations were delayed and many timed out. Between 09:40 and 13:20 UTC "
              "about 18% of card authorization requests failed, and most of the others completed slowly. The "
              "incident lasted 3 h 40 min."),
        ("h2", "Impact"),
        ("p", "About 18% of card authorization requests failed with a gateway timeout during the incident window. "
              "Merchants saw declined or slow card payments at checkout. No data was lost."),
        ("h2", "Timeline (UTC)"),
        ("ul", [
            "09:00 CHG-0314 deployed: fraud-scorer model v4 serves all traffic.",
            "09:40 Alerts for payments-gateway timeouts; incident opened.",
            "10:05 fraud-scorer p99 latency observed at about 900 ms, up from about 80 ms before the rollout.",
            "10:30 ledger-service reports its database connection pool at 50 of 50 connections in use.",
            "11:15 Incident raised to SEV-1.",
            "13:05 fraud-scorer rolled back to model v3.",
            "13:20 Authorization success rate back to normal; incident resolved.",
        ]),
        ("h2", "Root cause"),
        ("p", "The incident was caused by two changes acting together. CHG-0314 rolled out fraud model v4, which "
              "made fraud-scorer much slower: the observed p99 latency was about 900 ms. payments-gateway calls "
              "fraud-scorer synchronously and keeps its ledger-service session, and with it a ledger DB "
              "connection, open until the authorization completes. Slow fraud scoring therefore kept ledger DB "
              "connections checked out for much longer than usual."),
        ("p", "Two days earlier CHG-0311 had reduced the ledger DB connection pool from 200 to 50 connections. "
              "With the smaller pool and the longer hold time the pool was exhausted, new authorizations waited "
              "for a connection, and payments-gateway hit its timeout."),
        ("h2", "Affected services"),
        ("ul", ["payments-gateway", "fraud-scorer", "ledger-service"]),
        ("h2", "Resolution"),
        ("p", "fraud-scorer was rolled back to model v3 at 13:05 UTC. Latency dropped, connections were released "
              "and the authorization success rate recovered by 13:20 UTC."),
        ("h2", "Action items"),
        ("ul", [
            "Restore the ledger DB connection pool to 200 connections (raised as CHG-0331).",
            "Add alerting on ledger DB pool saturation.",
            "Load test new fraud models with production-like traffic before rollout.",
        ]),
    ],
}

INC_2047 = {
    "filename": "INC-2047-incident-report.pdf",
    "title": "INC-2047 Incident Report - Delayed merchant payouts",
    "blocks": [
        ("h1", "INC-2047 Incident Report - Delayed merchant payouts"),
        ("kv", [("Date", "2026-03-19"), ("Severity", "SEV-2"), ("Status", "Resolved"),
                ("Duration", "2 h 45 min (00:30 to 03:15 UTC)")]),
        ("h2", "Summary"),
        ("p", "In the night of 2026-03-19 the nightly settlement-batch run was very slow and merchant payouts "
              "were delayed. The incident lasted 2 h 45 min, from 00:30 to 03:15 UTC. 1,200 merchants received "
              "their payouts late."),
        ("h2", "Timeline (UTC)"),
        ("ul", [
            "00:00 reconciliation-job starts as usual.",
            "00:30 settlement-batch starts at its new time (CHG-0327).",
            "00:50 settlement-batch throughput drops; lock wait alerts on the ledger DB.",
            "01:30 reconciliation-job finishes; settlement-batch speeds up but has a large backlog.",
            "03:15 settlement-batch completes; all payout files sent.",
        ]),
        ("h2", "Root cause"),
        ("p", "CHG-0327 moved settlement-batch from 02:00 to 00:30 UTC. At 00:30 reconciliation-job is still "
              "running (its window is 00:00 to 01:30 UTC). Both jobs write to the same ledger DB tables, so they "
              "competed for row locks. The row-lock contention made settlement-batch wait and retry for most of "
              "the overlap, and payouts were delayed."),
        ("h2", "Affected services"),
        ("ul", ["settlement-batch", "ledger-service", "reconciliation-job"]),
        ("h2", "Impact"),
        ("p", "1,200 merchants received their payouts late. Card authorizations were not affected."),
        ("h2", "Resolution"),
        ("p", "On 2026-03-20 the settlement-batch schedule was moved to 01:45 UTC, after reconciliation-job "
              "finishes. Later runs completed on time."),
    ],
}

INC_2052 = {
    "filename": "INC-2052-incident-report.pdf",
    "title": "INC-2052 Incident Report - Notification email delays",
    "blocks": [
        ("h1", "INC-2052 Incident Report - Notification email delays"),
        ("kv", [("Date", "2026-03-26"), ("Severity", "SEV-3"), ("Status", "Resolved"),
                ("Duration", "about 20 minutes (14:10 to 14:30 UTC)")]),
        ("h2", "Summary"),
        ("p", "On 2026-03-26 transaction notification emails from notification-service were delayed for about "
              "20 minutes. The cause was an outage at MailRelay, the external email provider used by "
              "notification-service."),
        ("h2", "Root cause"),
        ("p", "MailRelay returned errors for all send requests between 14:10 and 14:30 UTC. notification-service "
              "queued the messages and retried; all emails were delivered after MailRelay recovered. No internal "
              "change was involved."),
        ("h2", "Affected services"),
        ("ul", ["notification-service"]),
    ],
}

POSTMORTEM_2041 = {
    "filename": "PM-2041-postmortem.pdf",
    "title": "PM-2041 Postmortem - INC-2041 card authorization outage",
    "blocks": [
        ("h1", "PM-2041 Postmortem - INC-2041 card authorization outage"),
        ("kv", [("Date", "2026-03-12"), ("Incident", "INC-2041"), ("Written by", "Core Banking team"),
                ("Review status", "Reviewed in the weekly operations meeting")]),
        ("h2", "Summary"),
        ("p", "On 2026-03-05 card authorizations at Northwind Payments degraded for 3 h 40 min, from 09:40 to "
              "13:20 UTC. Authorization requests queued inside payments-gateway while waiting for database "
              "connections from ledger-service, and a large share of them timed out. This postmortem describes "
              "what happened, why it happened and what we are changing. It follows the blameless format: the "
              "goal is to improve the system, not to find a person at fault."),
        ("p", "The short version: the ledger DB connection pool was too small for normal peak traffic after "
              "CHG-0311 reduced it from 200 to 50 connections two days earlier. When the morning traffic peak "
              "arrived the pool ran out of free connections, requests waited, and the gateway gave up on them."),
        ("h2", "Impact"),
        ("p", "For 3 h 40 min a significant share of card authorization requests failed or were slow. Merchants "
              "using our card acceptance products saw declines that were not caused by the cardholder or by "
              "fraud rules. Retail merchants with high morning volume were hit hardest. Settlement, payouts and "
              "notifications were not affected. No financial data was lost or corrupted; every authorization that "
              "completed was recorded correctly in the ledger."),
        ("p", "Customer support received a large number of merchant contacts during the morning. Several large "
              "merchants asked for a written explanation, which this document and the incident report provide."),
        ("h2", "Timeline (all times UTC, 2026-03-05)"),
        ("ul", [
            "08:30 Morning traffic starts its usual climb as European retail opens.",
            "09:00 Scheduled deployment of fraud-scorer model v4 (CHG-0314) completes.",
            "09:40 First alerts: payments-gateway request timeouts above threshold. Incident opened.",
            "09:52 On-call engineer for payments-gateway joins; gateway pods look healthy, no errors in deploys.",
            "10:10 ledger-service dashboards show request queueing; database CPU is normal.",
            "10:30 Core Banking on-call confirms the ledger DB connection pool is at 50 of 50 connections in use.",
            "10:45 Discussion of raising the pool size; decided to wait for a config review because of CHG-0311.",
            "11:15 Incident raised to SEV-1; incident commander assigned.",
            "11:40 Gateway timeout rate stable but high; customer support starts merchant communication.",
            "12:20 Config review of the pool change starts; rollback of CHG-0311 prepared.",
            "13:05 fraud-scorer switched back to model v3 as a precaution while the pool rollback was being "
            "prepared.",
            "13:20 Connection pool usage drops below the limit, timeouts stop, incident resolved.",
            "15:00 Monitoring confirms normal behaviour; incident closed.",
        ]),
        ("h2", "Root cause"),
        ("p", "The root cause was CHG-0311, the reduction of the ledger DB connection pool from 200 to 50 "
              "connections on 2026-03-03. The change was planned as a cost reduction and was based on February "
              "monitoring data that showed a typical peak of about 40 open connections. That data used five-minute "
              "averages, which hide short bursts. Real peaks during the morning traffic ramp are much higher than "
              "the averaged numbers suggest."),
        ("p", "Every card authorization takes a ledger DB connection for the duration of the request. When the "
              "pool is exhausted, new requests wait in the ledger-service client queue. Waiting requests count "
              "against the payments-gateway timeout, so once the queue grew the gateway started to time out "
              "requests that would have succeeded with a free connection. Timed-out requests were often retried "
              "by merchant terminals, which added more load and kept the pool saturated."),
        ("p", "On 2026-03-03 and 2026-03-04 the traffic was lower than on 2026-03-05, which was the first busy "
              "weekday morning after the change. That explains why the problem appeared two days after the "
              "change rather than immediately."),
        ("h2", "Contributing factors"),
        ("ul", [
            "The capacity estimate for CHG-0311 used averaged metrics and did not look at peak concurrency.",
            "There was no alert on ledger DB pool saturation, so the first signal was gateway timeouts.",
            "The change was rated low risk, so it was not scheduled with extra monitoring.",
            "Merchant terminal retries amplified the load once timeouts began.",
            "fraud-scorer was not a contributing factor. Its model change happened the same morning, but the "
            "pool limit would have been reached by normal peak traffic regardless.",
        ]),
        ("h2", "Why the change looked safe"),
        ("p", "The change request for CHG-0311 was reviewed in the normal way and nobody objected. The numbers in "
              "the request were correct as averages: over February the pool rarely had more than about 40 "
              "connections open in any five-minute window. What the request did not show was the distribution "
              "inside those windows. During the morning ramp the number of connections in use rises and falls "
              "within seconds, and the short peaks are several times higher than the five-minute average."),
        ("p", "The rollback plan in the change request was sound and would have taken about ten minutes. The "
              "plan was not used during the incident because the team first wanted to confirm that the pool was "
              "the problem and not a symptom of something else. In hindsight, rolling back a recent capacity "
              "reduction is cheap and safe, and it should have been the first step."),
        ("h2", "Detection and response"),
        ("p", "Detection worked: the gateway timeout alert fired at 09:40, within minutes of the first failed "
              "authorizations. Diagnosis was slower. The gateway on-call engineer looked at the gateway first, "
              "found healthy pods and no recent gateway deployments, and then looked at downstream services one "
              "by one. The ledger-service dashboards showed queueing at 10:10, and the saturated pool was "
              "confirmed at 10:30. Because there was no alert on pool usage, this step depended on someone "
              "knowing where to look."),
        ("p", "Communication to merchants started at 11:40 through customer support. The incident channel had "
              "good participation once the incident was raised to SEV-1, but before that only two teams were "
              "involved. We will page all critical-path owners earlier in future incidents."),
        ("h2", "What went well"),
        ("ul", [
            "Alerting on gateway timeouts fired within minutes of the first failures.",
            "No authorization data was lost and the ledger stayed consistent throughout.",
            "Customer support had a holding statement for merchants within the first hour.",
            "The team that owns ledger-service identified the saturated pool quickly once involved.",
        ]),
        ("h2", "What went wrong"),
        ("ul", [
            "It took 50 minutes from the first alert to look at the ledger DB pool.",
            "The decision to raise the pool size was delayed by a config review.",
            "Ownership of the pool configuration was unclear between the gateway and ledger teams.",
        ]),
        ("h2", "Lessons learned"),
        ("p", "Capacity changes to shared resources such as database connection pools need to be checked against "
              "peak concurrency, not averages. The ledger DB is shared by the authorization path and by nightly "
              "jobs, so its pool is a critical shared resource and should be treated like one. A low-risk rating "
              "should not be given to a change that removes three quarters of the capacity of a shared resource."),
        ("p", "We also learned that our incident process should bring in the owners of every service on the "
              "critical path early. In this incident the ledger-service on-call joined almost an hour after the "
              "first alert. Paging all critical-path owners at SEV-2 and above would have saved time."),
        ("h2", "Action items"),
        ("ul", [
            "Restore the ledger DB connection pool to 200 connections (CHG-0331). Owner: Core Banking team.",
            "Add alerts on ledger DB pool saturation at 80% and 95% usage. Owner: Core Banking team.",
            "Require peak-concurrency data in change requests that reduce shared capacity. Owner: change board.",
            "Add model load testing with production-like traffic to the fraud model release checklist. Owner: "
            "model release process.",
            "Page all critical-path service owners for SEV-2 and above. Owner: incident management.",
        ]),
    ],
}

STATUS_PAGE = {
    "filename": "status-page-march-2026.html",
    "title": "Northwind Payments Status - March 2026 history",
    "blocks": [
        ("h1", "Northwind Payments Status - March 2026 history"),
        ("p", "Public status notices published during March 2026. Times are in UTC."),
        ("h2", "March 5, 2026 - Card payments degraded (INC-2041)"),
        ("p", "Investigating: some card payments are failing or slow. We are investigating."),
        ("p", "Resolved: card payments are working normally again. The disruption was caused by an outage at a "
              "third-party card network. Total duration was about 2 hours. We apologise for the inconvenience."),
        ("h2", "March 19, 2026 - Delayed payouts (INC-2047)"),
        ("p", "Some merchants are experiencing delayed payouts this morning. Payouts are being processed and "
              "will arrive later today."),
        ("p", "Resolved: all delayed payouts have been sent."),
        ("h2", "March 26, 2026 - Email delays (INC-2052)"),
        ("p", "Transaction notification emails are delayed. Messages are queued and will be delivered."),
        ("p", "Resolved: all queued emails have been delivered."),
    ],
}

FINANCE_SUMMARY = {
    "filename": "finance-summary-march-2026.html",
    "title": "Finance Summary - Incidents, March 2026",
    "blocks": [
        ("h1", "Finance Summary - Incidents, March 2026"),
        ("p", "Prepared by Finance on 2026-03-31 for the monthly management report. The table lists the "
              "operational incidents of the month with their merchant and financial impact as known at the time "
              "of writing."),
        ("table", [
            ["Incident", "Date", "Description", "Merchants affected", "Financial impact"],
            ["INC-2041", "2026-03-05", "Card authorization failures", "not yet quantified",
             "Cost impact under review"],
            ["INC-2047", "2026-03-19", "Delayed merchant payouts", "4,500", "Late-payout credits being assessed"],
            ["INC-2052", "2026-03-26", "Notification email delays", "none", "No financial impact"],
        ]),
        ("h2", "Notes"),
        ("p", "INC-2047: 4,500 merchants had payouts delayed. Treasury is reviewing whether late-payout credits "
              "apply under merchant contracts."),
        ("p", "INC-2041: cost impact under review. Final figures will be reported once merchant claims are "
              "assessed."),
    ],
}

SERVICE_CATALOG = {
    "filename": "service-catalog.html",
    "title": "Service Catalog - Northwind Payments",
    "blocks": [
        ("h1", "Service Catalog - Northwind Payments"),
        ("p", "Last updated 2026-03-01. One row per production service with its owning team and a short "
              "description. Contact the owning team for questions about a service."),
        ("table", [
            ["Service", "Owner", "Description"],
            ["payments-gateway", "Payments Core team", "Entry point for card authorizations from merchants and "
             "acquirers."],
            ["fraud-scorer", "Risk Engineering", "Scores each card authorization for fraud risk."],
            ["ledger-service", "Core Banking team", "Records authorization holds and balances in the ledger DB."],
            ["settlement-batch", "Treasury Engineering", "Nightly job that calculates and sends merchant payouts."],
            ["reconciliation-job", "Finance Ops Engineering", "Nightly job that reconciles the ledger with bank "
             "statements; runs 00:00 to 01:30 UTC."],
            ["notification-service", "Customer Comms team", "Sends transaction emails and SMS through the "
             "external provider MailRelay."],
            ["auth-service", "Identity team", "Authenticates merchant users of the dashboard and API."],
        ]),
    ],
}

FRAUD_RUNBOOK = {
    "filename": "fraud-scorer-runbook.md",
    "title": "fraud-scorer Runbook",
    "blocks": [
        ("h1", "fraud-scorer Runbook"),
        ("kv", [("Last updated", "2026-02-20"), ("Owner", "ML Platform team"),
                ("On-call", "ml-platform-oncall rotation (24/7)")]),
        ("h2", "Service overview"),
        ("p", "fraud-scorer receives one scoring request per card authorization and returns a risk score and a "
              "decision hint. It loads one active model version at a time; older versions stay available for "
              "fast rollback."),
        ("h2", "Service level objective"),
        ("p", "Latency SLO: p99 scoring latency below 150 ms, measured at the service. Availability SLO: 99.95% "
              "of requests answered."),
        ("h2", "Alerts"),
        ("ul", [
            "FraudScorerLatencyHigh: p99 above 150 ms for 5 minutes.",
            "FraudScorerErrorRate: more than 1% errors for 5 minutes.",
        ]),
        ("h2", "How to roll back a model version"),
        ("ul", [
            "Check the currently active version on the fraud-scorer admin page.",
            "Run the model alias switch command with the previous version, for example v3.",
            "Watch the latency and score distribution dashboards for 15 minutes.",
            "Record the rollback in the incident channel and open a ticket for the model team.",
        ]),
        ("h2", "Escalation"),
        ("p", "If a rollback does not restore latency, page the ML Platform team lead."),
    ],
}

ARCHITECTURE = {
    "filename": "payments-architecture.md",
    "title": "Payments Platform Architecture",
    "blocks": [
        ("h1", "Payments Platform Architecture"),
        ("p", "Version 3, 2026-02-15. This document describes how a card authorization flows through the "
              "Northwind Payments platform, how the services depend on each other, and how the nightly batch "
              "jobs use the shared ledger database. It is meant for engineers joining the platform teams and for "
              "anyone reviewing a change that touches the authorization path."),
        ("h2", "Overview"),
        ("p", "Northwind Payments processes card payments for merchants. The platform has two kinds of workload. "
              "The online workload is the card authorization path: a merchant terminal or e-commerce checkout "
              "sends an authorization request and expects an answer in about a second. The offline workload is "
              "a set of nightly jobs that reconcile the ledger with bank statements and pay merchants. Both "
              "workloads use the same ledger database, which is why changes to the database or to the job "
              "schedule need care."),
        ("p", "The main services are payments-gateway, fraud-scorer, ledger-service and notification-service on "
              "the online side, and reconciliation-job and settlement-batch on the offline side. auth-service "
              "handles logins to the merchant dashboard and API and is not on the authorization path."),
        ("h2", "Authorization flow"),
        ("p", "A card authorization request enters through payments-gateway. The gateway validates the request, "
              "opens a ledger-service session for the request, and then performs the following steps in order."),
        ("ul", [
            "payments-gateway calls fraud-scorer synchronously and waits for the risk score.",
            "If the score is acceptable, payments-gateway asks ledger-service to write an authorization hold. "
            "ledger-service writes the hold through its connection pool to the ledger DB.",
            "payments-gateway returns the approval or decline to the merchant.",
            "notification-service is informed asynchronously and sends a transaction email or SMS if the "
            "merchant has enabled notifications.",
        ]),
        ("p", "The ledger-service session, and the ledger DB connection behind it, is held from the moment the "
              "request is accepted until the response is sent. This keeps the hold write and the balance check in "
              "one transaction, but it also means that any slow step in the middle of the flow keeps a database "
              "connection busy for longer."),
        ("p", "The fraud-scorer call is synchronous because the decision must be known before the hold is written. "
              "There is no asynchronous fallback: if fraud-scorer is slow, every authorization is slow."),
        ("h2", "Timeouts"),
        ("p", "payments-gateway has an end-to-end timeout of 1,200 ms per authorization request. If the full flow "
              "does not complete within 1,200 ms, the gateway returns a timeout response to the merchant, and the "
              "merchant terminal may retry. The fraud-scorer call has no separate shorter timeout; it is bounded "
              "only by the end-to-end gateway timeout. Time spent waiting for a free ledger DB connection also "
              "counts against the 1,200 ms budget."),
        ("p", "Under normal conditions the fraud-scorer call takes well under 100 ms and the ledger write about "
              "20 ms, so the typical authorization completes in 150 to 250 ms, leaving plenty of headroom."),
        ("h2", "Ledger database and connection pool"),
        ("p", "The ledger DB is a PostgreSQL database owned through ledger-service. Only ledger-service and the "
              "two nightly jobs connect to it directly. ledger-service uses a connection pool with a configurable "
              "maximum size. When all connections in the pool are in use, new requests wait in the client queue "
              "until a connection is released or the caller gives up."),
        ("p", "The number of connections needed at any time is roughly the request rate multiplied by the time "
              "each request holds a connection. Because the connection is held for the whole authorization, the "
              "hold time is close to the end-to-end request latency. Doubling the latency of any step on the path "
              "therefore roughly doubles the number of connections needed at the same traffic level."),
        ("p", "Sizing guidance: the pool must be sized for peak concurrency during the morning traffic ramp, not "
              "for average usage. Short bursts are not visible in five-minute averages."),
        ("h2", "Nightly jobs"),
        ("p", "Two batch jobs run every night and both write to the ledger DB."),
        ("ul", [
            "reconciliation-job runs from 00:00 to 01:30 UTC. It compares ledger entries with bank statement "
            "files and writes reconciliation markers to ledger rows.",
            "settlement-batch starts at 02:00 UTC. It calculates merchant payouts from settled ledger rows, "
            "marks those rows as paid out and produces payout files for the banking partner.",
        ]),
        ("p", "The two jobs update overlapping sets of ledger rows. They are scheduled one after the other on "
              "purpose: running them at the same time would make them compete for row locks on the same tables. "
              "Any change to either schedule must keep the jobs from overlapping."),
        ("h2", "Dependencies and failure modes"),
        ("ul", [
            "fraud-scorer slow: authorizations slow down end to end, and ledger connections are held longer.",
            "ledger DB pool exhausted: requests wait for connections and may hit the gateway timeout.",
            "notification-service or its email provider down: notifications are queued and retried; "
            "authorizations are not affected.",
            "nightly jobs overlapping: row-lock contention in the ledger DB slows both jobs.",
        ]),
        ("h2", "Deployment and scaling"),
        ("p", "The online services run as containers behind internal load balancers. payments-gateway and "
              "fraud-scorer scale horizontally with traffic; adding gateway instances does not add ledger DB "
              "capacity, because every gateway instance shares the same ledger-service pool. ledger-service runs "
              "a small fixed number of instances, and the total number of ledger DB connections is the pool size "
              "configured in ledger-service. The ledger DB itself is a single primary with a standby replica; the "
              "replica is used for reporting queries only and never for authorization traffic."),
        ("p", "fraud-scorer loads its active model into memory at start-up. A new model version is activated by "
              "switching a model alias, which lets the service move between versions without a redeploy. Larger "
              "models need more CPU per request, so scoring latency depends on the model as well as on traffic."),
        ("h2", "Observability"),
        ("p", "Each service exports request rate, error rate and latency percentiles. payments-gateway also "
              "exports the timeout rate per merchant. ledger-service exports the number of connections in use and "
              "the length of the client queue. The batch jobs report start time, end time and rows processed."),
        ("h2", "Change guidelines"),
        ("p", "Changes on the authorization path should be rolled out gradually where possible and watched on the "
              "gateway latency and timeout dashboards. Changes to the ledger DB pool or to the nightly schedule "
              "should be reviewed against the sizing guidance and the job ordering described above."),
    ],
}

OPS_REVIEW = {
    "filename": "ops-review-march-2026.pdf",
    "title": "Operations Review - March 2026",
    "blocks": [
        ("h1", "Operations Review - March 2026"),
        ("kv", [("Date", "2026-03-31"), ("Prepared for", "Monthly operations meeting")]),
        ("h2", "Summary"),
        ("p", "March 2026 had 5 production changes and 3 incidents. Two incidents are linked to changes made "
              "during the month; one was caused by an external provider."),
        ("h2", "Changes"),
        ("ul", [
            "CHG-0311 (2026-03-03) ledger-service connection pool reduced.",
            "CHG-0314 (2026-03-05) fraud-scorer model v4.",
            "CHG-0320 (2026-03-10) notification-service TLS certificate rotation. No customer impact.",
            "CHG-0327 (2026-03-18) settlement-batch schedule change.",
            "CHG-0331 (2026-03-24) ledger-service connection pool restored.",
        ]),
        ("h2", "Incidents"),
        ("ul", [
            "INC-2041 (2026-03-05) card authorization failures. Linked to CHG-0314 and CHG-0311.",
            "INC-2047 (2026-03-19) delayed merchant payouts. Linked to CHG-0327.",
            "INC-2052 (2026-03-26) notification email delays. External: provider outage, not linked to any "
            "change.",
        ]),
        ("h2", "Follow-up"),
        ("p", "Action items from INC-2041 and INC-2047 are tracked in the incident reports. The change board will "
              "review how risk ratings are assigned to capacity changes."),
    ],
}

DOCUMENTS = [CHANGELOG, CHG_0311, CHG_0314, CHG_0320, CHG_0327, CHG_0331, INC_2041, INC_2047, INC_2052,
             POSTMORTEM_2041, STATUS_PAGE, FINANCE_SUMMARY, SERVICE_CATALOG, FRAUD_RUNBOOK, ARCHITECTURE, OPS_REVIEW]
