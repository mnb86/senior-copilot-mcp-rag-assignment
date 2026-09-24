---
doc_id: TG-MTR-005
title: Electric Motor Trip Troubleshooting Guide
doc_type: troubleshooting_guide
revision: "2.3"
effective_date: 2025-12-05
owner: NorthPlant Electrical Maintenance
site: NorthPlant
asset_types: [motor, electrical]
asset_ids: [AST-MTR-501, AST-MTR-502, AST-MTR-503, AST-MCC-501, AST-MTR-101]
alarm_names: [Motor Trip, Bus Undervoltage, Overcurrent, High Winding Temperature, Ground Fault, Phase Imbalance, Motor Overload]
---

# Electric Motor Trip Troubleshooting Guide

## 1. Scope

Applies to low-voltage and medium-voltage induction motors in NorthPlant, including the Unit 5 motors
fed from Motor Control Center MCC-501 (Cooling Water Pump Motor 501, Conveyor Drive Motor 502 and
ID Fan Motor 503).

## 2. Related Assets to Inspect After a Motor Trip

When a motor trips, inspect the following related assets before any restart:

1. **The upstream motor control center or switchgear.** Check bus voltage history, incomer breaker status
   and protection relay events. When several motors on the same MCC trip within a few minutes, a bus
   undervoltage on the MCC is the most likely common cause.
2. **The protection relay** of the tripped motor: record the first-out (overcurrent, thermal overload,
   earth fault, undervoltage).
3. **The driven equipment** (pump, fan, conveyor): check for mechanical seizure, blockage or overload.
4. **The motor itself**: winding temperature history, cooling fan, terminal box.

## 3. Diagnosis by Trip Cause

| First-out | Likely cause | Action |
| --- | --- | --- |
| Undervoltage | Supply dip at MCC / transformer | Check MCC bus voltage and upstream supply before restart |
| Overcurrent | Mechanical overload of driven equipment | Inspect driven equipment; check for jams |
| Thermal overload / high winding temperature | Cooling loss or sustained overload | Allow cool-down; check cooling fan |
| Earth (ground) fault | Insulation failure | Do not restart. Megger test the motor and cable |

## 4. Restart Rules

- Do not attempt more than two restarts within one hour; allow the motor to cool between attempts.
- Never restart a motor that tripped on earth fault until an insulation resistance test has passed.
- If the trip was caused by an upstream undervoltage, confirm the MCC bus voltage has recovered and is
  stable before restarting.
