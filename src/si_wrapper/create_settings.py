"""Script that generates a set of configuration files for netslices."""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Annotated

import pcbnew
import typer

from si_wrapper.constant import PCB_EXTENSION, REGEX_IMPEDANCE_PATT

logger = logging.getLogger(__name__)
app = typer.Typer()


class SettingCreator:
    """Create settings json files for slices."""

    def __init__(self, json_path: Path, out_path: Path) -> None:
        """Load json file."""
        if json_path.exists():
            file = open(json_path)
            self.json_file = json.load(file)
        else:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            file = open(json_path, "a")
            self.json_file = {"board": ".", "netclass": "all", "nets": []}
            json.dump(self.json_file, file)
        if not out_path.exists():
            out_path.mkdir(parents=True, exist_ok=True)

        self.out_path = str(out_path)

    def get_board(self) -> list[str]:
        """Get name of the board."""
        return self.json_file["board"]

    def get_nets(self) -> list[str]:
        """Get nets field from file."""
        return [i for i in self.json_file["nets"]]

    def get_netclass(self) -> list[str]:
        """Get netclass filed from file."""
        return self.json_file["netclass"]

    def new_config(self, nets: list) -> None:
        """Create new configuration file for single net."""
        data = {
            "designated_nets": nets,
            "board_offset": {"top": 1, "bottom": 1, "left": 1, "right": 1},
            "included_pads": [],
            "excluded_pads": [],
            "hidden_pads": {"designated_net": True, "other_nets": True},
            "neighbouring_nets": {
                "in_use": True,
                "offset": 0.01,
                "common_points": 100,
                "netlist": [],
            },
        }

        with open(
            f'{self.out_path}/{nets[0].removeprefix("/").replace("/", "_").replace("_P","_PN").replace(" ","_")}.json',
            "w",
        ) as simulation_json:
            json.dump(data, simulation_json, indent=2)


def get_pcb_path() -> str | None:
    """Check if file with .kicad_pcb extension exists in current folder."""
    for file in os.listdir():
        if file.endswith(PCB_EXTENSION):
            return os.path.join(os.getcwd(), file)
    return None


@app.command("settings")
def main(
    input_file: Annotated[Path, typer.Option("--input", "-i", help="Initial .json input path")] = Path(
        "./si-wrapper-init.json"
    ),
    output_file: Annotated[Path, typer.Option("--output", "-o", help="Net config output path")] = Path(
        "./si-wrapper-cfg"
    ),
):
    """Generate settings for netslices."""
    nlist = []

    settings = SettingCreator(input_file, output_file)
    path = get_pcb_path()
    board = pcbnew.LoadBoard(path)

    if path is None:
        logger.error("No .kicad_pcb file in current directory.")
        sys.exit(1)
    nets = settings.get_nets()
    netclass = settings.get_netclass()

    if netclass == "all":
        for _, netinfo in board.GetNetsByNetcode().items():
            if re.search(REGEX_IMPEDANCE_PATT, netinfo.GetNetClassName()):
                if netinfo.GetNetname()[-1] != "P" and netinfo.GetNetname()[-1] != "+":
                    nlist.append(netinfo.GetNetname())

        for n in nlist:
            if n[-1] == "N":
                settings.new_config([n[0:-1] + "P", n[0:-1] + "N"])
            elif n[-1] == "-":
                settings.new_config([n[0:-1] + "+", n[0:-1] + "-"])
            elif n[-1] != "N" or n[-1] != "P":
                settings.new_config([n])

    elif len(netclass) > 1 and netclass != "all":
        for _, netinfo in board.GetNetsByNetcode().items():
            if netinfo.GetNetClassName() == netclass:
                if netinfo.GetNetname()[-1] != "P" and netinfo.GetNetname()[-1] != "+":
                    nlist.append(netinfo.GetNetname())

        for n in nlist:
            if n[-1] == "N":
                settings.new_config([n[0:-1] + "P", n[0:-1] + "N"])
            elif n[-1] == "-":
                settings.new_config([n[0:-1] + "+", n[0:-1] + "-"])
            elif n[-1] != "N" or n[-1] != "P":
                settings.new_config([n])
    else:
        for n in nets:
            if n[-1] == "N":
                settings.new_config([n[0:-1] + "P", n[0:-1] + "N"])
            elif n[-1] == "-":
                settings.new_config([n[0:-1] + "+", n[0:-1] + "-"])
            elif n[-1] != "N" or n[-1] != "P":
                settings.new_config([n])


if __name__ == "__main__":
    app()
