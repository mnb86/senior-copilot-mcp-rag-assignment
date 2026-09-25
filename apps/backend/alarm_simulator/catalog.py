"""Static asset and alarm-definition catalog for the Alarm Management API simulator.

The catalog is intentionally rich enough to exercise every endpoint in the Postman
contract (sites, units, related assets, correlated alarm chains, chattering alarms,
flood bursts and one asset with a persistent downstream fault).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Effect:
    """A causal link: when the parent alarm fires, ``alarm_name`` on ``asset_id`` may follow."""

    asset_id: str
    alarm_name: str
    probability: float
    lag_minutes: tuple[int, int]


@dataclass(frozen=True)
class AlarmDef:
    name: str
    code: str
    alarm_type: str  # process | safety | device | system
    severity: str  # low | medium | high | critical
    rate_per_day: float
    uom: str
    limit: float
    direction: str  # high | low | state
    chatter: bool = False
    recent_multiplier: float = 1.0  # rate multiplier applied to the most recent 90 days
    effects: tuple[Effect, ...] = ()


@dataclass(frozen=True)
class Asset:
    asset_id: str
    asset_name: str
    asset_type: str
    site: str
    unit: str
    criticality: str
    manufacturer: str
    model: str
    install_date: str
    description: str
    tag_prefix: str
    related: tuple[tuple[str, str], ...] = ()  # (asset_id, relationship)
    alarms: tuple[AlarmDef, ...] = ()
    operating_limits: dict[str, str] = field(default_factory=dict)
    standby_asset_id: str | None = None
    sim_fault: str | None = None


def _e(asset_id: str, name: str, p: float, lo: int, hi: int) -> Effect:
    return Effect(asset_id, name, p, (lo, hi))


ASSETS: tuple[Asset, ...] = (
    # ------------------------------------------------------------------ NorthPlant / Unit 1
    Asset(
        "AST-BFP-101",
        "Boiler Feed Pump 101",
        "pump",
        "NorthPlant",
        "Unit 1",
        "high",
        "Flowserve",
        "HDX 150-8",
        "2014-03-12",
        "Multistage centrifugal boiler feed pump, duty unit for HP feedwater header.",
        "BFP101",
        related=(
            ("AST-BFP-102", "standby_redundant"),
            ("AST-DEA-101", "upstream_suction_source"),
            ("AST-MTR-101", "driver"),
            ("AST-LOS-101", "lube_oil_supply"),
            ("AST-FCV-103", "minimum_flow_recirculation"),
        ),
        alarms=(
            AlarmDef(
                "Low Suction Pressure",
                "PT-001.LO",
                "process",
                "high",
                0.07,
                "bar(g)",
                3.5,
                "low",
                recent_multiplier=2.4,
                effects=(_e("AST-BFP-101", "Pump Trip", 0.22, 2, 8),),
            ),
            AlarmDef("High Discharge Pressure", "PT-002.HI", "process", "medium", 0.04, "bar(g)", 182.0, "high"),
            AlarmDef(
                "High Bearing Temperature",
                "TT-010.HI",
                "device",
                "high",
                0.03,
                "degC",
                85.0,
                "high",
                recent_multiplier=1.6,
            ),
            AlarmDef("High Vibration", "VT-020.HI", "device", "high", 0.03, "mm/s", 7.1, "high"),
            AlarmDef("Pump Trip", "XS-099.TRIP", "safety", "critical", 0.005, "state", 1.0, "state"),
            AlarmDef("Seal Leak Detected", "LS-030.HI", "device", "medium", 0.02, "state", 1.0, "state"),
        ),
        operating_limits={
            "suction_pressure_min": "3.5 bar(g)",
            "bearing_temp_trip": "95 degC",
            "vibration_alarm": "7.1 mm/s",
            "vibration_trip": "11.0 mm/s",
        },
        standby_asset_id="AST-BFP-102",
    ),
    Asset(
        "AST-BFP-102",
        "Boiler Feed Pump 102",
        "pump",
        "NorthPlant",
        "Unit 1",
        "high",
        "Flowserve",
        "HDX 150-8",
        "2014-03-12",
        "Multistage centrifugal boiler feed pump, standby unit for HP feedwater header.",
        "BFP102",
        related=(
            ("AST-BFP-101", "standby_redundant"),
            ("AST-DEA-101", "upstream_suction_source"),
            ("AST-LOS-101", "shared_lube_oil_header"),
        ),
        alarms=(
            AlarmDef("Low Suction Pressure", "PT-001.LO", "process", "high", 0.03, "bar(g)", 3.5, "low"),
            AlarmDef("High Bearing Temperature", "TT-010.HI", "device", "high", 0.03, "degC", 85.0, "high"),
            AlarmDef("High Vibration", "VT-020.HI", "device", "critical", 0.02, "mm/s", 7.1, "high"),
            AlarmDef("Pump Trip", "XS-099.TRIP", "safety", "critical", 0.004, "state", 1.0, "state"),
        ),
        operating_limits={
            "suction_pressure_min": "3.5 bar(g)",
            "bearing_temp_trip": "95 degC",
            "vibration_alarm": "7.1 mm/s",
            "vibration_trip": "11.0 mm/s",
        },
        standby_asset_id="AST-BFP-101",
    ),
    Asset(
        "AST-DEA-101",
        "Deaerator 101",
        "vessel",
        "NorthPlant",
        "Unit 1",
        "high",
        "Stork",
        "DA-2400",
        "2013-11-02",
        "Spray-tray deaerator and storage tank supplying suction to BFP-101/102.",
        "DEA101",
        related=(("AST-BFP-101", "downstream_consumer"), ("AST-BFP-102", "downstream_consumer")),
        alarms=(
            AlarmDef(
                "Deaerator Low Level",
                "LT-001.LO",
                "process",
                "high",
                0.05,
                "%",
                40.0,
                "low",
                recent_multiplier=2.4,
                effects=(
                    _e("AST-BFP-101", "Low Suction Pressure", 0.65, 2, 9),
                    _e("AST-BFP-102", "Low Suction Pressure", 0.25, 3, 10),
                ),
            ),
            AlarmDef("Deaerator High Pressure", "PT-002.HI", "process", "medium", 0.02, "bar(g)", 2.2, "high"),
        ),
    ),
    Asset(
        "AST-MTR-101",
        "BFP-101 Drive Motor",
        "motor",
        "NorthPlant",
        "Unit 1",
        "high",
        "ABB",
        "AMA 500",
        "2014-03-12",
        "6.6 kV induction motor driving Boiler Feed Pump 101.",
        "MTR101",
        related=(("AST-BFP-101", "driven_equipment"),),
        alarms=(
            AlarmDef("High Winding Temperature", "TT-101.HI", "device", "high", 0.02, "degC", 130.0, "high"),
            AlarmDef(
                "Motor Overload",
                "IT-102.HI",
                "device",
                "high",
                0.015,
                "A",
                610.0,
                "high",
                effects=(_e("AST-BFP-101", "Pump Trip", 0.3, 0, 3),),
            ),
        ),
    ),
    Asset(
        "AST-LOS-101",
        "BFP-101 Lube Oil Console",
        "lube_oil_system",
        "NorthPlant",
        "Unit 1",
        "medium",
        "Flowserve",
        "LOC-45",
        "2014-03-12",
        "Forced lube oil console for BFP-101 bearings.",
        "LOS101",
        related=(("AST-BFP-101", "lubricated_equipment"), ("AST-BFP-102", "lubricated_equipment")),
        alarms=(
            AlarmDef(
                "Low Lube Oil Pressure",
                "PT-201.LO",
                "process",
                "high",
                0.025,
                "bar(g)",
                1.2,
                "low",
                recent_multiplier=1.8,
                effects=(_e("AST-BFP-101", "High Bearing Temperature", 0.55, 5, 15),),
            ),
            AlarmDef("Lube Oil Filter DP High", "PDT-202.HI", "device", "low", 0.08, "bar", 1.0, "high", chatter=True),
        ),
    ),
    Asset(
        "AST-FCV-103",
        "Feedwater Recirculation Valve 103",
        "valve",
        "NorthPlant",
        "Unit 1",
        "medium",
        "Fisher",
        "DBQ",
        "2015-06-20",
        "Automatic minimum-flow recirculation valve for BFP-101.",
        "FCV103",
        related=(("AST-BFP-101", "protected_equipment"),),
        alarms=(
            AlarmDef("Valve Position Deviation", "ZT-301.DEV", "device", "low", 0.06, "%", 5.0, "high", chatter=True),
        ),
    ),
    # ------------------------------------------------------------------ NorthPlant / Unit 2 (flood)
    Asset(
        "AST-HX-201",
        "Feedwater Heater 201",
        "heat_exchanger",
        "NorthPlant",
        "Unit 2",
        "medium",
        "SPX",
        "HP-FWH-6",
        "2012-08-01",
        "High-pressure closed feedwater heater.",
        "HX201",
        related=(("AST-DRM-201", "downstream"), ("AST-CV-202", "level_control")),
        alarms=(
            AlarmDef("Heater High Level", "LT-401.HI", "process", "high", 0.04, "%", 75.0, "high"),
            AlarmDef("Tube Leak Suspected", "AI-402.HI", "device", "critical", 0.004, "state", 1.0, "state"),
        ),
    ),
    Asset(
        "AST-DRM-201",
        "Steam Drum 201",
        "vessel",
        "NorthPlant",
        "Unit 2",
        "high",
        "Babcock",
        "SD-40",
        "2012-08-01",
        "Boiler steam drum.",
        "DRM201",
        related=(("AST-CV-202", "level_control"), ("AST-HX-201", "upstream")),
        alarms=(
            AlarmDef("Low Drum Level", "LT-501.LO", "safety", "critical", 0.01, "mm", -150.0, "low"),
            AlarmDef("High Drum Level", "LT-501.HI", "process", "high", 0.03, "mm", 150.0, "high"),
        ),
    ),
    Asset(
        "AST-CV-202",
        "Feedwater Control Valve 202",
        "valve",
        "NorthPlant",
        "Unit 2",
        "high",
        "Fisher",
        "HPT",
        "2012-08-01",
        "Three-element drum level control valve.",
        "CV202",
        related=(("AST-DRM-201", "controlled_vessel"),),
        alarms=(
            AlarmDef(
                "Valve Stuck",
                "ZS-601.FLT",
                "device",
                "high",
                0.01,
                "state",
                1.0,
                "state",
                effects=(_e("AST-DRM-201", "Low Drum Level", 0.4, 1, 6),),
            ),
            AlarmDef("Positioner Fault", "ZY-602.FLT", "device", "medium", 0.02, "state", 1.0, "state"),
        ),
    ),
    # ------------------------------------------------------------------ NorthPlant / Unit 3
    Asset(
        "AST-BLR-301",
        "Boiler 301",
        "boiler",
        "NorthPlant",
        "Unit 3",
        "high",
        "Babcock",
        "FM-120",
        "2010-05-15",
        "Package water-tube boiler.",
        "BLR301",
        related=(("AST-FDF-301", "combustion_air_supply"),),
        alarms=(
            AlarmDef("Flame Instability", "BS-701.FLT", "safety", "critical", 0.02, "state", 1.0, "state"),
            AlarmDef("High Flue Gas O2", "AT-702.HI", "process", "medium", 0.08, "%", 6.0, "high"),
            AlarmDef("High Steam Temperature", "TT-703.HI", "process", "high", 0.03, "degC", 540.0, "high"),
        ),
    ),
    Asset(
        "AST-FDF-301",
        "Forced Draft Fan 301",
        "fan",
        "NorthPlant",
        "Unit 3",
        "medium",
        "Howden",
        "FD-2200",
        "2010-05-15",
        "Combustion air forced draft fan.",
        "FDF301",
        related=(("AST-BLR-301", "served_equipment"),),
        alarms=(
            AlarmDef(
                "High Vibration",
                "VT-801.HI",
                "device",
                "high",
                0.03,
                "mm/s",
                7.1,
                "high",
                effects=(_e("AST-BLR-301", "Flame Instability", 0.2, 1, 5),),
            ),
            AlarmDef("Damper Position Fault", "ZT-802.FLT", "device", "medium", 0.03, "state", 1.0, "state"),
        ),
    ),
    # ------------------------------------------------------------------ NorthPlant / Unit 4 (nuisance)
    Asset(
        "AST-CTP-401",
        "Condensate Transfer Pump 401",
        "pump",
        "NorthPlant",
        "Unit 4",
        "low",
        "Grundfos",
        "CR-95",
        "2016-09-09",
        "Condensate transfer pump.",
        "CTP401",
        related=(("AST-TK-401", "suction_tank"),),
        alarms=(
            AlarmDef("Low Flow", "FT-901.LO", "process", "low", 0.6, "m3/h", 12.0, "low", chatter=True),
            AlarmDef("High Motor Current", "IT-902.HI", "device", "medium", 0.05, "A", 48.0, "high"),
        ),
    ),
    Asset(
        "AST-TK-401",
        "Condensate Tank 401",
        "tank",
        "NorthPlant",
        "Unit 4",
        "low",
        "Local",
        "CT-50",
        "2016-09-09",
        "Atmospheric condensate collection tank.",
        "TK401",
        related=(("AST-CTP-401", "discharge_pump"),),
        alarms=(
            AlarmDef("Tank High Level", "LT-911.HI", "process", "medium", 0.45, "%", 85.0, "high", chatter=True),
            AlarmDef("Tank Low Level", "LT-911.LO", "process", "medium", 0.05, "%", 15.0, "low"),
        ),
    ),
    # ------------------------------------------------------------------ NorthPlant / Unit 5 (motors)
    Asset(
        "AST-MCC-501",
        "Motor Control Center 501",
        "electrical",
        "NorthPlant",
        "Unit 5",
        "high",
        "Siemens",
        "SIVACON S8",
        "2011-02-11",
        "480 V motor control center feeding Unit 5 motors.",
        "MCC501",
        related=(
            ("AST-MTR-501", "power_supply_to"),
            ("AST-MTR-502", "power_supply_to"),
            ("AST-MTR-503", "power_supply_to"),
        ),
        alarms=(
            AlarmDef(
                "Bus Undervoltage",
                "EV-001.LO",
                "system",
                "high",
                0.03,
                "V",
                432.0,
                "low",
                recent_multiplier=1.5,
                effects=(
                    _e("AST-MTR-501", "Motor Trip", 0.55, 0, 2),
                    _e("AST-MTR-502", "Motor Trip", 0.45, 0, 2),
                    _e("AST-MTR-503", "Motor Trip", 0.35, 0, 3),
                ),
            ),
        ),
    ),
    Asset(
        "AST-MTR-501",
        "Cooling Water Pump Motor 501",
        "motor",
        "NorthPlant",
        "Unit 5",
        "high",
        "WEG",
        "W22",
        "2011-02-11",
        "Motor driving cooling water pump 501.",
        "MTR501",
        related=(("AST-MCC-501", "power_supply"),),
        alarms=(
            AlarmDef("Motor Trip", "XS-511.TRIP", "safety", "critical", 0.006, "state", 1.0, "state"),
            AlarmDef(
                "High Winding Temperature",
                "TT-512.HI",
                "device",
                "high",
                0.03,
                "degC",
                130.0,
                "high",
                effects=(_e("AST-MTR-501", "Motor Trip", 0.25, 5, 20),),
            ),
            AlarmDef("Phase Imbalance", "EI-513.HI", "device", "medium", 0.02, "%", 5.0, "high"),
        ),
    ),
    Asset(
        "AST-MTR-502",
        "Conveyor Drive Motor 502",
        "motor",
        "NorthPlant",
        "Unit 5",
        "medium",
        "WEG",
        "W22",
        "2011-02-11",
        "Coal conveyor drive motor.",
        "MTR502",
        related=(("AST-MCC-501", "power_supply"),),
        alarms=(
            AlarmDef("Motor Trip", "XS-521.TRIP", "safety", "critical", 0.006, "state", 1.0, "state"),
            AlarmDef(
                "Overcurrent",
                "IT-522.HI",
                "device",
                "high",
                0.02,
                "A",
                210.0,
                "high",
                effects=(_e("AST-MTR-502", "Motor Trip", 0.3, 0, 4),),
            ),
            AlarmDef("High Vibration", "VT-523.HI", "device", "high", 0.02, "mm/s", 4.5, "high"),
        ),
    ),
    Asset(
        "AST-MTR-503",
        "ID Fan Motor 503",
        "motor",
        "NorthPlant",
        "Unit 5",
        "high",
        "ABB",
        "AMA 400",
        "2011-02-11",
        "Induced draft fan motor.",
        "MTR503",
        related=(("AST-MCC-501", "power_supply"),),
        alarms=(
            AlarmDef("Motor Trip", "XS-531.TRIP", "safety", "critical", 0.005, "state", 1.0, "state"),
            AlarmDef("High Bearing Temperature", "TT-532.HI", "device", "high", 0.02, "degC", 90.0, "high"),
            AlarmDef(
                "Ground Fault",
                "EG-533.FLT",
                "safety",
                "critical",
                0.003,
                "state",
                1.0,
                "state",
                effects=(_e("AST-MTR-503", "Motor Trip", 0.8, 0, 1),),
            ),
        ),
    ),
    # ------------------------------------------------------------------ EastRefinery
    Asset(
        "AST-K-301",
        "Recycle Gas Compressor K-301",
        "compressor",
        "EastRefinery",
        "HCU-2",
        "high",
        "Elliott",
        "EDGE 38M",
        "2009-07-30",
        "Hydrocracker recycle gas centrifugal compressor.",
        "K301",
        related=(("AST-E-301", "discharge_cooler"), ("AST-FV-301", "anti_surge_valve")),
        alarms=(
            AlarmDef(
                "High Discharge Pressure",
                "PT-3012.HI",
                "process",
                "high",
                0.07,
                "bar(g)",
                168.0,
                "high",
                recent_multiplier=1.8,
            ),
            AlarmDef("High Discharge Temperature", "TT-3013.HI", "process", "high", 0.03, "degC", 135.0, "high"),
            AlarmDef("Surge Detected", "UY-3015.SURGE", "safety", "critical", 0.006, "state", 1.0, "state"),
            AlarmDef("High Vibration", "VT-3016.HI", "device", "high", 0.02, "um", 63.0, "high"),
        ),
        operating_limits={
            "discharge_pressure_alarm": "168 bar(g)",
            "discharge_pressure_trip": "175 bar(g)",
            "discharge_temp_alarm": "135 degC",
        },
    ),
    Asset(
        "AST-E-301",
        "K-301 Discharge Cooler E-301",
        "heat_exchanger",
        "EastRefinery",
        "HCU-2",
        "medium",
        "Alfa Laval",
        "AirCooler-12",
        "2009-07-30",
        "Air-cooled discharge cooler for compressor K-301.",
        "E301",
        related=(("AST-K-301", "served_compressor"),),
        alarms=(
            AlarmDef(
                "High Outlet Temperature",
                "TT-3101.HI",
                "process",
                "high",
                0.05,
                "degC",
                60.0,
                "high",
                recent_multiplier=1.8,
                effects=(
                    _e("AST-K-301", "High Discharge Pressure", 0.6, 4, 14),
                    _e("AST-K-301", "High Discharge Temperature", 0.45, 2, 10),
                ),
            ),
        ),
    ),
    Asset(
        "AST-FV-301",
        "K-301 Anti-Surge Valve FV-301",
        "valve",
        "EastRefinery",
        "HCU-2",
        "high",
        "CCI",
        "DRAG",
        "2009-07-30",
        "Anti-surge recycle valve for compressor K-301.",
        "FV301",
        related=(("AST-K-301", "protected_compressor"),),
        alarms=(
            AlarmDef(
                "Valve Position Deviation",
                "ZT-3201.DEV",
                "device",
                "medium",
                0.04,
                "%",
                5.0,
                "high",
                effects=(
                    _e("AST-K-301", "Surge Detected", 0.15, 1, 4),
                    _e("AST-K-301", "High Discharge Pressure", 0.35, 2, 10),
                ),
            ),
        ),
    ),
    Asset(
        "AST-K-302",
        "Wet Gas Compressor K-302",
        "compressor",
        "EastRefinery",
        "CDU-1",
        "high",
        "Dresser-Rand",
        "DATUM D12",
        "2011-01-18",
        "FCC wet gas compressor.",
        "K302",
        alarms=(
            AlarmDef("High Discharge Pressure", "PT-3302.HI", "process", "high", 0.02, "bar(g)", 16.5, "high"),
            AlarmDef("Seal Gas Low Differential Pressure", "PDT-3303.LO", "safety", "high", 0.02, "bar", 0.8, "low"),
            AlarmDef("High Vibration", "VT-3304.HI", "device", "high", 0.015, "um", 63.0, "high"),
        ),
    ),
    Asset(
        "AST-K-303",
        "Instrument Air Compressor K-303",
        "compressor",
        "EastRefinery",
        "UTIL",
        "medium",
        "Atlas Copco",
        "ZR 315",
        "2017-04-04",
        "Oil-free instrument air compressor.",
        "K303",
        alarms=(
            AlarmDef("Low Discharge Pressure", "PT-3402.LO", "process", "high", 0.02, "bar(g)", 6.0, "low"),
            AlarmDef("High Discharge Temperature", "TT-3403.HI", "process", "medium", 0.02, "degC", 110.0, "high"),
        ),
    ),
    Asset(
        "AST-P-101",
        "Crude Charge Pump P-101",
        "pump",
        "EastRefinery",
        "CDU-1",
        "high",
        "Sulzer",
        "BB2",
        "2008-10-10",
        "Crude unit charge pump.",
        "P101",
        alarms=(
            AlarmDef("Low Flow", "FT-1011.LO", "process", "high", 0.03, "m3/h", 420.0, "low"),
            AlarmDef("High Vibration", "VT-1012.HI", "device", "critical", 0.015, "mm/s", 7.1, "high"),
        ),
    ),
    # ------------------------------------------------------------------ SouthPlant
    Asset(
        "AST-CWP-301",
        "Cooling Water Pump 301",
        "pump",
        "SouthPlant",
        "CW-1",
        "medium",
        "KSB",
        "Omega 300",
        "2018-02-02",
        "Cooling water circulation pump.",
        "CWP301",
        related=(("AST-CTF-301", "cooling_tower"),),
        alarms=(
            AlarmDef("Low Discharge Pressure", "PT-3011.LO", "process", "high", 0.03, "bar(g)", 3.0, "low"),
            AlarmDef("High Vibration", "VT-3012.HI", "device", "medium", 0.02, "mm/s", 7.1, "high"),
        ),
        sim_fault="recommendations_unavailable",
    ),
    Asset(
        "AST-CTF-301",
        "Cooling Tower Fan 301",
        "fan",
        "SouthPlant",
        "CW-1",
        "medium",
        "Marley",
        "NC-8400",
        "2018-02-02",
        "Induced draft cooling tower fan.",
        "CTF301",
        related=(("AST-CWP-301", "served_pump"),),
        alarms=(
            AlarmDef("High Vibration", "VT-3111.HI", "device", "high", 0.03, "mm/s", 7.1, "high"),
            AlarmDef("Gearbox Oil Low Level", "LS-3112.LO", "device", "medium", 0.02, "state", 1.0, "state"),
        ),
    ),
)

ASSET_INDEX: dict[str, Asset] = {a.asset_id: a for a in ASSETS}

# Alarms that are "standing" at the anchor time: (asset_id, alarm_name, hours_before_anchor, acknowledged)
ACTIVE_SEEDS: tuple[tuple[str, str, float, bool], ...] = (
    ("AST-BFP-102", "High Vibration", 1.5, False),
    ("AST-BFP-102", "High Bearing Temperature", 2.2, True),
    ("AST-BFP-101", "Low Suction Pressure", 0.6, False),
    ("AST-DEA-101", "Deaerator Low Level", 0.8, True),
    ("AST-K-301", "High Discharge Pressure", 3.0, False),
    ("AST-E-301", "High Outlet Temperature", 3.3, True),
    ("AST-K-302", "Seal Gas Low Differential Pressure", 5.0, False),
    ("AST-P-101", "High Vibration", 0.9, False),
    ("AST-MTR-501", "Motor Trip", 0.4, False),
    ("AST-MCC-501", "Bus Undervoltage", 0.45, True),
    ("AST-CWP-301", "Low Discharge Pressure", 2.0, False),
    ("AST-TK-401", "Tank High Level", 0.2, False),
)

# Flood bursts in Unit 2: (days_before_anchor, number_of_alarms)
FLOOD_SEEDS: tuple[tuple[float, int], ...] = (
    (8.3, 22),
    (21.6, 17),
    (37.2, 28),
    (55.9, 14),
    (70.4, 19),
    (96.1, 24),
    (130.7, 16),
    (180.2, 21),
)

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
CRITICALITY_WEIGHT = {"low": 5, "medium": 15, "high": 25}
