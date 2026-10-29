# Payments Platform Architecture

Version 3, 2026-02-15. This document describes how a card authorization flows through the Northwind Payments platform, how the services depend on each other, and how the nightly batch jobs use the shared ledger database. It is meant for engineers joining the platform teams and for anyone reviewing a change that touches the authorization path.

## Overview

Northwind Payments processes card payments for merchants. The platform has two kinds of workload. The online workload is the card authorization path: a merchant terminal or e-commerce checkout sends an authorization request and expects an answer in about a second. The offline workload is a set of nightly jobs that reconcile the ledger with bank statements and pay merchants. Both workloads use the same ledger database, which is why changes to the database or to the job schedule need care.

The main services are payments-gateway, fraud-scorer, ledger-service and notification-service on the online side, and reconciliation-job and settlement-batch on the offline side. auth-service handles logins to the merchant dashboard and API and is not on the authorization path.

## Authorization flow

A card authorization request enters through payments-gateway. The gateway validates the request, opens a ledger-service session for the request, and then performs the following steps in order.

- payments-gateway calls fraud-scorer synchronously and waits for the risk score.
- If the score is acceptable, payments-gateway asks ledger-service to write an authorization hold. ledger-service writes the hold through its connection pool to the ledger DB.
- payments-gateway returns the approval or decline to the merchant.
- notification-service is informed asynchronously and sends a transaction email or SMS if the merchant has enabled notifications.

The ledger-service session, and the ledger DB connection behind it, is held from the moment the request is accepted until the response is sent. This keeps the hold write and the balance check in one transaction, but it also means that any slow step in the middle of the flow keeps a database connection busy for longer.

The fraud-scorer call is synchronous because the decision must be known before the hold is written. There is no asynchronous fallback: if fraud-scorer is slow, every authorization is slow.

## Timeouts

payments-gateway has an end-to-end timeout of 1,200 ms per authorization request. If the full flow does not complete within 1,200 ms, the gateway returns a timeout response to the merchant, and the merchant terminal may retry. The fraud-scorer call has no separate shorter timeout; it is bounded only by the end-to-end gateway timeout. Time spent waiting for a free ledger DB connection also counts against the 1,200 ms budget.

Under normal conditions the fraud-scorer call takes well under 100 ms and the ledger write about 20 ms, so the typical authorization completes in 150 to 250 ms, leaving plenty of headroom.

## Ledger database and connection pool

The ledger DB is a PostgreSQL database owned through ledger-service. Only ledger-service and the two nightly jobs connect to it directly. ledger-service uses a connection pool with a configurable maximum size. When all connections in the pool are in use, new requests wait in the client queue until a connection is released or the caller gives up.

The number of connections needed at any time is roughly the request rate multiplied by the time each request holds a connection. Because the connection is held for the whole authorization, the hold time is close to the end-to-end request latency. Doubling the latency of any step on the path therefore roughly doubles the number of connections needed at the same traffic level.

Sizing guidance: the pool must be sized for peak concurrency during the morning traffic ramp, not for average usage. Short bursts are not visible in five-minute averages.

## Nightly jobs

Two batch jobs run every night and both write to the ledger DB.

- reconciliation-job runs from 00:00 to 01:30 UTC. It compares ledger entries with bank statement files and writes reconciliation markers to ledger rows.
- settlement-batch starts at 02:00 UTC. It calculates merchant payouts from settled ledger rows, marks those rows as paid out and produces payout files for the banking partner.

The two jobs update overlapping sets of ledger rows. They are scheduled one after the other on purpose: running them at the same time would make them compete for row locks on the same tables. Any change to either schedule must keep the jobs from overlapping.

## Dependencies and failure modes

- fraud-scorer slow: authorizations slow down end to end, and ledger connections are held longer.
- ledger DB pool exhausted: requests wait for connections and may hit the gateway timeout.
- notification-service or its email provider down: notifications are queued and retried; authorizations are not affected.
- nightly jobs overlapping: row-lock contention in the ledger DB slows both jobs.

## Deployment and scaling

The online services run as containers behind internal load balancers. payments-gateway and fraud-scorer scale horizontally with traffic; adding gateway instances does not add ledger DB capacity, because every gateway instance shares the same ledger-service pool. ledger-service runs a small fixed number of instances, and the total number of ledger DB connections is the pool size configured in ledger-service. The ledger DB itself is a single primary with a standby replica; the replica is used for reporting queries only and never for authorization traffic.

fraud-scorer loads its active model into memory at start-up. A new model version is activated by switching a model alias, which lets the service move between versions without a redeploy. Larger models need more CPU per request, so scoring latency depends on the model as well as on traffic.

## Observability

Each service exports request rate, error rate and latency percentiles. payments-gateway also exports the timeout rate per merchant. ledger-service exports the number of connections in use and the length of the client queue. The batch jobs report start time, end time and rows processed.

## Change guidelines

Changes on the authorization path should be rolled out gradually where possible and watched on the gateway latency and timeout dashboards. Changes to the ledger DB pool or to the nightly schedule should be reviewed against the sizing guidance and the job ordering described above.
