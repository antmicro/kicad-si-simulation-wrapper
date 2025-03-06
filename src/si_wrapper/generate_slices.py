"""Script that generates slices."""

import logging
import os
import sys
from typing import Any, Annotated, List
from pathlib import Path

import coloredlogs
import typer

from si_wrapper.config import NetInformation, PortConfig, Settings
from si_wrapper.pcbslicer import PCBSlice, const, netclass_list

logger = logging.getLogger(__name__)
app = typer.Typer()


def setup_logging(debug) -> None:
    """Set up logging based on command line arguments."""
    level = logging.INFO

    if debug:
        level = logging.DEBUG

    if level == logging.DEBUG:
        coloredlogs.install(
            fmt="[%(asctime)s][%(name)s:%(lineno)d][%(levelname).4s] %(message)s",
            datefmt="%H:%M:%S",
            level=level,
        )
    else:
        coloredlogs.install(
            fmt="[%(asctime)s][%(levelname).4s] %(message)s",
            datefmt="%H:%M:%S",
            level=level,
        )


def check_path_exit(path: str) -> None:
    """Check if given path exists, if not, exit."""
    if path is None or not os.path.exists(path):
        logger.error(f"The path {path} does not exist.")
        sys.exit()


def check_path_warn(path: str) -> bool:
    """Check if given path exists, if not, return False."""
    if path is None or not os.path.exists(path):
        logger.warn(f"The path {path} does not exist.")
        return False

    return True


def get_pcb_path() -> Any:
    """Check if file with .kicad_pcb extension exists in current folder."""
    for file in os.listdir():
        if file.endswith(const.PCB_EXTENSION):
            return os.path.join(os.getcwd(), file)
    return None


