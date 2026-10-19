"""Library file containing class for generating and editing netslices."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, List, Set, Optional
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
    multi_connected: bool
    """True if more than one trace that exits pad"""
    net: str
    """Port net name"""
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

    def get_des_pads_points(self) -> list:
        """Return designated track pads."""
        pad_points = []
        for net_n in self.netname:
            for pad in self.board.GetPads():
                if pad.GetNetname() == net_n:
                    bbox = pad.GetBoundingBox()
                    start_x = pcbnew.ToMM(bbox.GetLeft())
                    start_y = pcbnew.ToMM(bbox.GetTop())
                    end_x = pcbnew.ToMM(bbox.GetRight())
                    end_y = pcbnew.ToMM(bbox.GetBottom())
                    pad_points.append((start_x, start_y))
                    pad_points.append((end_x, end_y))

        return pad_points

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

    @staticmethod
    def get_netclass_impedance(netclass: str) -> tuple[float, float | None]:
        impedance_str = re.search(r"^\d+", netclass)
        assert impedance_str is not None
        imp = float(impedance_str.group())
        if "se" in netclass.lower():
            return imp, None
        return 50, imp

    def get_selected_track_info(self, tracks: list[Any]) -> list:
        """Give information about track. It returns.

        * length of the net,
        * width of the net,
        * starting position of the tracks of the net,
        * ending position of the tracks of the net,
        * nominal impedance.
        * netclass of the net
        """
        track_length = 0
        track_widths: float = 0
        start_pos = []
        end_pos = []
        impedance: float = 0
        diff_impedance = None
        interface = None

        try:
            for track in tracks:
                if isinstance(track, pcbnew.PCB_VIA):
                    continue
                start_pos.append(list(pcbnew.ToMM(track.GetStart())))
                end_pos.append(list(pcbnew.ToMM(track.GetEnd())))

                track_length += track.GetLength()
                track_widths = track.GetWidth()
                impedance_str = re.search(r"^\d+", track.GetNetClassName())
                main_netclass = track.GetNetClassName().partition(",")[0]
                interface = main_netclass.partition("_")[2] or None

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
            interface,
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
        [max_edge_x, min_edge_x, max_edge_y, min_edge_y] = [pcbnew.FromMM(float(e)) for e in edges]

        zones = self.board.Zones()
        to_remove = []

        def clip_point(polys: pcbnew.SHAPE_POLY_SET, poly_idx: int, corner_idx: int) -> None:
            [point_x, point_y] = polys.COutline(poly_idx).GetPoint(corner_idx)
            if point_x > max_edge_x:
                point_x = max_edge_x
            if point_x < min_edge_x:
                point_x = min_edge_x
            if point_y > max_edge_y:
                point_y = max_edge_y
            if point_y < min_edge_y:
                point_y = min_edge_y

            polys.COutline(poly_idx).SetPoint(corner_idx, pcbnew.VECTOR2I(point_x, point_y))

        for zone in zones:
            zone.SetNet(self.GNDnet)
            polys = zone.Outline()
            for poly_idx in range(polys.OutlineCount()):
                for corner_idx in range(polys.COutline(poly_idx).PointCount()):
                    clip_point(polys, poly_idx, corner_idx)
            if zone.CalculateOutlineArea() < 1e-5:
                to_remove.append(zone)
                continue

            for polys in (zone.GetFilledPolysList(layer) for layer in zone.GetLayerSet().CuStack()):
                pidx_to_remove = []
                for poly_idx in range(polys.OutlineCount()):
                    for corner_idx in range(polys.COutline(poly_idx).PointCount()):
                        clip_point(polys, poly_idx, corner_idx)
                    polys.RemoveNullSegments()
                    polys.SimplifyOutlines()
                    if polys.COutline(poly_idx).PointCount() == 0:
                        pidx_to_remove.append(poly_idx)
                for idx in reversed(pidx_to_remove):
                    polys.RemoveOutline(idx)

            if zone.CalculateFilledArea() < 1e-5:
                to_remove.append(zone)
        for zone in to_remove:
            self.board.Remove(zone)

    def to_gnd(self, track: pcbnew.PCB_TRACK) -> None:
        """Set netclass of net to GND."""
        if re.search(self.ci_dict(), str(track.GetNetClassName())) is None:
            track.SetNet(self.GNDnet)

    @staticmethod
    def clip_segment_to_bbox(
        seg: tuple[Point, Point], bbox: tuple[float, float, float, float]
    ) -> tuple[Point, Point] | None:
        """
        Clip segment  `seg` to an axis-aligned bounding box.

        Args:
            seg: (Point(x0, y0), Point(x1, y1)) segment to clip
            bbox: (xmin, ymin, xmax, ymax)

        Returns:
            (Point(x0, y0), Point(x1, y1)) for the clipped segment,
            or None if entirely outside.
        """
        xmin, ymin, xmax, ymax = bbox

        dx = seg[1].x - seg[0].x
        dy = seg[1].y - seg[0].y

        t_min, t_max = 0.0, 1.0

        for p, q in [
            (-dx, seg[0].x - xmin),
            (dx, xmax - seg[0].x),
            (-dy, seg[0].y - ymin),
            (dy, ymax - seg[0].y),
        ]:
            if p == 0:
                if q < 0:
                    return None
                continue

            r = q / p

            if p < 0:
                t_min = max(t_min, r)
            else:
                t_max = min(t_max, r)

            if t_min > t_max:
                return None

        start = Point(seg[0].x + t_min * dx, seg[0].y + t_min * dy)
        end = Point(seg[0].x + t_max * dx, seg[0].y + t_max * dy)

        return start, end

    def cut_tracks(self, edges: list) -> list:
        """Remove tracks existing out of the EdgeCuts layer."""
        sp_tracks = []

        for track in self.board.GetTracks():
            self.to_gnd(track)

            start, end = Point(*pcbnew.ToMM(track.GetStart())), Point(*pcbnew.ToMM(track.GetEnd()))

            width = track.GetFrontWidth() if isinstance(track, pcbnew.PCB_VIA) else track.GetWidth()
            track_radius = pcbnew.ToMM(width) / 2
            [xmax, xmin, ymax, ymin] = edges

            xmax -= track_radius
            ymax -= track_radius
            xmin += track_radius
            ymin += track_radius

            clipped_trace = PCBSlice.clip_segment_to_bbox((start, end), (xmin, ymin, xmax, ymax))

            if not clipped_trace:
                self.board.Delete(track)
                continue

            new_start, new_end = clipped_trace
            track.SetStart(pcbnew.VECTOR2I_MM(float(new_start.x), float(new_start.y)))
            track.SetEnd(pcbnew.VECTOR2I_MM(float(new_end.x), float(new_end.y)))
            if new_start != start:
                if self.terminate_track(start.x, start.y, track.GetWidth(), track) == 0:
                    sp_tracks.append(track)
            if new_end != end:
                if self.terminate_track(end.x, end.y, track.GetWidth(), track) == 0:
                    sp_tracks.append(track)

        return sp_tracks

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

        for footprint in self.board.GetFootprints():
            bbox = footprint.GetFpPadsLocalBbox()
            start_x = pcbnew.ToMM(bbox.GetLeft())
            start_y = pcbnew.ToMM(bbox.GetTop())
            end_x = pcbnew.ToMM(bbox.GetRight())
            end_y = pcbnew.ToMM(bbox.GetBottom())
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
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                virt_footprint = pcbnew.FOOTPRINT(self.board)
                new_pad = pcbnew.PAD(pad)
                new_pad.SetPos(pcbnew.VECTOR2I(0, 0))  # Set pad position to origin of the footprint
                if re.search(self.ci_dict(), str(pad.GetNetClassName())) is None:
                    new_pad.SetNet(self.GNDnet)
                virt_footprint.Add(new_pad)
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
        points = np.vstack([track_pos[0], track_pos[1], np.array(track_pos[2], dtype=float).reshape(-1, 2)])

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
        edge_bbox = self.board.GetBoardEdgesBoundingBox()
        edges_org = [
            pcbnew.ToMM(edge_bbox.GetRight()),
            pcbnew.ToMM(edge_bbox.GetLeft()),
            pcbnew.ToMM(edge_bbox.GetBottom()),
            pcbnew.ToMM(edge_bbox.GetTop()),
        ]

        edges = [max_track_x, min_track_x, max_track_y, min_track_y]
        func = [min, max, min, max]
        edges = [f(a, b) for f, a, b in zip(func, edges_org, edges, strict=True)]

        self.footprint_to_pad()
        new_edges = self.remove_footprints(edges)

        sp_track_termination = self.cut_tracks(new_edges)
        self.resize_zones(new_edges)

        mask_layers = [pcbnew.F_Mask, pcbnew.B_Mask]

        # Remove all drawings except mask_layers
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer() not in mask_layers:
                self.board.Delete(drawing)

        ec = [float(f(a, b)) for f, a, b in zip(func, edges_org, new_edges, strict=True)]
        edge_corners = [[ec[1], ec[3]], [ec[0], ec[2]]]

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
    def calculate_orientation(start_track: tuple[Any, Any], end_track: tuple[Any, Any]) -> int:
        """Return orientation."""
        return int(round(Point(*start_track).rotation(Point(*end_track))))

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
                if not [t for t in tracks if (pad.HitTest(t.GetStart()) + pad.HitTest(t.GetEnd())) == 1]:
                    # no pads on other layer too
                    multi_connected = True

            if (
                (len(included_pads) and pad.GetParent().GetReference() in included_pads)
                or (len(excluded_pads) and pad.GetParent().GetReference() not in excluded_pads)
                or (len(included_pads) == 0 and len(excluded_pads) == 0)
            ):
                pad_ports.append(
                    PortPad(
                        Point(*pad_pos),
                        pad.IsFlipped(),
                        multi_connected,
                        pad.GetNetname(),
                    )
                )

        single_connected_count = sum([1 for pp in pad_ports if not pp.multi_connected])
        if single_connected_count >= 2:
            # We have enough potential ports so We can ignore pads that have multiple traces connected,
            # as they are most likely passthrough and not endpoints
            pad_ports = list(filter(lambda x: not x.multi_connected, pad_ports))
        return pad_ports

    def replace_resistors_and_capacitors(self) -> None:
        """Replace every R0 and Capacitor with an track."""
        pattern = r"((C_\d*[munp])|(R_0R))_.*"
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

    def place_sim_port_fp(self, x: float, y: float) -> None:
        self.SimPortFootprint.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        self.SimPortFootprint.SetReference(f"SP{self.static_sp_index}")
        self.board.Add(self.SimPortFootprint.Duplicate(False))
        self.static_sp_index += 1

    def terminate_track(self, x: float, y: float, width_t: float, track: pcbnew.PCB_TRACK) -> int:
        """Terminate track with SP or GND via."""
        if re.search(self.ci_dict(), str(track.GetNetClassName())):
            self.place_sim_port_fp(x, y)
            return 0

        new_via = pcbnew.PCB_VIA(self.board)
        new_via.SetDrill(50000)  # 0.05 mm
        new_via.SetViaType(pcbnew.VIATYPE_BURIED)
        new_via.SetFrontWidth(width_t)
        new_via.SetNet(self.GNDnet)
        new_via.SetPosition(pcbnew.VECTOR2I_MM(float(x), float(y)))
        self.board.Add(new_via)
        return 1

    def place_simulation_port(self, portpads: List[PortPad]) -> list[int]:
        """Place Simulation Ports on the beginning and ending of the board."""
        index_list = []
        for pp in portpads:
            index_list.append(self.static_sp_index)
            pp.idx = self.static_sp_index
            self.place_sim_port_fp(pp.position.x, pp.position.y)

        return index_list

    def save_slice(self, path: str) -> None:
        """Save .kicad_pcb file of crated slice."""
        self.board.Save(path)

    def get_num_layers(self, layer_name: str) -> tuple[Any, Any]:
        """Get number of layers."""
        layer_count = self.board.GetCopperLayerCount()
        if layer_name == "B.Cu":
            return (
                self.board.GetCopperLayerCount() - 1,
                layer_count,
            )
        if layer_name == "F.Cu":
            return 0, layer_count
        return int((self.board.GetLayerID(layer_name) - 2) / 2), layer_count

    def find_nearest_to_designated_net(
        self,
        start_pos: list,
        end_pos: list,
        net_offset: float,
        number_of_common_points: int,
        protected_list: list,
    ) -> None:
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
            if re.search(r"SP\d+", str(fp.GetReference())):
                # print(fp.GetReference())
                sp_list.append(fp)

        sp_list.sort(key=lambda x: self.sort_key(x.GetReference()))

        for sp in sp_list:
            old_names.append(int(re.findall(r"\d+", str(sp.GetReference()))[0]))
            # print(old_names[sp_index])
            # print(sp.GetReference())
            sp.SetReference(f"SP{sp_index}")
            sp_index += 1

        return old_names

    def sort_key(self, ref: str) -> Any:
        """Sort by reference number."""
        ref_num = "".join(filter(str.isdigit, ref))
        return int(ref_num) if ref_num else ref

    def purge_all_but_designated(self, nets: Optional[List[str]] = None) -> None:
        """Remove all elements from board, except designated nets and Edge Cuts Layer."""
        # Init variables
        to_remove = []

        if nets is None:
            nets = self.netname
        # Iterate through tracks and remove all, except designated ones
        for track in self.board.GetTracks():
            if track.GetNetname() not in nets:
                self.board.Delete(track)

        # Append footprints to remove
        for fp in self.board.Footprints():
            if re.search(r"SP\d+", str(fp.GetReference())):
                fp.SetReference(int(re.findall(r"\d+", str(fp.GetReference()))[0]))
                fp.Reference().SetVisible(True)
            else:
                to_remove.append(fp)
                for g in fp.GraphicalItems():
                    if g.GetLayer() == pcbnew.Edge_Cuts:
                        self.board.Add(g.Duplicate())

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
