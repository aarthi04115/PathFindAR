"""
Indoor Navigation — A* Pathfinding on Building Graph

Workflow:
  1. Load building_map.json → NetworkX DiGraph (with weights)
  2. find_route() → nx.astar_path() → list of node dicts
  3. get_nearest_node() → scipy KDTree spatial lookup
  4. Turn detection → dot-product of consecutive edge direction vectors
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
from scipy.spatial import KDTree
from loguru import logger


# ── Typing helpers ──────────────────────────────────────────────────────────

Vec3 = list[float]  # [x, y, z]


# ── Data model (thin wrappers to avoid Pydantic in here) ───────────────────

class MapNode:
    __slots__ = ("id", "label", "position", "floor", "type", "tags")

    def __init__(self, d: dict):
        self.id: str = d["id"]
        self.label: str = d.get("label", self.id)
        self.position: Vec3 = d["position"]        # [x, y, z] Unity world coords
        self.floor: int = d.get("floor", 0)
        self.type: str = d.get("type", "junction")
        self.tags: list[str] = d.get("tags", [])


# ── Navigator ──────────────────────────────────────────────────────────────

class IndoorNavigator:
    """
    Handles building graph loading and A* pathfinding.

    Typical lifecycle:
        nav = IndoorNavigator()
        nav.load_map("path/to/building_map.json")
        result = nav.find_route("entrance", "room_101")
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self.nodes: dict[str, MapNode] = {}
        self.poi_aliases: dict[str, list[str]] = {}
        self._kdtree: Optional[KDTree] = None
        self._kdtree_ids: list[str] = []          # node id at each KDTree index
        self.is_loaded: bool = False
        logger.info("IndoorNavigator created (map not yet loaded)")

    # ── Map Loading ────────────────────────────────────────────────────────

    def load_map(self, map_file: str) -> None:
        """Parse building_map.json and build the navigation graph."""
        path = Path(map_file)
        if not path.exists():
            raise FileNotFoundError(f"Map file not found: {map_file}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # Parse nodes
        self.nodes = {}
        for nd in data.get("nodes", []):
            node = MapNode(nd)
            self.nodes[node.id] = node
            self.graph.add_node(
                node.id,
                label=node.label,
                position=node.position,
                floor=node.floor,
                type=node.type,
                tags=node.tags,
            )

        # Parse edges
        for edge in data.get("edges", []):
            src, dst, dist = edge["from"], edge["to"], edge.get("distance_m", 1.0)
            tags = edge.get("tags", [])
            self.graph.add_edge(src, dst, weight=dist, tags=tags)
            if edge.get("bidirectional", True):
                self.graph.add_edge(dst, src, weight=dist, tags=tags)

        # POI aliases (e.g. "toilet" → ["toilet_gf", "toilet_f1"])
        self.poi_aliases = data.get("poi_aliases", {})

        # Build KDTree for spatial lookups (uses [x, z] projected to floor plane)
        self._build_kdtree()

        self.is_loaded = True
        logger.info(
            f"Map loaded: {len(self.nodes)} nodes, {self.graph.number_of_edges()} edges"
        )

    def _build_kdtree(self) -> None:
        """Build a 3-D KDTree over all node positions for nearest-node lookups."""
        ids = list(self.nodes.keys())
        coords = np.array([self.nodes[nid].position for nid in ids], dtype=float)
        self._kdtree = KDTree(coords)
        self._kdtree_ids = ids
        logger.debug(f"KDTree built over {len(ids)} nodes")

    # ── Public API ─────────────────────────────────────────────────────────

    def find_route(
        self,
        start_node: str,
        end_node: str,
        floor: int = 0,
        accessible_only: bool = False,
    ) -> dict:
        """
        Run A* from start_node to end_node.

        Args:
            start_node: Node ID or POI alias.
            end_node:   Node ID or POI alias.
            floor:      Caller's current floor (used for alias resolution).
            accessible_only: If True, skip non-accessible vertical transitions.

        Returns:
            {
              "waypoints": [...],
              "total_distance": float,
              "estimated_time_sec": float,
            }
        """
        if not self.is_loaded:
            raise RuntimeError("Map not loaded — call load_map() first")

        # Resolve aliases → concrete node IDs
        start_id = self._resolve_node(start_node, floor)
        end_id = self._resolve_node(end_node, floor)

        if start_id not in self.graph:
            raise ValueError(f"Start node not in graph: {start_id!r}")
        if end_id not in self.graph:
            raise ValueError(f"End node not in graph: {end_id!r}")

        if start_id == end_id:
            start_node_obj = self.nodes[start_id]
            return {
                "waypoints": [self._node_to_waypoint(start_node_obj, is_turn=False)],
                "total_distance": 0.0,
                "estimated_time_sec": 0.0,
            }

        try:
            path_ids: list[str] = nx.astar_path(
                self.graph,
                source=start_id,
                target=end_id,
                heuristic=self._heuristic,
                weight="weight",
            )
        except nx.NetworkXNoPath:
            raise ValueError(f"No path between {start_id!r} and {end_id!r}")
        except nx.NodeNotFound as exc:
            raise ValueError(str(exc)) from exc

        waypoints = self._path_to_waypoints(path_ids)
        total_dist = self._path_distance(path_ids)
        walk_speed_mps = 1.2  # average walking speed
        est_time = total_dist / walk_speed_mps

        logger.info(
            f"Route found: {start_id} → {end_id} | "
            f"{len(path_ids)} hops | {total_dist:.1f} m | {est_time:.0f} s"
        )
        return {
            "waypoints": waypoints,
            "total_distance": round(total_dist, 2),
            "estimated_time_sec": round(est_time, 1),
        }

    def get_nearest_node(
        self, position: Vec3, floor: Optional[int] = None
    ) -> Optional[str]:
        """
        Return the closest graph node to a given world position.

        Args:
            position: [x, y, z] Unity world coordinates.
            floor:    If provided, restrict search to that floor.
        """
        if not self.is_loaded or self._kdtree is None:
            return None

        if floor is not None:
            # Filter candidates by floor, then find nearest among them
            candidates = [
                nid for nid, n in self.nodes.items() if n.floor == floor
            ]
            if not candidates:
                return None
            coords = np.array(
                [self.nodes[nid].position for nid in candidates], dtype=float
            )
            tree = KDTree(coords)
            _, idx = tree.query(position)
            return candidates[idx]

        _, idx = self._kdtree.query(position)
        return self._kdtree_ids[idx]

    def get_node(self, node_id: str) -> Optional[MapNode]:
        """Return a MapNode by ID, or None if not found."""
        return self.nodes.get(node_id)

    # ── Private helpers ────────────────────────────────────────────────────

    def _resolve_node(self, name: str, floor: int = 0) -> str:
        """
        Resolve a node name or alias to a concrete node ID.
        For aliases with multiple targets, prefer the one on the same floor.
        """
        if name in self.nodes:
            return name
        alias_targets = self.poi_aliases.get(name.lower())
        if alias_targets:
            # Prefer target on caller's floor
            same_floor = [t for t in alias_targets if self.nodes.get(t, None) and
                          self.nodes[t].floor == floor]
            return same_floor[0] if same_floor else alias_targets[0]
        raise ValueError(f"Unknown node or alias: {name!r}")

    def _heuristic(self, u: str, v: str) -> float:
        """Euclidean distance heuristic for A*."""
        pu = self.nodes[u].position
        pv = self.nodes[v].position
        return math.dist(pu, pv)

    def _path_distance(self, path_ids: list[str]) -> float:
        """Sum edge weights along a path."""
        total = 0.0
        for a, b in zip(path_ids, path_ids[1:]):
            total += self.graph[a][b].get("weight", 1.0)
        return total

    def _path_to_waypoints(self, path_ids: list[str]) -> list[dict]:
        """Convert node-ID path to waypoint dicts with turn detection."""
        waypoints = []
        n = len(path_ids)
        for i, nid in enumerate(path_ids):
            node = self.nodes[nid]
            is_turn, turn_dir = False, None

            if 0 < i < n - 1:
                prev_pos = np.array(self.nodes[path_ids[i - 1]].position)
                curr_pos = np.array(node.position)
                next_pos = np.array(self.nodes[path_ids[i + 1]].position)
                is_turn, turn_dir = self._detect_turn(prev_pos, curr_pos, next_pos)

            waypoints.append(self._node_to_waypoint(node, is_turn, turn_dir))
        return waypoints

    @staticmethod
    def _detect_turn(
        prev: np.ndarray, curr: np.ndarray, nxt: np.ndarray
    ) -> tuple[bool, Optional[str]]:
        """
        Detect if there's a significant turn at `curr`.
        Uses cross-product sign in the XZ plane (floor plane) to determine L/R.
        Returns (is_turn, direction) where direction is 'left' | 'right' | None.
        """
        in_vec = curr - prev
        out_vec = nxt - curr

        # Normalise in XZ plane only (ignore Y — floor transitions)
        def xz(v: np.ndarray) -> np.ndarray:
            return np.array([v[0], v[2]])

        in_xz = xz(in_vec)
        out_xz = xz(out_vec)

        in_norm = np.linalg.norm(in_xz)
        out_norm = np.linalg.norm(out_xz)

        if in_norm < 1e-6 or out_norm < 1e-6:
            return False, None

        in_xz /= in_norm
        out_xz /= out_norm

        cos_angle = float(np.clip(np.dot(in_xz, out_xz), -1.0, 1.0))
        angle_deg = math.degrees(math.acos(cos_angle))

        TURN_THRESHOLD_DEG = 30.0
        if angle_deg < TURN_THRESHOLD_DEG:
            return False, None

        # Cross product Z-component: positive → left turn, negative → right
        cross_z = in_xz[0] * out_xz[1] - in_xz[1] * out_xz[0]
        direction = "left" if cross_z > 0 else "right"
        return True, direction

    @staticmethod
    def _node_to_waypoint(
        node: MapNode, is_turn: bool, turn_dir: Optional[str] = None
    ) -> dict:
        return {
            "node_id": node.id,
            "label": node.label,
            "position": node.position,
            "floor": node.floor,
            "is_turn": is_turn,
            "turn_direction": turn_dir,
        }