def create_output_path(nname: str) -> tuple[str, str]:
    """Create dedicated folder/file for given path/s."""
    net_name = (
        nname.removeprefix("/")
        .replace("/", "_")
        .replace("_P", "_PN")
        .replace(" ", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("~", "neg")
        .replace("{", "")
        .replace("}", "")
    )

    out_dir = f"{const.OUTPUT_DIR_PATH}/{net_name}"
    out_file = f"{net_name}{const.PCB_EXTENSION}"
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    open(os.path.join(out_dir, out_file), "w")

    return out_dir, out_file


def check_diffs(indexes: list) -> list:
    """Check if net is differential pair."""
    tmp_idx = indexes
    if len(tmp_idx) < 4:
        logger.warning(
            "Differential net slice has too few Simulation Ports. Edit *.kicad_pcb and simulation.json file."
        )
        return [0, 0, 0, 0]
    if len(tmp_idx) > 4:
        logger.warning(
            "Differential net slice has too many Simulation Ports. Edit *.kicad_pcb and simulation.json file."
        )
        return [0, 0, 0, 0]

    return indexes


def get_ports_placement_info(first_net_ports: list, second_net_ports: list, is_diff) -> tuple[str, str]:
    """Return information about placement of simulation ports."""
    first_net_info = ""
    second_net_info = ""

    if len(first_net_ports) > 0:
        if len(first_net_ports) > 2:
            first_net_info = (
                f"Too many ( {len(first_net_ports)} ) Simulation Ports on first net. Check it and fix if needed."
            )
        elif len(first_net_ports) < 2:
            first_net_info = f"Too few ( {len(first_net_ports)} ) Simulation Ports on first net. Check it and fix."
        else:
            first_net_info = "OK."

    if len(second_net_ports) > 0 and is_diff != 0:
        if len(second_net_ports) > 2:
            second_net_info = (
                f"Too many ( {len(second_net_ports)} ) Simulation Ports on second net. Check it and fix if needed."
            )
        elif len(second_net_ports) < 2:
            second_net_info = f"Too few ( {len(second_net_ports)} ) Simulation Ports on second net. Check it and fix."
        else:
            second_net_info = "OK."
    else:
        second_net_info = " - "

    logger.warning(first_net_info)
    logger.warning(second_net_info)

    return first_net_info, second_net_info


@app.command("slice")
def main(
    config_file: Annotated[Path, typer.Option("--file", "-f", help="Path to settings file")] = Path("si-wrapper-cfg"),
    list_nets: Annotated[bool, typer.Option("--list", "-l", help="List Net classes with corresponding nets")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Increase logs verbosity")] = False,
):
    """Generate slices for chosen PCB."""
    pcb_path = get_pcb_path()
    if pcb_path is None:
        logger.error("No .kicad_pcb file in current directory.")
        sys.exit()

    check_path_exit(path=pcb_path)

    if list_nets:
        logger.info("Displaying Netclasses...")
        netclass_list(pcb_path)

    cfg_files = [config_file] if config_file.suffix == ".json" else list(config_file.glob("**/*.json"))
    for cfile in cfg_files:
        is_diff = False
        plane = 0
        excite = [True, True]

        sp_index_1: List = []
        sp_index_2: List = []
        setup_logging(debug)

        settings_path = str(cfile)
        settings = Settings(settings_path)

        logger.info("Loading Simulation Port footprint...")
        netname = settings.get_nets()
        pcb_slice = PCBSlice(pcb_path, netname)
        pcb_slice.check_netname()

        included_pads = settings.get_included_pads()
        excluded_pads = settings.get_excluded_pads()

        offset = settings.get_offset()
        dir_path, file_path = create_output_path(netname[0])
        out_path = os.path.join(dir_path, file_path)
        check_path_exit(path=out_path)

        neighbour_offset = settings.get_neighbour_offset()
        neighbour_cp = settings.get_neighbour_common_points()
        neighbour_netlist = settings.get_neighbour_list()
        neighbour_inuse = settings.get_neighbour_in_use()

        # Get designated track or tracks
        des_net_1, des_net_2 = pcb_slice.get_des_tracks()

        # Get information about single selected line or for differential pairs - two lines
        net_length_1, net_width_1, net_start_pos_1, net_end_pos_1, net_impedance_1 = pcb_slice.get_selected_track_info(
            des_net_1
        )

        if des_net_2 != []:
            net_length_2, net_width_2, _, _, net_impedance_2 = pcb_slice.get_selected_track_info(des_net_2)
            logger.info("Differential tracks recognized")
            is_diff = True
        else:
            net_length_2, net_width_2, _, _, net_impedance_2 = (
                None,
                None,
                None,
                None,
                None,
            )
            logger.info("Single track recognized")

        # Combine list of two separate tracks into one
        logger.info("Gathering information about selected net/s...")
        designated_tracks = des_net_1 + des_net_2
        net_length, net_width, net_start_pos, net_end_pos, net_impedance = pcb_slice.get_selected_track_info(
            designated_tracks
        )

        logger.info("Gathering information about pads...")
        pads, board_origin = pcb_slice.get_pads()

        # Get orientation of the track/s to place simulation ports
        logger.info("Checking tracks orientation...")
        candidate_sp_pos1, candidate_sp_orient1, candidate_sp_is_flipped_1 = pcb_slice.get_track_orientation(
            des_net_1, pads, included_pads, excluded_pads
        )
        if des_net_2 != []:
            candidate_sp_pos2, candidate_sp_orient2, candidate_sp_is_flipped_2 = pcb_slice.get_track_orientation(
                des_net_2, pads, included_pads, excluded_pads
            )

        if neighbour_inuse:
            logger.info("Looking for neighbouring tracks...")
            nearest_net_names = pcb_slice.find_nearest_to_designated_net(
                net_start_pos, net_end_pos, neighbour_offset, neighbour_cp, neighbour_netlist
            )

        logger.info("Terminating Tracks...")
        terminate_tracks = pcb_slice.create_edge_cuts([net_start_pos, net_end_pos], offset)

        if neighbour_inuse:
            pcb_slice.remove_pads(nearest_net_names)

        # Creating config
        port_cfg = PortConfig(f"{dir_path}/{const.SIMULATION_J_CONFIG_PATH}")
        port_cfg.create_default_config()

        # Create netinfo file
        net_info = NetInformation(f"{dir_path}/{const.NETINFO_J_PATH}")
        net_info.create_default()
        net_info.add_attributes(netname[0], net_length_1, net_width_1, net_impedance_1, is_diff)
        if is_diff is True:
            net_info.add_attributes(netname[1], net_length_2, net_width_2, net_impedance_2, is_diff)

        # Set and save simulation port terminators
        for i in range(len(terminate_tracks)):
            whole_track, sp_termination_layer, max_copper_layer_num = pcb_slice.get_whole_track(terminate_tracks[i])

            if sp_termination_layer < int(max_copper_layer_num / 2):
                plane = sp_termination_layer + 1
            else:
                plane = sp_termination_layer - 1

            net_length_3, net_width_3, net_start_pos_3, net_end_pos_3, net_impedance_3 = (
                pcb_slice.get_selected_track_info(whole_track)
            )
            logger.debug(
                f"Nets params: Length: {net_length_3} \
                | Width: {net_width_3} \
                | Impedance: {net_impedance_3} \
                | SP{i+1} | Layer: {sp_termination_layer}"
            )
            port_cfg.add_simulation_port(
                i + 1, net_width_3, 500000, net_impedance_3, sp_termination_layer, plane, False
            )

        # Get information about other nets for placing simulation ports
        trs = pcb_slice.get_all_tracks()
        if len(trs) > 0:  # Check if exists any other
            other_pads = pcb_slice.get_other_pads()
            other_net_length, other_net_width, other_net_start_pos, other_net_end_pos, other_net_impedance = (
                pcb_slice.get_selected_track_info(trs)
            )
            candidate_sp_pos_other, candidate_sp_ori_other, candidate_sp_is_flipped_other = (
                pcb_slice.get_track_orientation(trs, other_pads, included_pads, excluded_pads)
            )
            # Hiding other pads
            if settings.is_pad_other():
                pcb_slice.hide_pads(other_pads, candidate_sp_pos_other)

        # Hiding designated pads
        if settings.is_pad_designated():
            pcb_slice.hide_pads(pads, candidate_sp_pos1)
            if des_net_2 != []:
                pcb_slice.hide_pads(pads, candidate_sp_pos2)

        if len(trs) > 0:
            sp_index_other, layer_flip_other = pcb_slice.place_simulation_port(
                candidate_sp_pos_other, candidate_sp_ori_other, candidate_sp_is_flipped_other
            )

        sp_index_1, layer_flip_1 = pcb_slice.place_simulation_port(
            candidate_sp_pos1, candidate_sp_orient1, candidate_sp_is_flipped_1
        )
        if des_net_2 != []:
            sp_index_2, layer_flip_2 = pcb_slice.place_simulation_port(
                candidate_sp_pos2, candidate_sp_orient2, candidate_sp_is_flipped_2
            )

        diff_index_list = []
        if len(trs) > 0:
            for index in sp_index_other:
                lyr, _ = (
                    pcb_slice.get_num_layers("B.Cu")
                    if layer_flip_other[sp_index_other.index(index)] is True
                    else pcb_slice.get_num_layers("F.Cu")
                )
                plane = 1 if lyr == 0 else lyr - 1
                port_cfg.add_simulation_port(index, other_net_width, 500000, other_net_impedance, lyr, plane, False)
                diff_index_list.append(index)
        for index in sp_index_1:
            lyr, _ = (
                pcb_slice.get_num_layers("B.Cu")
                if layer_flip_1[sp_index_1.index(index)] is True
                else pcb_slice.get_num_layers("F.Cu")
            )
            plane = 1 if lyr == 0 else lyr - 1
            logger.debug(
                f"Designated Net: Length: {net_length_1} \
                | Width: {net_width_1} \
                | Impedance: {net_impedance_1} \
                | SP{index} | Layer: {lyr}"
            )
            port_cfg.add_simulation_port(index, net_width_1, 500000, net_impedance_1, lyr, plane, excite[0])
            diff_index_list.append(index)
            excite[0] = False
        if des_net_2 != []:
            for index in sp_index_2:
                lyr, _ = (
                    pcb_slice.get_num_layers("B.Cu")
                    if layer_flip_2[sp_index_2.index(index)] is True
                    else pcb_slice.get_num_layers("F.Cu")
                )
                plane = 1 if lyr == 0 else lyr - 1
                logger.debug(
                    f"Designated Net: Length: {net_length_2} \
                    | Width: {net_width_2} \
                    | Impedance: {net_impedance_2} \
                    | SP{index} | Layer: {lyr}"
                )
                port_cfg.add_simulation_port(index, net_width_2, 500000, net_impedance_2, lyr, plane, excite[1])
                diff_index_list.append(index)
                excite[1] = False

            netname_diff = netname[0].replace("/", "").replace("_P", "Diff")
            port_cfg.add_differential_pair(check_diffs(diff_index_list), netname_diff)

        pcb_slice.rename_layers()
        pcb_slice.edit_diff_via_clearance(True)
        pcb_slice.save_slice(out_path)

        # Can't fill zones using the same file without saving it when changed properties of netclasses.
        # Have to save it, reopen and refill, then again save - some PCBnew bug.
        fill_pcb1 = PCBSlice(out_path, netname)
        fill_pcb1.refill_zones()
        fill_pcb1.save_slice(out_path)

        fill_pcb2 = PCBSlice(out_path, netname)
        fill_pcb2.edit_diff_via_clearance(False)
        fill_pcb2.save_slice(out_path)

        info_port_plcmnt = get_ports_placement_info(sp_index_1, sp_index_2, des_net_2)
        print(f"{netname} | 1. {info_port_plcmnt[0]} | 2. {info_port_plcmnt[1]}")


if __name__ == "__main__":
    app()
