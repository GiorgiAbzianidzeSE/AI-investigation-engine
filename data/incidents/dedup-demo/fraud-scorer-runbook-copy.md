# fraud-scorer Runbook

Last updated: 2026-02-20  
Owner: ML Platform team  
On-call: ml-platform-oncall rotation (24/7)  

## Service overview

fraud-scorer receives one scoring request per card authorization and returns a risk score and a decision hint. It loads one active model version at a time; older versions stay available for fast rollback.

## Service level objective

Latency SLO: p99 scoring latency below 150 ms, measured at the service. Availability SLO: 99.95% of requests answered.

## Alerts

- FraudScorerLatencyHigh: p99 above 150 ms for 5 minutes.
- FraudScorerErrorRate: more than 1% errors for 5 minutes.

## How to roll back a model version

- Check the currently active version on the fraud-scorer admin page.
- Run the model alias switch command with the previous version, for example v3.
- Watch the latency and score distribution dashboards for 15 minutes.
- Record the rollback in the incident channel and open a ticket for the model team.

## Escalation

If a rollback does not restore latency, page the ML Platform team lead.
