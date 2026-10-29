"""Library file containing class for generating and editing netslices."""

from __future__ import annotations
from copy import deepcopy

import logging
import re
import sys
from typing import Any, List, Set, Optional
from dataclasses import dataclass, field
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
class BBox:
    """Point defining Bounding box in 2D space."""

    min: Point = field(default_factory=lambda: Point(inf, inf))
    max: Point = field(default_factory=lambda: Point(-inf, -inf))

    def add_point(self, point: Point) -> None:
        """Expand BBox to encompass `point`."""
        self.min.x = min(point.x, self.min.x)
        self.min.y = min(point.y, self.min.y)
        self.max.x = max(point.x, self.max.x)
        self.max.y = max(point.y, self.max.y)

    def in_bbox(self, point: Point) -> bool:
        return self.min.x <= point.x <= self.max.x and self.min.y <= point.y <= self.max.y

    def clip_segment(self, seg: tuple[Point, Point]) -> tuple[Point, Point] | None:
        """
        Clip segment  `seg` to an axis-aligned bounding box.

        Args:
            seg: (Point(x0, y0), Point(x1, y1)) segment to clip
            bbox: (xmin, ymin, xmax, ymax)

        Returns:
            (Point(x0, y0), Point(x1, y1)) for the clipped segment,
            or None if entirely outside.
        """

        dx = seg[1].x - seg[0].x
        dy = seg[1].y - seg[0].y

        t_min, t_max = 0.0, 1.0

        for p, q in [
            (-dx, seg[0].x - self.min.x),
            (dx, self.max.x - seg[0].x),
            (-dy, seg[0].y - self.min.y),
            (dy, self.max.y - seg[0].y),
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

    def extend_by(self, d: float) -> BBox:
        return BBox(Point(self.min.x - d, self.min.y - d), Point(self.max.x + d, self.max.y + d))


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

    def resize_zones(self, bbox: BBox) -> None:
        """Fit sizes of the zones to size of new PCB."""
        edges = (bbox.max.x, bbox.min.x, bbox.max.y, bbox.min.y)
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

    def cut_tracks(self, bbox: BBox) -> list:
        """Remove tracks existing out of the EdgeCuts layer."""
        sp_tracks = []

        for track in self.board.GetTracks():
            start, end = Point(*pcbnew.ToMM(track.GetStart())), Point(*pcbnew.ToMM(track.GetEnd()))

            width = track.GetFrontWidth() if isinstance(track, pcbnew.PCB_VIA) else track.GetWidth()
            track_radius = pcbnew.ToMM(width) / 2

            clipped_trace = bbox.extend_by(-track_radius).clip_segment((start, end))

            if not clipped_trace:
                self.board.Delete(track)
                continue

            new_start, new_end = clipped_trace
            track.SetStart(pcbnew.VECTOR2I_MM(float(new_start.x), float(new_start.y)))
            track.SetEnd(pcbnew.VECTOR2I_MM(float(new_end.x), float(new_end.y)))
            if new_start != start:
                if self.terminate_track(new_start.x, new_start.y, track.GetWidth(), track) == 0:
                    sp_tracks.append(track)
            if new_end != end:
                if self.terminate_track(new_end.x, new_end.y, track.GetWidth(), track) == 0:
                    sp_tracks.append(track)

        return sp_tracks

    def remove_pad_footprints(self, bbox: BBox) -> BBox:
        """Change size of the board to edge nearest footprints and remove those out of the range of the board."""
        to_remove = []
        to_remove2 = []
        new_bbox = deepcopy(bbox)

        def pad_corners(fp: pcbnew.FOOTPRINT) -> tuple[Point, Point, Point, Point]:
            padbbox = fp.GetFpPadsLocalBbox()
            [footprint_x, footprint_y] = pcbnew.ToMM(fp.GetPosition())
            c1 = Point(pcbnew.ToMM(padbbox.GetLeft()) + footprint_x, pcbnew.ToMM(padbbox.GetTop()) + footprint_y)
            c2 = Point(pcbnew.ToMM(padbbox.GetRight()) + footprint_x, pcbnew.ToMM(padbbox.GetBottom()) + footprint_y)
            c3, c4 = Point(c1.x, c2.y), Point(c2.x, c1.y)
            return (c1, c2, c3, c4)

        # Note: These are not original footprints, these are processed footprint-per-pad
        for footprint in self.board.GetFootprints():
            corners = pad_corners(footprint)
            if not any(bbox.in_bbox(c) for c in corners):
                # Pad is completely outside of new outline
                to_remove.append(footprint)
                continue

            # pads that are partially inside new outline should extend it
            for c in corners:
                new_bbox.add_point(c)

        exp_bbox = new_bbox.extend_by(0.3)
        for footprint in to_remove:
            corners = pad_corners(footprint)
            if not all(exp_bbox.in_bbox(c) for c in corners):
                # Pad is completely inside of updated outline, so there is no need to remove it
                to_remove2.append(footprint)
                continue

        for item in to_remove2:
            self.board.Delete(item)

        return new_bbox

    def footprint_to_pad(self) -> None:
        """Split every footprint into separate pad, then turn pad into footprint."""
        pads_as_fp = []
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                virt_footprint = pcbnew.FOOTPRINT(self.board)
                new_pad = pcbnew.PAD(pad)
                new_pad.SetPos(pcbnew.VECTOR2I(0, 0))  # Set pad position to origin of the footprint
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

    def create_edge_cuts(self, points: list[tuple[float, float]], offset: list[float]) -> list:
        """Create shape for Sliced PCB."""

        bbox = BBox()

        # Find max coordinates of track
        for x, y in points:
            bbox.add_point(Point(float(x), float(y)))

        bbox.max.x += offset[0]
        bbox.min.x -= offset[1]
        bbox.max.y += offset[2]
        bbox.min.y -= offset[3]
        edge_bbox = self.board.GetBoardEdgesBoundingBox()

        self.footprint_to_pad()
        bbox = self.remove_pad_footprints(bbox)

        sp_track_termination = self.cut_tracks(bbox)
        self.resize_zones(bbox)

        mask_layers = [pcbnew.F_Mask, pcbnew.B_Mask]

        # Remove all drawings except mask_layers
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer() not in mask_layers:
                self.board.Delete(drawing)

        bbox.max.x = min(bbox.max.x, pcbnew.ToMM(edge_bbox.GetRight()))
        bbox.min.x = max(bbox.min.x, pcbnew.ToMM(edge_bbox.GetLeft()))
        bbox.max.y = min(bbox.max.y, pcbnew.ToMM(edge_bbox.GetBottom()))
        bbox.min.y = max(bbox.min.y, pcbnew.ToMM(edge_bbox.GetTop()))

        segment = pcbnew.PCB_SHAPE(self.board)
        self.board.Add(segment)
        segment.SetShape(pcbnew.S_RECT)
        segment.SetLayer(pcbnew.Edge_Cuts)
        segment.SetStart(pcbnew.VECTOR2I_MM(bbox.min.x, bbox.min.y))
        segment.SetEnd(pcbnew.VECTOR2I_MM(bbox.max.x, bbox.max.y))

        # Remove mask layers out of EdgeCuts
        for drawing in self.board.GetDrawings():
            if drawing.GetLayer() in mask_layers:
                if not segment.GetBoundingBox().Contains(drawing.GetPosition()):
                    self.board.Delete(drawing)

        temporary_aux_offset = 0.025

        self.board.GetDesignSettings().SetAuxOrigin(
            pcbnew.VECTOR2I_MM(bbox.min.x - temporary_aux_offset, bbox.max.y + temporary_aux_offset)
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
            self.place_sim_port_fp(float(x), float(y))
            return 0

        new_via = pcbnew.PCB_VIA(self.board)
        new_via.SetDrill(50000)  # 0.05 mm
        new_via.SetViaType(pcbnew.VIATYPE_BURIED)
        new_via.SetFrontWidth(width_t)
        new_via.SetNet(self.GNDnet)
        new_via.SetPosition(pcbnew.VECTOR2I_MM(float(x), float(y)))
        layer, lcopp_num = self.get_num_layers(track.GetLayerName())
        start_layer = max(layer - 1, 0)
        end_layer = min(layer + 1, lcopp_num - 1)
        new_via.SetLayerPair(self.get_kicad_layer_number(start_layer), self.get_kicad_layer_number(end_layer))
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

    def get_kicad_layer_number(self, layer: int) -> int:
        """Get layer number used by KiCad."""
        if layer == 0:
            return 0
        if layer + 1 == self.board.GetCopperLayerCount():
            return 2
        return layer * 2 + 2

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
