"""Script that contains tools for configuration files generation."""

import json
import logging
import re

from si_wrapper.constant import DEFAULT_SIMULATION_J
from si_wrapper.pcbslicer import PortPad, PCBSlice

logger = logging.getLogger(__name__)


class Settings:
    """Create config for slices."""

    def __init__(self, json_path: str) -> None:
        """Load json file."""
        file = open(json_path)
        self.json_file = json.load(file)

    def get_offset(self) -> list[float]:
        """Get offset values."""
        return [
            float(self.json_file["board_offset"]["right"]),
            float(self.json_file["board_offset"]["left"]),
            float(self.json_file["board_offset"]["bottom"]),
            float(self.json_file["board_offset"]["top"]),
        ]

    def get_nets(self) -> list[str]:
        """Get list of designated nets."""
        return [i for i in self.json_file["designated_nets"]]

    def get_excluded_pads(self) -> list[str]:
        """Get list of footprints that cannot contain simulation ports on the pads."""
        return [i for i in self.json_file["excluded_pads"]]

    def get_included_pads(self) -> list[str]:
        """Get list of footprints that can contain simulation ports on the pads."""
        return [i for i in self.json_file["included_pads"]]

    def is_pad_designated(self) -> list[str]:
        """Get if designated pads hidden."""
        return self.json_file["hidden_pads"]["designated_net"]

    def is_pad_other(self) -> list[str]:
        """Get if other pads hidden."""
        return self.json_file["hidden_pads"]["other_nets"]

    def get_neighbour_offset(self) -> float:
        """Get neighbour offset."""
        return float(self.json_file["neighbouring_nets"]["offset"])

    def get_neighbour_common_points(self) -> int:
        """Get neighbour comon points."""
        return int(self.json_file["neighbouring_nets"]["common_points"])

    def get_neighbour_list(self) -> list[str]:
        """Get neighbour netlist."""
        return self.json_file["neighbouring_nets"]["netlist"]

    def get_neighbour_in_use(self) -> list[str]:
        """Get if neighbours in use."""
        return self.json_file["neighbouring_nets"]["in_use"]

    @staticmethod
    def get_filesystem_name(nets: list[str]) -> str:
        """Get normalized net name."""
        nn = (
            nets[0]
            .removeprefix("/")
            .replace("/", "_")
            .replace(" ", "_")
            .replace("(", "")
            .replace(")", "")
            .replace("{", "")
            .replace("}", "")
            .replace("~", "neg")
        )
        if len(nets) == 2:
            # Replace trailing `_P` `+` or `_+` to `_Diff`
            nn = re.sub(r"((_P)|(_?\+))$", r"_Diff", nn)
        return nn


class PortConfig:
    """Create port configuration file."""

    def __init__(self, json_path: str):
        """Init json path."""
        self.path = json_path

    def load_save(self, keyword: str, pattern: list) -> None:
        """Load and save json file."""
        with open(self.path, "r") as read_data:
            edit_data = json.load(read_data)

        existing_data = edit_data.get(keyword, [])
        existing_data.extend(pattern)

        edit_data[keyword] = existing_data

        with open(self.path, "w") as write_data:
            json.dump(edit_data, write_data, indent=2)

    def create_default_config(self) -> None:
        """Create default configuration file."""
        default_simulation_data = DEFAULT_SIMULATION_J

        with open(self.path, "w") as simulation_json:
            json.dump(default_simulation_data, simulation_json, indent=2)

    def renumerate_ports(self, old_nums: list) -> None:
        """Renumerate ports in file."""
        ports_to_remove = []
        with open(self.path, "r") as read_data:
            edit_data = json.load(read_data)
            ports = edit_data["ports"]
            print(old_nums)
            for p in ports:
                if p["number"] not in old_nums:
                    # ports.remove(p)
                    ports_to_remove.append(p)

            for port in ports_to_remove:
                ports.remove(port)

            for i in range(1, len(ports) + 1, 1):
                ports[i - 1]["number"] = i

        with open(self.path, "w") as write_data:
            json.dump(edit_data, write_data, indent=2)

    def add_port_pad(
        self,
        pcb_slice: PCBSlice,
        port: PortPad,
        impedance: int,
        excite: bool,
    ) -> None:
        """Add simulation port to configuration file."""
        layer, _ = pcb_slice.get_num_layers("B.Cu") if port.flipped is True else pcb_slice.get_num_layers("F.Cu")
        plane = 1 if layer == 0 else layer - 1
        logger.debug(
            f"Designated Net: \
            | Width: {port.size.x}mm \
            | Impedance: {impedance} \
            | SP{port.idx} | Layer: {layer}"
        )
        self.add_simulation_port(port.idx, port.size.x * 1000, port.size.y * 1000, impedance, layer, plane, excite)

    def add_simulation_port(
        self,
        number: int,
        width: float,
        length: float,
        impedance: float,
        layer: int,
        plane: int,
        excite: bool,
    ) -> None:
        """Add simulation port to configuration file."""
        port_keyword = "ports"
        port_pattern = [
            {
                "number": number,
                "width": round(width, 2),
                "length": round(length, 2),
                "impedance": impedance,
                "layer": layer,
                "plane": plane,
                "excite": excite,
            },
        ]

        self.load_save(port_keyword, port_pattern)

    def add_differential_pair(self, indexes: list, name: str, diff_impedance: float) -> None:
        """Add differential pair to config."""
        start_p = indexes[0]
        stop_p = indexes[1]
        start_n = indexes[2]
        stop_n = indexes[3]

        diff_keyword = "differential_pairs"
        diff_pattern = [
            {
                "start_p": start_p,
                "stop_p": stop_p,
                "start_n": start_n,
                "stop_n": stop_n,
                "name": name,
                "diff_impedance": diff_impedance,
            },
        ]

        self.load_save(diff_keyword, diff_pattern)


class NetInformation:
    """Get data about nets in json format."""

    def __init__(self, json_path: str) -> None:
        """Init path."""
        self.path = json_path

    def load_save(self, keyword: str, pattern: list) -> None:
        """Load and save json file."""
        with open(self.path, "r") as read_data:
            edit_data = json.load(read_data)

        existing_data = edit_data.get(keyword, [])
        existing_data.extend(pattern)

        edit_data[keyword] = existing_data

        with open(self.path, "w") as write_data:
            json.dump(edit_data, write_data, indent=2)

    def create_default(self) -> None:
        """Create default configuration file."""
        default_data: dict[str, list] = {"nets": []}

        with open(self.path, "w") as simulation_json:
            json.dump(default_data, simulation_json, indent=2)

    def add_attributes(self, netname: str, length: int, width: int, impedance: int, diff: bool) -> None:
        """Add all fields to the json file."""
        keyword = "nets"
        pattern = [
            {
                "name": netname,
                "length": "{:.3f}".format(length / 1000000),
                "width": "{:.3f}".format(width / 1000000),
                "impedance": impedance,
                "diff": diff,
                "charts": {
                    "impedance": "./results/Z_*",
                    "smith": "./results/*_smith.png",
                    "s-param": "./results/S_*",
                },
            }
        ]
        self.load_save(keyword, pattern)

    def get_names(self) -> list[str]:
        """Get names of the nets."""
        names = []
        with open(self.path, "r") as read_data:
            json_data = json.load(read_data)
            for element in json_data["nets"]:
                name = element["name"]
                if name is not None:
                    names.append(name)
        return list(names)
