"""Library file containing class for generating and editing netslices."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Iterable, List, Set
from dataclasses import dataclass
import numpy as np
import pcbnew
from math import inf

import si_wrapper.constant as const

logger = logging.getLogger(__name__)


@dataclass
class Point:
    """Class representing 2D point."""

    x: float = 0
    y: float = 0

    def distance(self, rhs: Point) -> float:
        """Get euclidean distance between two points."""
        return ((self.x - rhs.x) ** 2 + (self.y - rhs.y) ** 2) ** 0.5

    def rotation(self, rhs: Point) -> float:
        """Get orientation of vector connecting two points."""
        return np.arctan2((rhs.x - self.x), (rhs.y - self.y)) * (180.0 / np.pi) - 180.0


@dataclass
class PortPad:
    """Class representing Pad that may be also simulation port."""

    position: Point
    """Pad origin coordinates"""
    flipped: bool
    """False- pad on F.Cu; True- pad on B.Cu"""
    port_rotation: float
    """Rotation of simulation port (based on trace that exits pad)"""
    pad_rotation: float
    """Rotation of pad"""
    size: Point
    """Size of pad"""
    multi_connected: bool
    """True if more than one trace that exits pad"""
    opt_rating: int
    """How optimal is placement of this port.
    
    There are 3 conditions for optimal port placement:
    - pad is vertical or horizontal
    - pad is rectangle
    - trace exits at the same angle as pad is oriented
    0 - all conditions fulfilled, 3 - none of conditions fulfilled
    """
    ort_case: bool
    """Pad is not vertical/horizontal, but trace that exits it is"""
    idx: int = 0
    """Port ordinal number"""

    def distance(self, rhs: PortPad) -> float:
        """Get distance between origins of two pads, pads that are on different layers have infinite distance."""
        if self.flipped != rhs.flipped:
            return inf
        return self.position.distance(rhs.position)


class PCBSlice:
    """Class containing methods for slicing pcb."""

    static_sp_index = 1
    static_hole = 0
    static_diameter = 0

    def __init__(self, board_pth: str, netname: list) -> None:
        """Initialize variables."""
        self.board = pcbnew.LoadBoard(board_pth)
        self.netname = netname
        self.GNDnet = self.board.GetNetsByName().find("GND").value()[1]

        fp_name = const.FP_NAME
        self.static_sp_index = 1
        self.SimPortFootprint = pcbnew.FootprintLoad(const.FP_LIB_PATH, fp_name)
        self.SimPortFootprint.Reference().SetVisible(False)

    def ci_dict(self) -> str:
        """Return pattern matching Antmicro standard."""
        return const.REGEX_IMPEDANCE_PATT

    def check_netname(self) -> None:
        """Check if netname is matching impedance pattern."""
        net_flag = 0
        for track in self.board.GetTracks():
            if track.GetNetname() in self.netname:
                if re.search(self.ci_dict(), str(track.GetNetClassName())):
                    net_flag = 1
        logger.info(f"Designated nets: {self.netname}")

        if net_flag == 0:
            logger.error("Net is not in controlled impedance class")
            sys.exit(1)

    def get_all_tracks(self) -> list[Any]:
        """Get all tracks."""
        return [
            track
            for track in self.board.GetTracks()
            if (
                track.GetNetname() not in self.netname
                and track.GetNetClassName() != "Default"
                and re.search(self.ci_dict(), str(track.GetNetClassName()))
            )
        ]

    def get_des_tracks(self) -> list:
        """Return designated tracks."""
        des_track: list = [[], []]
        try:
            for net_n in self.netname:
                for track in self.board.GetTracks():
                    if track.GetNetname() == net_n:
                        des_track[self.netname.index(net_n)].append(track)
        except NameError:
            logger.exception("Traces cannot be found")

        return des_track

    def get_whole_track(self, track_in: Any) -> tuple[list[Any], int, int]:
        """Return information about chosen track."""
        tracks_out = []
        layer = 0
        lcopp_num: Any = 0

        for track in self.board.Tracks():
            if track.GetNetname() == track_in.GetNetname():
                tracks_out.append(track)

        layer, lcopp_num = self.get_num_layers(track_in.GetLayerName())
        return tracks_out, layer, lcopp_num

    def get_selected_track_info(self, tracks: list[Any]) -> list:
        """Give information about track. It returns.

        * length of the net,
        * width of the net,
        * starting position of the tracks of the net,
        * ending position of the tracks of the net,
        * nominal impedance.
        """
        track_length = 0
        track_widths: float = 0
        start_pos = []
        end_pos = []
        impedance: float = 0
        diff_impedance = None

        try:
            for track in tracks:
                if isinstance(track, pcbnew.PCB_VIA):
                    continue
                start_pos.append(list(pcbnew.ToMM(track.GetStart())))
                end_pos.append(list(pcbnew.ToMM(track.GetEnd())))

                track_length += track.GetLength()
                track_widths = track.GetWidth()
                impedance_str = re.search("^\d+", track.GetNetClassName())
                assert impedance_str is not None
                imp = float(impedance_str.group())
                if "se" in track.GetNetClassName().lower():
                    impedance = imp
                else:
                    impedance = 50
                    diff_impedance = imp

        except NameError:
            logger.exception("Traces cannot be found")

        return [
            float(track_length),
            int(track_widths),
            list(start_pos),
            list(end_pos),
            float(impedance),
            diff_impedance,
        ]

    def get_pads(self) -> List[pcbnew.PAD]:
        """Return pads of chosen NET."""
        return [pad for pad in self.board.GetPads() if pad.GetNetname() in self.netname]

    def get_other_pads(self) -> list:
        """Get all pads but impedance controlled."""
        pads = []
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if pad.GetNetname() not in self.netname:
                    pad.SetPosition(footprint.GetPosition())
                    pads.append(pad)
        return pads

    def resize_zones(self, edges: list) -> None:
        """Fit sizes of the zones to size of new PCB."""
        [max_edge_x, min_edge_x, max_edge_y, min_edge_y] = edges

        zones = self.board.Zones()
        to_remove = []
        for zone in zones:

            outline = zone.Outline()
            zone.SetNet(self.GNDnet)
            zone.UnFill()
            zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
            for i in range(outline.FullPointCount()):
                [point_x, point_y] = outline.COutline(0).GetPoint(i)
                [point_x, point_y] = [pcbnew.ToMM(point_x), pcbnew.ToMM(point_y)]
                if point_x > max_edge_x:
                    point_x = max_edge_x
                if point_x < min_edge_x:
                    point_x = min_edge_x
                if point_y > max_edge_y:
                    point_y = max_edge_y
                if point_y < min_edge_y:
                    point_y = min_edge_y

                outline.COutline(0).SetPoint(i, pcbnew.VECTOR2I_MM(float(point_x), float(point_y)))
            if zone.CalculateOutlineArea() < 1e-5:
                to_remove.append(zone)
        for zone in to_remove:
            self.board.Remove(zone)

        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(zones)

    def to_gnd(self, track: pcbnew.PCB_TRACK) -> None:
        """Set netclass of net to GND."""
        if re.search(self.ci_dict(), str(track.GetNetClassName())) is None:
            track.SetNet(self.GNDnet)

    def cut_tracks(self, edges: list) -> list:
        """Remove tracks existing out of the EdgeCuts layer."""
        orient = 0
        sp_tracks = []

        [max_edge_x, min_edge_x, max_edge_y, min_edge_y] = edges

        # Define courners #
        top_left_edge = [edges[1], edges[3]]
        top_right_edge = [edges[0], edges[3]]
        bottom_left_edge = [edges[1], edges[2]]
        bottom_right_edge = [edges[0], edges[2]]

        for track in self.board.GetTracks():
            self.to_gnd(track)

            [start_x, start_y] = pcbnew.ToMM(track.GetStart())
            [end_x, end_y] = pcbnew.ToMM(track.GetEnd())

            if (
                (start_x < min_edge_x and end_x < min_edge_x)
                or (start_x > max_edge_x and end_x > max_edge_x)
                or (start_y < min_edge_y and end_y < min_edge_y)
                or (start_y > max_edge_y and end_y > max_edge_y)
            ):
                self.board.Delete(track)
                continue

            if start_x < min_edge_x and end_x > min_edge_x:
                # [StartCheck, SEdge, EEdge] = [True, top_left_edge, bottom_left_edge]
                start_x, start_y = self.calculate_intersection(
                    top_left_edge,
                    bottom_left_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="start",
                )
                orient = self.calculate_orientation((start_x, start_y), (end_x, end_y))
                track.SetStart(pcbnew.VECTOR2I_MM(float(start_x), float(start_y)))
                if (
                    self.terminate_track(
                        start_x,
                        start_y,
                        orient,
                        track.GetWidth(),
                        track,
                        track_beg="start",
                    )
                    == 0
                ):
                    sp_tracks.append(track)

            if start_x > min_edge_x and end_x < min_edge_x:
                # [EndCheck, SEdge, EEdge] = [True, top_left_edge, bottom_left_edge]
                end_x, end_y = self.calculate_intersection(
                    top_left_edge,
                    bottom_left_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="end",
                )
                orient = self.calculate_orientation((end_x, end_y), (start_x, start_y))
                track.SetEnd(pcbnew.VECTOR2I_MM(float(end_x), float(end_y)))
                if self.terminate_track(end_x, end_y, orient, track.GetWidth(), track, track_beg="end") == 0:
                    sp_tracks.append(track)

            if start_x < max_edge_x and end_x > max_edge_x:
                # [EndCheck, SEdge, EEdge] = [True, top_right_edge, bottom_right_edge]
                end_x, end_y = self.calculate_intersection(
                    top_right_edge,
                    bottom_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="end",
                )
                orient = self.calculate_orientation((end_x, end_y), (start_x, start_y))
                track.SetEnd(pcbnew.VECTOR2I_MM(float(end_x), float(end_y)))
                if self.terminate_track(end_x, end_y, orient, track.GetWidth(), track, track_beg="end") == 0:
                    sp_tracks.append(track)

            if start_x > max_edge_x and end_x < max_edge_x:
                # [StartCheck, SEdge, EEdge] = [True, top_right_edge, bottom_right_edge]
                [start_x, start_y] = self.calculate_intersection(
                    top_right_edge,
                    bottom_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="start",
                )
                orient = self.calculate_orientation((start_x, start_y), (end_x, end_y))
                track.SetStart(pcbnew.VECTOR2I_MM(float(start_x), float(start_y)))
                if (
                    self.terminate_track(
                        start_x,
                        start_y,
                        orient,
                        track.GetWidth(),
                        track,
                        track_beg="start",
                    )
                    == 0
                ):
                    sp_tracks.append(track)

            if start_y < min_edge_y and end_y > min_edge_y:
                # [StartCheck, SEdge, EEdge] = [True, top_left_edge, top_right_edge]
                [start_x, start_y] = self.calculate_intersection(
                    top_left_edge,
                    top_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="start",
                )
                orient = self.calculate_orientation((start_x, start_y), (end_x, end_y))
                track.SetStart(pcbnew.VECTOR2I_MM(float(start_x), float(start_y)))
                if (
                    self.terminate_track(
                        start_x,
                        start_y,
                        orient,
                        track.GetWidth(),
                        track,
                        track_beg="start",
                    )
                    == 0
                ):
                    sp_tracks.append(track)

            if start_y > min_edge_y and end_y < min_edge_y:
                # [EndCheck, SEdge, EEdge] = [True, top_left_edge, top_right_edge]
                end_x, end_y = self.calculate_intersection(
                    top_left_edge,
                    top_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="end",
                )
                orient = self.calculate_orientation((end_x, end_y), (start_x, start_y))
                track.SetEnd(pcbnew.VECTOR2I_MM(float(end_x), float(end_y)))
                if self.terminate_track(end_x, end_y, orient, track.GetWidth(), track, track_beg="end") == 0:
                    sp_tracks.append(track)

            if start_y < max_edge_y and end_y > max_edge_y:
                # [EndCheck, SEdge, EEdge] = [True, bottom_left_edge, bottom_right_edge]
                [end_x, end_y] = self.calculate_intersection(
                    bottom_left_edge,
                    bottom_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="end",
                )
                orient = self.calculate_orientation((end_x, end_y), (start_x, start_y))
                track.SetEnd(pcbnew.VECTOR2I_MM(float(end_x), float(end_y)))
                if self.terminate_track(end_x, end_y, orient, track.GetWidth(), track, track_beg="end") == 0:
                    sp_tracks.append(track)

            if start_y > max_edge_y and end_y < max_edge_y:
                # [StartCheck, SEdge, EEdge] = [True, bottom_left_edge, bottom_right_edge]
                [start_x, start_y] = self.calculate_intersection(
                    bottom_left_edge,
                    bottom_right_edge,
                    track_start=[start_x, start_y],
                    track_end=[end_x, end_y],
                    track_beg="start",
                )
                orient = self.calculate_orientation((start_x, start_y), (end_x, end_y))
                track.SetStart(pcbnew.VECTOR2I_MM(float(start_x), float(start_y)))
                if (
                    self.terminate_track(
                        start_x,
                        start_y,
                        orient,
                        track.GetWidth(),
                        track,
                        track_beg="start",
                    )
                    == 0
                ):
                    sp_tracks.append(track)

        return sp_tracks

    def hide_pads(self, pads: Any, simports_pos: tuple[Iterable, Iterable]) -> None:
        """Remove pads from project."""
        for footprint in self.board.GetFootprints():
            fp_x = footprint.GetPosition()[0]
            fp_y = footprint.GetPosition()[1]
            for x, y in simports_pos:
                if (pcbnew.ToMM(fp_x) - 1 < x < pcbnew.ToMM(fp_x) + 1) and (
                    pcbnew.ToMM(fp_y) - 1 < y < pcbnew.ToMM(fp_y) + 1
                ):
                    if re.search("SP\d+", str(footprint.GetReference())) is None:
                        self.board.Remove(footprint)

    def remove_footprints(self, edges: list) -> list:
        """Change size of the board to edge nearest footprints and remove those out of the range of the board."""
        to_remove = []
        new_edges = edges

        # Removing footprints v1 #
        for footprint in self.board.GetFootprints():
            [footprint_x, footprint_y] = pcbnew.ToMM(footprint.GetPosition())
            if footprint_x > edges[0] or footprint_x < edges[1] or footprint_y > edges[2] or footprint_y < edges[3]:
                to_remove.append(footprint)

        for item in to_remove:
            self.board.Delete(item)

        # checkLayers = [pcbnew.F_CrtYd, pcbnew.B_CrtYd]

        for footprint in self.board.GetFootprints():
            bbox = footprint.GetFpPadsLocalBbox()
            start_x = pcbnew.ToMM(bbox.GetLeft())
            start_y = pcbnew.ToMM(bbox.GetTop())
            end_x = pcbnew.ToMM(bbox.GetRight())
            end_y = pcbnew.ToMM(bbox.GetBottom())
            # print(start_x, start_y, end_x, end_y, footprint.GetReference())
            # Set footprints to remove #
            if start_x <= edges[1] and end_x >= edges[1]:
                new_edges[1] = start_x - 0.2
            if start_x <= edges[0] and end_x >= edges[0]:
                new_edges[0] = end_x + 0.2
            if start_y <= edges[3] and end_y >= edges[3]:
                new_edges[3] = start_y - 0.2
            if start_y <= edges[2] and end_y >= edges[2]:
                new_edges[2] = end_y + 0.2

        return list(new_edges)

    def footprint_to_pad(self) -> None:
        """Split every footprint into separate pad, then turn pad into footprint."""
        pads_as_fp = []
        for pad in self.board.GetPads():
            for footprint in self.board.GetFootprints():
                for pad in footprint.Pads():
                    virt_footprint = pcbnew.FOOTPRINT(self.board)
                    new_pad = pcbnew.PAD(pad)
                    new_pad.SetPos(pcbnew.VECTOR2I(0, 0))  # Set pad position to origin of the footprint
                    if re.search(self.ci_dict(), str(pad.GetNetClassName())) is None:
                        new_pad.SetNet(self.GNDnet)
                    virt_footprint.Add(new_pad)
                    # virt_footprint.SetReference(f'{footprint.GetReference()}_{pad.GetName()}')
                    virt_footprint.SetReference(f"{footprint.GetReference()}")
                    virt_footprint.Reference().SetVisible(False)  # Hide reference text
                    virt_footprint.SetLayer(footprint.GetLayer())
                    virt_footprint.SetPosition(pad.GetPosition())
                    virt_footprint.SetValue(footprint.GetValue())
                    virt_footprint.Value().SetVisible(False)
                    pads_as_fp.append(virt_footprint)

                self.board.Remove(footprint)

        for fp in pads_as_fp:
            self.board.Add(fp)

    def create_edge_cuts(self, track_pos: list, offset: list[float]) -> list:
        """Create shape for Sliced PCB."""
        points = np.vstack([track_pos[0], track_pos[1]])

        max_track_x: Any = None
        min_track_x: Any = None
        max_track_y: Any = None
        min_track_y: Any = None

        # Find max coordinates of track
        for x, y in points:
            if max_track_x is None or x > max_track_x:
                max_track_x = x
            if min_track_x is None or x < min_track_x:
                min_track_x = x
            if max_track_y is None or y > max_track_y:
                max_track_y = y
            if min_track_y is None or y < min_track_y:
                min_track_y = y

        max_track_x = max_track_x + offset[0]
        min_track_x = min_track_x - offset[1]
        max_track_y = max_track_y + offset[2]
        min_track_y = min_track_y - offset[3]

        edges = [max_track_x, min_track_x, max_track_y, min_track_y]

        self.footprint_to_pad()
        new_edges = self.remove_footprints(edges)

        # Create GND zones with offset left for simulation ports
        zone_offset = 0.8
        zone_corners = [
            new_edges[0] + zone_offset,
            new_edges[1] - zone_offset,
            new_edges[2] + zone_offset,
            new_edges[3] - zone_offset,
        ]

        sp_track_termination = self.cut_tracks(new_edges)
        self.resize_zones(zone_corners)

        mask_layers = [pcbnew.F_Mask, pcbnew.B_Mask]

        # Remove all drawings except mask_layers
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer() not in mask_layers:
                self.board.Delete(drawing)

        # Create offset for edge cuts
        edge_offset = 1.0
        edge_corners = [
            [float(new_edges[1] - edge_offset), float(new_edges[3] - edge_offset)],
            [float(new_edges[0] + edge_offset), float(new_edges[2] + edge_offset)],
        ]

        segment = pcbnew.PCB_SHAPE(self.board)
        self.board.Add(segment)
        segment.SetShape(pcbnew.S_RECT)
        segment.SetLayer(pcbnew.Edge_Cuts)
        segment.SetStart(pcbnew.VECTOR2I_MM(edge_corners[0][0], edge_corners[0][1]))
        segment.SetEnd(pcbnew.VECTOR2I_MM(edge_corners[1][0], edge_corners[1][1]))

        # Remove mask layers out of EdgeCuts
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer() in mask_layers:
                if not segment.GetBoundingBox().Contains(drawing.GetPosition()):
                    self.board.Delete(drawing)

        temporary_aux_offset = 0.025

        self.board.GetDesignSettings().SetAuxOrigin(
            pcbnew.VECTOR2I_MM(
                edge_corners[0][0] - temporary_aux_offset,
                edge_corners[1][1] + temporary_aux_offset,
            )
        )

        return sp_track_termination

    @staticmethod
    def calculate_intersection(
        edge_start: list, edge_end: list, track_start: list, track_end: list, track_beg: str
    ) -> tuple[Any, Any]:
        """Calculate intersection point of two straight lines."""
        # Calculate matrixes for edges #
        a_xy = np.array([[edge_start[0], edge_start[1]], [edge_end[0], edge_end[1]]])
        a_x = np.array([[edge_start[0], 1], [edge_end[0], 1]])
        a_y = np.array([[edge_start[1], 1], [edge_end[1], 1]])

        # Calculate matrixes for tracks #
        b_xy = np.array([[track_start[0], track_start[1]], [track_end[0], track_end[1]]])
        b_x = np.array([[track_start[0], 1], [track_end[0], 1]])
        b_y = np.array([[track_start[1], 1], [track_end[1], 1]])

        # Calculate determinants #
        det_b_xy = np.linalg.det(b_xy)
        det_b_x = np.linalg.det(b_x)
        det_b_y = np.linalg.det(b_y)
        det_a_xy = np.linalg.det(a_xy)
        det_a_x = np.linalg.det(a_x)
        det_a_y = np.linalg.det(a_y)

        # Temp matrices #
        c1 = np.array([[det_a_xy, det_a_x], [det_b_xy, det_b_x]])
        c2 = np.array([[det_a_x, det_a_y], [det_b_x, det_b_y]])
        c3 = np.array([[det_a_xy, det_a_y], [det_b_xy, det_b_y]])

        det_c1 = np.linalg.det(c1)
        det_c2 = np.linalg.det(c2)
        det_c3 = np.linalg.det(c3)

        # Points
        if track_beg == "start":
            if det_c3 == 0:
                p_x = track_start[0]
                p_y = track_start[1]
            else:
                p_x = det_c1 / det_c2
                p_y = det_c3 / det_c2
        elif track_beg == "end":
            if det_c3 == 0:
                p_x = track_end[0]
                p_y = track_end[1]
            else:
                p_x = det_c1 / det_c2
                p_y = det_c3 / det_c2

        return p_x, p_y

    @staticmethod
    def calculate_orientation(start_track: tuple[Any, Any], end_track: tuple[Any, Any]) -> int:
        """Return orientation."""
        return int(round(Point(*start_track).rotation(Point(*end_track))))

    @staticmethod
    def is_in_circle(center: list, radius: float, x: int, y: int) -> bool:
        """Check if is located in field of radius of the defined circle."""
        d = np.sqrt((center[0] - x) ** 2 + (center[1] - y) ** 2)
        return d <= radius

    @staticmethod
    def pad_exit_angle(pad: pcbnew.Pad, track: pcbnew.PCB_TRACK) -> int:
        """Get trace at which trace exits pad."""
        pad_pos = pcbnew.ToMM(pad.GetCenter())
        far_track_end = track.GetStart() if pad.HitTest(track.GetEnd()) else track.GetEnd()
        far_track_end = far_track_end if not isinstance(track, pcbnew.PCB_ARC) else track.GetMid()
        return PCBSlice.calculate_orientation(pad_pos, pcbnew.ToMM(far_track_end))

    def get_port_pads(
        self, pads: list, included_pads: list, excluded_pads: list, net_name: List[str] | Set[str]
    ) -> List[PortPad]:
        """Get parameters of pads necessary for port placement."""
        layers = [pcbnew.F_Cu, pcbnew.B_Cu]
        pad_ports = []
        tracks = [track for track in self.board.GetTracks() if track.GetNetname() in net_name]
        for pad in pads:
            if pad.GetNetname() not in net_name:
                continue
            b_cu, f_cu = self.board.GetLayerID("B.Cu"), self.board.GetLayerID("F.Cu")
            pad_layer = pad.GetPrincipalLayer()
            pad_layer = pad_layer if not pad.IsFlipped() else (b_cu if pad_layer == f_cu else f_cu)
            if pad_layer not in layers:
                continue
            multi_connected = False
            pad_touching_tracks = [
                track
                for track in tracks
                if track.GetLayer() == pad_layer
                and (pad.HitTest(track.GetStart()) + pad.HitTest(track.GetEnd())) == 1
                or (isinstance(track, pcbnew.PCB_VIA) and pad.HitTest(track.GetStart()) and pad.HitTest(track.GetEnd()))
            ]
            pad_pos = pcbnew.ToMM(pad.GetCenter())
            if pad_touching_tracks:
                out_track = max(pad_touching_tracks, key=pcbnew.PCB_TRACK.GetLength)
                track_angles = [PCBSlice.pad_exit_angle(pad, track) for track in pad_touching_tracks]
                orientation = PCBSlice.pad_exit_angle(pad, out_track)
                if any(abs(ang - orientation) > 30 for ang in track_angles):
                    multi_connected = True
            else:
                # Pad has no connected traces OR traces are passthrough
                multi_connected = True
                orientation = pad.GetOrientation().AsDegrees()

            size = Point(*pcbnew.ToMM(pad.GetSize()))
            pad_orientation = pad.GetOrientation().AsDegrees()
            if size.x > size.y:
                size = Point(size.y, size.x)
                pad_orientation += 90
            if pad_orientation > 360:
                pad_orientation -= 360

            orientation = 45 * round(orientation / 45)
            orientation = orientation if orientation > 0 else orientation + 360
            ort_angles = [0, 90, 180, 270, 360]
            ort_case = orientation in ort_angles and pad_orientation not in ort_angles
            optimality_rating = 0
            pad_shape = pad.GetShape()
            rect_shapes = [pcbnew.PAD_SHAPE_CHAMFERED_RECT, pcbnew.PAD_SHAPE_RECTANGLE, pcbnew.PAD_SHAPE_ROUNDRECT]
            optimality_rating += pad_shape not in rect_shapes
            optimality_rating += (pad_orientation not in ort_angles) + (ort_case or orientation not in ort_angles)

            if (
                (len(included_pads) and pad.GetParent().GetReference() in included_pads)
                or (len(excluded_pads) and pad.GetParent().GetReference() not in excluded_pads)
                or (len(included_pads) == 0 and len(excluded_pads) == 0)
            ):
                pad_ports.append(
                    PortPad(
                        Point(*pad_pos),
                        pad.IsFlipped(),
                        orientation,
                        pad_orientation,
                        size,
                        multi_connected,
                        optimality_rating,
                        ort_case,
                    )
                )

        single_connected_count = sum([1 for pp in pad_ports if not pp.multi_connected])
        if single_connected_count >= 2:
            # We have enough potential ports so We can ignore pads that have multiple traces connected,
            # as they are most likely passthrough and not endpoints
            pad_ports = list(filter(lambda x: not x.multi_connected, pad_ports))
        return pad_ports

    def find_next_orthogonal(self, current_track: pcbnew.PCB_TRACK) -> pcbnew.PCB_TRACK:
        """Find next orthogonal track that can contain Simulation Port."""
        logger.debug(f"Finding next orthogonal track to {current_track.GetNetname()}")

        new_track = None
        last_end_crd = []
        last_start_crd = []

        tracks = self.board.GetTracks()
        i = 0
        deep = 0

        while i < len(tracks):
            # if tracks[i].GetNetname() == current_track.GetNetname():
            if tracks[i].GetNetCode() == current_track.GetNetCode():
                s_tr = tracks[i].GetStart()
                e_tr = tracks[i].GetEnd()

                curr_s_tr = current_track.GetStart()
                curr_e_tr = current_track.GetEnd()

                rules = (
                    (s_tr == curr_e_tr and e_tr != curr_s_tr)
                    or (e_tr == curr_s_tr and s_tr != curr_e_tr)
                    or (s_tr == curr_s_tr and e_tr != curr_e_tr)
                    or (e_tr == curr_e_tr and s_tr != curr_s_tr)
                )

                if rules:
                    if self.calculate_orientation(s_tr, e_tr) % 90 == 0:
                        new_track = tracks[i]
                        logger.debug("Track found!")
                        break
                    if deep >= 5:
                        deep = 0
                        logger.debug("Track not found!")
                        break
                    last_start_crd.append(s_tr)
                    last_end_crd.append(e_tr)
                    # curr_s_tr = s_tr
                    # curr_e_tr = e_tr
                    current_track = tracks[i]
                    deep += 1
                    i = 0
                    continue

                if (e_tr in last_end_crd) and (s_tr in last_start_crd):
                    i += 1
                    continue
            i += 1
        return new_track

    @staticmethod
    def euclidean_distance(pad_pos: pcbnew.wxPoint, track_pos: np.ndarray[Any, np.dtype[Any]]):
        """Return value of the distance between two points."""
        pad_pos = np.array(pcbnew.ToMM(pad_pos))
        track_pos = np.array(track_pos)

        return np.linalg.norm(pad_pos - track_pos)

    def terminate_track(
        self,
        x: float,
        y: float,
        theta: int,
        width_t: float,
        track: pcbnew.PCB_TRACK,
        track_beg: str,
    ) -> int:
        """Terminate track with SP or GND via."""
        if re.search(self.ci_dict(), str(track.GetNetClassName())):
            if theta % 90 != 0:
                otrack = self.find_next_orthogonal(track)
                if otrack is not None:
                    if track_beg == "end":
                        x, y = pcbnew.ToMM(otrack.GetEnd())
                        theta = self.calculate_orientation(otrack.GetEnd(), otrack.GetStart())
                    if track_beg == "start":
                        x, y = pcbnew.ToMM(otrack.GetStart())
                        theta = self.calculate_orientation(otrack.GetStart(), otrack.GetEnd())

            match theta:
                case 0:
                    y = y + 0.5
                case 90 | -270:
                    x = x + 0.5
                case -90 | 270:
                    x = x - 0.5
                case -180:
                    y = y - 0.5
                case -45 | -315:
                    y = y + 0.5
                    theta = 0
                case -135 | -225:
                    y = y - 0.5
                    theta = 180

            orient_eda = pcbnew.EDA_ANGLE(theta, pcbnew.DEGREES_T)
            self.SimPortFootprint.SetOrientation(orient_eda)

            self.SimPortFootprint.SetPosition(pcbnew.VECTOR2I_MM(float(x), float(y)))
            self.SimPortFootprint.SetReference(f"SP{self.static_sp_index}")
            sp_instance = self.SimPortFootprint.Duplicate()
            self.board.Add(sp_instance)
            self.static_sp_index += 1
            return 0

        new_via = pcbnew.PCB_VIA(self.board)
        new_via.SetDrill(50000)  # 0.05 mm
        new_via.SetViaType(pcbnew.VIATYPE_BLIND_BURIED)
        new_via.SetWidth(width_t)
        new_via.SetNet(self.GNDnet)
        new_via.SetPosition(pcbnew.VECTOR2I_MM(float(x), float(y)))
        self.board.Add(new_via)
        return 1

    def replace_resistors_and_capacitors(self) -> None:
        """Replace every R0 and Capacitor with an track."""
        pattern = "((C_\d*[munp])|(R_0R))_.*"
        defined_width = 150000

        pad2: pcbnew.PCB_PAD_T = 0
        pad1: pcbnew.PCB_PAD_T = 0

        for component1 in self.board.GetFootprints():
            for component2 in self.board.GetFootprints():
                new_track = pcbnew.PCB_TRACK(self.board)
                if component1.GetReference() == component2.GetReference():
                    if re.search(pattern, component1.GetValue()):
                        if component1.GetAttributes() & 10 != 10:
                            # print(component1.Pads()[0].GetNumber(), component2.Pads()[0].GetNumber())
                            if component1.Pads()[0].GetNumber() == "1":
                                pad1 = component1.Pads()[0]
                                if component2.Pads()[0].GetNumber() == "2":
                                    pad2 = component2.Pads()[0]
                                    if (pad1.GetNetname() != "GND") and (pad2.GetNetname() != "GND"):
                                        new_track.SetWidth(defined_width)
                                        new_track.SetLayer(pad1.GetLayer())
                                        new_track.SetStart(component2.GetPosition())
                                        new_track.SetEnd(component1.GetPosition())
                                        new_track_d = new_track.Duplicate()
                                        self.board.Add(new_track_d)

    def place_simulation_port(self, portpads: List[PortPad]) -> tuple[list[int], list[Any]]:
        """Place Simulation Ports on the beginning and ending of the board."""
        index_list = []
        flip_list = []
        all_signal_pads = [
            Point(*pcbnew.ToMM(pad.GetCenter())) for pad in self.board.GetPads() if pad.GetNetname() in self.netname
        ]
        for pp in portpads:
            x = pp.position.x
            y = pp.position.y
            orient = pp.port_rotation
            signal_pads = [pad for pad in all_signal_pads if pad != pp.position]
            closest_ang = 0.0
            if len(signal_pads) >= 2:
                closest_pad = min(signal_pads, key=lambda x: x.distance(pp.position))
                closest_ang = pp.position.rotation(closest_pad)

            dy = 0.5 * pp.size.y * (1 + 1 / const.SQRT2) - 0.5 * pp.size.x / const.SQRT2
            dx = 0.5 * pp.size.y / const.SQRT2 - 0.5 * pp.size.x / const.SQRT2
            closest_ang = closest_ang if closest_ang > 0 else closest_ang + 360
            if pp.ort_case:
                pad_port_rot_diff = min(abs(orient - pp.pad_rotation - 360), abs(orient - pp.pad_rotation))
                if pad_port_rot_diff > 90:
                    pp.pad_rotation += 180
                    if pp.pad_rotation > 360:
                        pp.pad_rotation -= 360
                if pp.pad_rotation > orient:
                    orient += 45
                else:
                    orient -= 45
            match orient:
                case 0 | 360:
                    y += pp.size.y / 2
                    orient = 0
                case 180:
                    y -= pp.size.y / 2
                    orient = 180
                case 90:
                    x += pp.size.y / 2
                    orient = 90
                case 270:
                    x -= pp.size.y / 2
                    orient = 270
                case _:
                    pp.size.y /= 2
                    pp.size.x *= const.SQRT2
                    flip_y = 1
                    flip_x = 1
                    if 270 >= orient >= 90:
                        flip_y = -1
                    if orient >= 180:
                        flip_x = -1
                    omap1 = {45: 0, 135: 180, 225: 180, 315: 0}
                    omap2 = {45: 90, 135: 90, 225: 270, 315: 270}

                    if (flip_y == -1) ^ (270 > closest_ang > 90):
                        x += flip_x * dy
                        y += flip_y * dx
                        orient = omap2[orient]
                    else:
                        y += flip_y * dy
                        x += flip_x * dx
                        orient = omap1[orient]

            orient_eda = pcbnew.EDA_ANGLE(orient, pcbnew.DEGREES_T)

            sp_instance = self.SimPortFootprint.Duplicate()
            sp_instance.SetPosition(pcbnew.VECTOR2I_MM(x, y))
            sp_instance.SetReference(f"SP{self.static_sp_index}")

            segment = pcbnew.PCB_SHAPE(self.board)
            segment.SetShape(pcbnew.S_RECT)
            segment.SetLayer(pcbnew.Eco1_User)
            segment.SetWidth(pcbnew.FromMM(0.01))
            segment.SetStart(pcbnew.VECTOR2I_MM(x - pp.size.x / 2, y))
            segment.SetEnd(pcbnew.VECTOR2I_MM(x + pp.size.x / 2, y - pp.size.y))
            seg2 = segment.Duplicate()
            sp_instance.Add(segment)
            segment.SetStart(pcbnew.VECTOR2I_MM(x - 1.2 * pp.size.x / 2, y + 0.1 * pp.size.y))
            segment.SetEnd(pcbnew.VECTOR2I_MM(x + 1.2 * pp.size.x / 2, y - 1.1 * pp.size.y))
            seg2.SetLayer(pcbnew.Eco2_User)
            sp_instance.Add(seg2)
            sp_instance.SetOrientation(orient_eda)
            self.board.Add(sp_instance)
            for fp in self.board.GetFootprints():
                if (
                    not fp.Pads().empty()
                    and fp.Pads()[0].GetNetname() not in self.netname
                    and fp.Pads()[0].HitTest(
                        sp_instance.GetBoundingBox(False, False),
                        False,
                    )
                ):
                    self.board.Remove(fp)

            index_list.append(self.static_sp_index)
            flip_list.append(pp.flipped)
            pp.idx = self.static_sp_index
            self.static_sp_index += 1

        return index_list, flip_list

    def save_slice(self, path: str) -> None:
        """Save .kicad_pcb file of crated slice."""
        self.board.Save(path)

    def get_num_layers(self, layer_name: str) -> tuple[Any, Any]:
        """Get number of layers."""
        if layer_name == "B.Cu":
            return (
                self.board.GetCopperLayerCount() - 1,
                self.board.GetCopperLayerCount(),
            )

        return self.board.GetLayerID(layer_name), self.board.GetCopperLayerCount()

    def rename_layers(self) -> None:
        """Rename Layers to standard format of In{l}.Cu."""
        copper_layer_count = self.board.GetCopperLayerCount()
        for cnt in range(1, copper_layer_count - 1):
            self.board.SetLayerName(cnt, f"In{cnt}.Cu")

    def find_nearest_to_designated_net(
        self,
        start_pos: list,
        end_pos: list,
        net_offset: float,
        number_of_common_points: int,
        protected_list: list,
    ) -> list:
        """Find nearest nets to designated one basing on provided information.

        There is a possibility to define area of existing propable neighbour or even
        possibility to define name if it in the config file
        """
        offset = net_offset
        common_points_number = number_of_common_points
        protected_nets = protected_list

        tracks = [track for track in self.board.GetTracks() if (track.GetNetname() not in self.netname)]

        num_of = 0
        i = 0

        names = []

        if len(protected_list) > 0:
            for net in protected_nets:
                names.append(net)

        my_dict: dict[str, float] = {}

        max_value = None
        min_value_x = None
        min_value_y = None
        oldname: str = ""

        for track in tracks:
            track_name = track.GetNetname()
            for n in range(0, len(start_pos)):
                orient = self.calculate_orientation(start_pos[n], end_pos[n])
                xs = start_pos[n][0]
                ys = start_pos[n][1]
                xe = end_pos[n][0]
                ye = end_pos[n][1]

                match orient:
                    case 0 | -180:
                        rule = (
                            (xs - offset < pcbnew.ToMM(track.GetEnd()[0]) < xs + offset)
                            or (xs - offset < pcbnew.ToMM(track.GetStart()[0]) < xs + offset)
                        ) and (
                            (ys < pcbnew.ToMM(track.GetEnd()[1]) < ye)
                            or (ys < pcbnew.ToMM(track.GetStart()[1]) < ye)
                            or (ye < pcbnew.ToMM(track.GetEnd()[1]) < ys)
                            or (ye < pcbnew.ToMM(track.GetStart()[1]) < ys)
                        )

                        if np.abs(xs - pcbnew.ToMM(track.GetStart()[0])) < np.abs(xs - pcbnew.ToMM(track.GetEnd()[0])):
                            diff_x = np.abs(xs - pcbnew.ToMM(track.GetStart()[0]))
                        else:
                            diff_x = np.abs(xs - pcbnew.ToMM(track.GetEnd()[0]))
                        diff_y = 255

                    case -90 | -270:
                        rule = (
                            (ys - offset < pcbnew.ToMM(track.GetEnd()[1]) < ys + offset)
                            or (ys - offset < pcbnew.ToMM(track.GetStart()[1]) < ys + offset)
                        ) and (
                            (xs < pcbnew.ToMM(track.GetEnd()[0]) < xe)
                            or (xs < pcbnew.ToMM(track.GetStart()[0]) < xe)
                            or (xe < pcbnew.ToMM(track.GetEnd()[0]) < xs)
                            or (xe < pcbnew.ToMM(track.GetStart()[0]) < xs)
                        )

                        if np.abs(ys - pcbnew.ToMM(track.GetStart()[1])) < np.abs(ys - pcbnew.ToMM(track.GetEnd()[1])):
                            diff_y = np.abs(ys - pcbnew.ToMM(track.GetStart()[1]))
                        else:
                            diff_y = np.abs(ys - pcbnew.ToMM(track.GetEnd()[1]))
                        diff_x = 255

                    case _:
                        rule = None

                if rule:
                    if oldname == track_name:
                        num_of += 1
                        if min_value_x is None or diff_x < min_value_x:
                            min_value_x = diff_x
                        if min_value_y is None or diff_y < min_value_y:
                            min_value_y = diff_y
                        if max_value is None or num_of > max_value:
                            max_value = num_of

                if oldname is not track_name and max_value is not None:
                    my_dict[oldname] = max_value
                    num_of = 0
                    max_value = None

            oldname = track.GetNetname()

        for i in range(len(my_dict)):
            # print(list(my_dict.values())[i], list(my_dict.keys())[i])
            if list(my_dict.values())[i] >= common_points_number:
                names.append(list(my_dict.keys())[i])

        for track in tracks:
            if track.GetNetname() not in names and track.GetNetname() != "GND":
                self.board.Delete(track)

        return names

    def remove_pads(self, condition: list) -> None:
        """Remove pads from board."""
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                if condition is None:
                    self.board.Remove(footprint)
                else:
                    if pad.GetNetname() not in condition and pad.GetNetname() not in self.netname:
                        self.board.Remove(footprint)

    def renumerate_simulation_ports(self) -> list[int]:
        """Renumerate ports that were changed on the board."""
        sp_index = 1
        old_names: list[int] = []
        sp_list = []
        for fp in self.board.GetFootprints():
            if re.search("SP\d+", str(fp.GetReference())):
                # print(fp.GetReference())
                sp_list.append(fp)

        sp_list.sort(key=lambda x: self.sort_key(x.GetReference()))

        for sp in sp_list:
            old_names.append(int(re.findall("\d+", str(sp.GetReference()))[0]))
            # print(old_names[sp_index])
            # print(sp.GetReference())
            sp.SetReference(f"SP{sp_index}")
            sp_index += 1

        return old_names

    def sort_key(self, ref: str) -> Any:
        """Sort by reference number."""
        ref_num = "".join(filter(str.isdigit, ref))
        return int(ref_num) if ref_num else ref

    def purge_all_but_designated(self) -> None:
        """Remove all elements from board, except designated nets and Edge Cuts Layer."""
        # Init variables
        to_remove = []

        # Iterate through tracks and remove all, except designated ones
        for track in self.board.GetTracks():
            if track.GetNetname() not in self.netname:
                self.board.Delete(track)

        # Append footprints to remove
        for fp in self.board.Footprints():
            if re.search("SP\d+", str(fp.GetReference())):
                fp.SetReference(int(re.findall("\d+", str(fp.GetReference()))[0]))
                fp.Reference().SetVisible(True)
            else:
                to_remove.append(fp)

        # Append zones to remove
        for zone in self.board.Zones():
            if zone.GetLayer() != pcbnew.Edge_Cuts:
                to_remove.append(zone)

        # Append drawings to remove
        for d in self.board.GetDrawings():
            if d.GetLayer() != pcbnew.Edge_Cuts:
                to_remove.append(d)

        # Remove elements from list
        for element in to_remove:
            self.board.Delete(element)

    def edit_netclass_clearance(self, clearance_value: float) -> None:
        """Change netclass clearance min value."""
        netclasses = self.board.GetAllNetClasses().items()
        for _, netclass in netclasses:
            netclass.SetClearance(pcbnew.FromMM(clearance_value))

    def change_zone_properties(self) -> None:
        """Change properties of the zones."""
        zones = self.board.Zones()

        for zone in zones:
            zone.SetMinThickness(pcbnew.FromMM(0.025))
            zone.SetLocalClearance(pcbnew.FromMM(0.005))

    def refill_zones(self) -> None:
        """Refill existing zones."""
        filler = pcbnew.ZONE_FILLER(self.board)
        filler.Fill(self.board.Zones())


def netclass_list(path: str) -> None:
    """Print out netclasses."""
    net_num = 0
    board = pcbnew.LoadBoard(path)
    for netclass in board.GetAllNetClasses():
        print(f"NetClass {net_num}. |- {netclass}")
        show_nets(path, str(netclass))
        net_num += 1
    sys.exit()


def show_nets(path: str, netclass: str) -> None:
    """Print out nets."""
    net_num = 0
    board = pcbnew.LoadBoard(path)
    for _, netinfo in board.GetNetsByNetcode().items():
        if netinfo.GetNetClassName() == netclass:
            print(f"\t Net {net_num}. |- {netinfo.GetNetname()}")
            net_num += 1
