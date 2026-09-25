---
doc_id: SOP-DEA-002
title: Deaerator Level Control and Low Level Response
doc_type: operating_procedure
revision: "2.0"
effective_date: 2025-11-01
owner: NorthPlant Operations
site: NorthPlant
asset_types: [vessel, pump]
asset_ids: [AST-DEA-101, AST-BFP-101, AST-BFP-102]
alarm_names: [Deaerator Low Level, Deaerator High Pressure, Low Suction Pressure]
---

# Deaerator Level Control and Low Level Response

## 1. Purpose

Deaerator 101 provides the suction head for Boiler Feed Pumps BFP-101 and BFP-102. Loss of deaerator
level is the leading cause of low suction pressure alarms and boiler feed pump trips in Unit 1. This
procedure describes the response to a Deaerator Low Level alarm (LT-001.LO, 40 %).

## 2. Low Level Alarm Response

1. Confirm the level reading against the local gauge glass and the redundant transmitter LT-001B.
2. Check the condensate make-up flow and the position of the deaerator level control valve. If the valve
   is fully open and level is still falling, place the valve in manual and verify the valve responds.
3. Check condensate extraction pump discharge pressure and that the condensate polisher bypass is
   correctly lined up.
4. Reduce unit load if level continues to fall below 30 %, to reduce feedwater demand.
5. Inform the boiler feed pump operator: a falling deaerator level will cause low suction pressure on
   the running boiler feed pump within 2 to 10 minutes.

## 3. Relationship to Boiler Feed Pump Alarms

Historical analysis shows that most Low Suction Pressure alarms on BFP-101 follow a Deaerator Low Level
alarm by a few minutes. When low suction pressure alarms recur, treat the deaerator level control loop
as the primary suspect: check level controller tuning, the make-up valve stroke, and the condensate
supply before requesting pump maintenance.

## 4. Returning to Normal

Level must be stable above 40 % for at least 10 minutes before any boiler feed pump that tripped on low
suction pressure is restarted (see SOP-BFP-001 section 4).
