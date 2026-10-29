# Production Changelog - March 2026

Northwind Payments platform engineering. Period covered: 2026-03-01 to 2026-03-31. This log lists every production change that went through the change process during the month. Each entry gives the date, the service, a short summary and the requesting team. Approval records are kept on the individual change request forms, not in this log.

## CHG-0311 - ledger-service connection pool resize

Date: 2026-03-03  
Service: ledger-service  
Requested by: Core Banking team  

Reduced the maximum size of the ledger DB connection pool from 200 to 50 connections. The goal is cost reduction: with fewer connections the database instance can be moved to a smaller size.

## CHG-0314 - fraud-scorer model v4 rollout

Date: 2026-03-05, 09:00 UTC  
Service: fraud-scorer  
Requested by: Risk Engineering  

Rolled out version 4 of the card fraud model to all production traffic. Version 4 uses a larger feature set for card-not-present transactions.

## CHG-0320 - notification-service TLS certificate rotation

Date: 2026-03-10  
Service: notification-service  
Requested by: Customer Comms team  

Rotated the TLS certificates used by notification-service for its outbound provider connection and its webhook endpoint. Routine rotation ahead of certificate expiry.

## CHG-0327 - settlement-batch schedule change

Date: 2026-03-18  
Service: settlement-batch  
Requested by: Treasury Engineering  

Moved the nightly settlement-batch start time from 02:00 UTC to 00:30 UTC so that EU merchants receive their payouts earlier in the morning.

## CHG-0331 - ledger-service connection pool restored

Date: 2026-03-24  
Service: ledger-service  
Requested by: Core Banking team  

Raised the maximum size of the ledger DB connection pool from 50 back to 200 connections. This reverts CHG-0311.
