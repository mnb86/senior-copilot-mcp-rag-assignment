---
doc_id: SOP-BFP-001
title: Boiler Feed Pump Operation and Alarm Response Procedure
doc_type: operating_procedure
revision: "4.2"
effective_date: 2026-01-15
owner: NorthPlant Operations
site: NorthPlant
asset_types: [pump]
asset_ids: [AST-BFP-101, AST-BFP-102]
alarm_names: [Low Suction Pressure, Pump Trip, High Vibration, High Bearing Temperature, High Discharge Pressure, Seal Leak Detected]
---

# Boiler Feed Pump Operation and Alarm Response Procedure

## 1. Purpose and Scope

This procedure defines the operator response to alarms raised on Boiler Feed Pumps BFP-101 and BFP-102
in NorthPlant Unit 1. BFP-101 is normally the duty pump and BFP-102 the standby pump. Both pumps take
suction from Deaerator 101 and are lubricated from the lube oil console LOS-101. The procedure applies to
control room operators and field operators, and to shift supervisors who authorise pump restarts.

## 2. Operating Limits

| Parameter | Alarm | Trip |
| --- | --- | --- |
| Suction pressure | 3.5 bar(g) low | 2.8 bar(g) low |
| Bearing temperature | 85 degC high | 95 degC high |
| Vibration (overall velocity) | 7.1 mm/s | 11.0 mm/s |
| Discharge pressure | 182 bar(g) high | 190 bar(g) high |
| Deaerator level (suction source) | 40 % low | 25 % low-low |

## 3. Low Suction Pressure Alarm (BFP PT-001.LO)

Low suction pressure indicates a risk of cavitation. The most common causes, in order of frequency, are:
low Deaerator 101 level, a partially blocked suction strainer, low deaerator pressure after a load
change, and vapour formation caused by high feedwater temperature.

Immediate actions:

1. Check Deaerator 101 level and pressure on the DCS overview. If deaerator level is below 40 %, follow
   SOP-DEA-002 to restore level before taking any other action on the pump.
2. Check the suction strainer differential pressure. A differential pressure above 0.5 bar indicates a
   fouled strainer; request a strainer changeover.
3. Verify that the minimum-flow recirculation valve FCV-103 is open when pump flow is low.
4. If suction pressure continues to fall towards 2.8 bar(g), start the standby pump BFP-102 and reduce
   load on BFP-101 in coordination with the shift supervisor.

## 4. Pump Trip Response

When a boiler feed pump trips, the standby pump starts automatically on low header pressure. The operator
must confirm that the standby pump is running and that feedwater header pressure has recovered.

Restart restrictions:

- Do not restart the pump after a low suction pressure trip until deaerator level has been restored
  above 40 % and the suction strainer differential pressure has been checked.
- Do not reset the trip until the first-out indication has been recorded in the shift log.
- A restart after any trip requires authorisation from the shift supervisor (see SI-GEN-001).
- Never attempt more than two consecutive restarts of the same pump within one hour.

Rationale: restarting a pump into a low-suction condition causes cavitation damage to the first-stage
impeller within minutes and can escalate to a seal failure.

## 5. High Bearing Temperature Alarm (TT-010.HI)

1. Check lube oil header pressure at LOS-101. Low lube oil pressure is the most frequent precursor of a
   bearing temperature alarm on BFP-101.
2. Check the lube oil cooler outlet temperature; the normal range is 40-50 degC.
3. Increase monitoring of bearing temperature to every 15 minutes and trend it on the DCS.
4. If bearing temperature reaches 95 degC, or rises by more than 5 degC in 10 minutes, transfer load to
   the standby pump and stop the affected pump.

## 6. High Vibration Alarm (VT-020.HI)

1. Compare the vibration reading with the standby pump and with the previous 24-hour trend.
2. Check for process causes: low suction pressure (cavitation), operation below minimum flow, or a
   recent change in feedwater demand.
3. If vibration exceeds 11.0 mm/s, transfer load to the standby pump and stop the pump. Request a
   vibration spectrum analysis from reliability engineering (see MM-BFP-010).

## 7. Recurring Alarms

If the same alarm occurs on a boiler feed pump more than three times in 24 hours, the shift supervisor
must raise a reliability investigation. Recurring low suction pressure alarms are almost always caused
by an upstream deaerator level control problem rather than a pump defect; the investigation must review
Deaerator 101 level control performance and the level control valve.

## 8. Records

Record all alarm responses, trips, restarts and authorisations in the shift log with the alarm tag,
time, first-out indication and actions taken.
