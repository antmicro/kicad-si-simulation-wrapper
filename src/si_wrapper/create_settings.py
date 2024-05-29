"""Script that generates a set of configuration files for netslices."""

import pcbnew
import re
from si_wrapper.constant import REGEX_IMPEDANCE_PATT, PCB_EXTENSION
import sys
import json
import argparse
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SettingCreator:
    """Create settings json files for slices."""

    def __init__(self, json_path: str, out_path: str) -> None:
        """Load json file."""
        file = open(json_path)
        self.json_file = json.load(file)
        self.out_path = out_path

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
            "whitelist": [],
            "blacklist": [],
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


def parse_arguments() -> Any:
    """Parse commandline arguments."""
    parser = argparse.ArgumentParser(
        prog="Config creator",
        description="This application creates config for every chosen net",
    )

    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT_NET_CONFIG_PATH",
        help="Net configs out path",
    )

    parser.add_argument(
        "-i",
        "--input",
        metavar="INPUT_INIT_PATH",
        help="Initial .json input path",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument("-d", "--debug", action="store_true", dest="debug")
    group.add_argument("--log", choices=["DEBUG", "INFO", "WARNING", "ERROR"], dest="log_level")

    return parser.parse_args()


def get_pcb_path() -> str | None:
    """Check if file with .kicad_pcb extension exists in current folder."""
    for file in os.listdir():
        if file.endswith(PCB_EXTENSION):
            return os.path.join(os.getcwd(), file)
    return None


def main():
    """Generate settings for netslices."""
    args = parse_arguments()
    nlist = []

    init_path = ""
    out_path = ""

    if len(args.input) > 1 and len(args.output) > 1:
        init_path = args.input
        out_path = args.output

    else:
        logger.error("No given args file in current directory.")
        sys.exit(1)

    settings = SettingCreator(init_path, out_path)
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
        for net in nets:
            settings.new_config(net)


if __name__ == "__main__":
    main()
