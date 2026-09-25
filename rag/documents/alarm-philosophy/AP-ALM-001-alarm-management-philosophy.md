---
doc_id: AP-ALM-001
title: Alarm Management Philosophy
doc_type: alarm_philosophy
revision: "3.0"
effective_date: 2025-04-01
owner: Corporate Process Safety
site: ALL
asset_types: [all]
asset_ids: []
alarm_names: []
---

# Alarm Management Philosophy

## 1. Principles

Every alarm must indicate an abnormal condition that requires a timely operator action. Alarms follow the
lifecycle of ISA-18.2 / IEC 62682: philosophy, identification, rationalization, design, implementation,
operation, maintenance, monitoring and assessment, and management of change.

## 2. Priority Assignment

Alarm priority is based on the severity of the consequence if no action is taken and the time available
to respond.

| Priority | Consequence | Response time |
| --- | --- | --- |
| P1 (critical) | Safety, environmental or major equipment damage | Immediate, under 3 minutes |
| P2 (high) | Significant production loss or equipment damage | Under 10 minutes |
| P3 (medium) | Minor production or efficiency impact | Under 30 minutes |
| P4 (low) | Advisory | Next routine check |

Alarms on high-criticality assets and safety-related alarms should be investigated first when several
alarms are active at the same time.

## 3. Performance Targets

- Average alarm rate per operator position below 6 per hour; flood defined as 10 or more alarms in
  10 minutes; less than 1 % of time in flood.
- Chattering alarms (repeating within one minute) and stale alarms (standing for more than 24 hours) are
  rationalization candidates and must be reviewed monthly.
- Acknowledgement targets: critical within 2 minutes, high within 5 minutes.

## 4. Recurring Alarms

An alarm that repeatedly occurs on the same asset is a symptom, not a root cause. The investigation must
review correlated alarms on related upstream and supporting assets, because the initiating event is often
on a different asset from the one raising the alarm.

## 5. Shelving and Suppression

Shelving requires supervisor approval and must be time-limited. Safety alarms (P1) must never be shelved
without a documented risk assessment. Suppression by design (for example state-based suppression during
start-up) must be defined in the alarm rationalization database.

## 6. Use of Decision Support Tools

Recommendations produced by analytics or decision-support systems are advisory. Where a recommendation
conflicts with an approved operating procedure, the operating procedure takes precedence and the
conflict must be reported to the process engineer.
