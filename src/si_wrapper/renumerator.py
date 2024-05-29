"""Script that allows renumerating simulation ports already placed on the board."""

import logging
import os

from si_wrapper.config import NetInformation, PortConfig
from si_wrapper.pcbslicer import PCBSlice, const
import typer
# import subprocess


logger = logging.getLogger(__name__)
app = typer.Typer()

def get_pcb_path() -> str | None:
    """Check if file with .kicad_pcb extension exists in current folder."""
    for file in os.listdir():
        if file.endswith(const.PCB_EXTENSION):
            return os.path.join(os.getcwd(), file)
    return None


@app.command("renumerate")
def main():
    """Renumerate placed Simulation Ports on the board and update simulation.json file."""
    # Open .json file with information
    net_config = NetInformation(const.NETINFO_J_PATH)
    net_name = net_config.get_names()

    # Find .kicad_pcb file
    pcb_path = get_pcb_path()

    # Load simulation.json file
    port_config = PortConfig(const.SIMULATION_J_CONFIG_PATH)

    # Open KiCad and perform editing
    # subprocess.run(['pcbnew', pcb_path])
    pcb_copy = PCBSlice(pcb_path, net_name)
    # Change numbers of Simulation Ports
    old_numbers = pcb_copy.renumerate_simulation_ports()
    port_config.renumerate_ports(old_numbers)
    pcb_copy.save_slice(pcb_path)


if __name__ == "__main__":
    main()
