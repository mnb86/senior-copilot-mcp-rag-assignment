---
doc_id: SOP-CMP-004
title: Recycle Gas Compressor K-301 Operating Procedure
doc_type: operating_procedure
revision: "5.0"
effective_date: 2025-09-01
owner: EastRefinery Operations
site: EastRefinery
asset_types: [compressor]
asset_ids: [AST-K-301, AST-E-301, AST-FV-301]
alarm_names: [High Discharge Pressure, High Discharge Temperature, Surge Detected, High Vibration]
---

# Recycle Gas Compressor K-301 Operating Procedure

## 1. Normal Operation

K-301 circulates hydrogen-rich recycle gas through the HCU-2 reactor loop. Discharge gas is cooled in the
air cooler E-301. The anti-surge valve FV-301 protects the machine at low flow.

## 2. Alarm Response Summary

| Alarm | First response |
| --- | --- |
| High Discharge Pressure (PT-3012.HI, 168 bar(g)) | Check E-301 outlet temperature and fans; verify FV-301 position; reduce load if pressure keeps rising |
| High Discharge Temperature (TT-3013.HI) | Check E-301 performance and ambient temperature |
| Surge Detected | Confirm anti-surge controller in AUTO; do not reduce flow further |
| High Vibration | Check for surge, liquid carry-over, and compare with thrust bearing temperature |

## 3. High Discharge Pressure

The trip setting is 175 bar(g). When the alarm is active for more than 15 minutes, notify the shift
supervisor and the process engineer. Load reduction must stay within the operating envelope shown on the
compressor map. The reactor loop pressure controller must not be switched to manual without supervisor
approval.

## 4. Restart After Trip

A restart of K-301 after a trip requires a completed pre-start checklist, confirmation of seal gas
supply, and supervisor authorisation in line with SI-GEN-001.
