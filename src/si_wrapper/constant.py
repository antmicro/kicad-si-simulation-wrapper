"""File containing constant values."""

import os

FP_NAME = "Simulation_Port"
FP_LIB_PATH = f"{os.path.dirname(os.path.abspath(__file__))}/footprint"

REGEX_IMPEDANCE_PATT = "^\d+Ohm-(\w|\d|-)*"
REGEX_CAP_RES0_PATT = "((C_\d*[munp])|(R_0R))_.*"

PCB_EXTENSION = ".kicad_pcb"
OUTPUT_DIR_PATH = "slices"

SIMULATION_J_CONFIG_PATH = "simulation.json"
NETINFO_J_PATH = "netinfo.json"

DEFAULT_SIMULATION_J = {
    "format_version": "1.2",
    "frequency": {"start": 2e8, "stop": 4e9},
    "max_steps": 50e4,
    "ports": [],
}
SQRT2 = 2**0.5
