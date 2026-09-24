"""Layout algorithms for positioning OSPF network topology nodes."""

from __future__ import annotations

import math
from typing import Dict, Tuple, List, Optional
import networkx as nx


class TopologyLayoutManager:
    """Computes and updates coordinates for OSPF topology nodes."""

    @staticmethod
    def compute_layout(
        graph: nx.MultiGraph,
        mode: str = "radial",
        center_node: Optional[str] = None,
        spacing: float = 200.0,
        saved_positions: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> Dict[str, Tuple[float, float]]:
        """
        Calculates (x, y) positions for all nodes in the graph.
        Preserves saved_positions for nodes that already have them if requested.
        """
        nodes = list(graph.nodes)
        if not nodes:
            return {}

        positions: Dict[str, Tuple[float, float]] = {}
        if saved_positions:
            for n in nodes:
                if n in saved_positions:
                    positions[n] = saved_positions[n]

        # Determine center node if needed
        if not center_node or center_node not in nodes:
            # Pick node with highest degree as default center
            degrees = dict(graph.degree())
            center_node = max(degrees.keys(), key=lambda k: degrees[k]) if degrees else nodes[0]

        if mode == "radial":
            new_pos = TopologyLayoutManager._layout_radial(graph, center_node, spacing)
        elif mode == "hierarchical":
            new_pos = TopologyLayoutManager._layout_hierarchical(graph, center_node, spacing)
        elif mode == "force":
            new_pos = TopologyLayoutManager._layout_force(graph, spacing)
        elif mode == "circular":
            new_pos = TopologyLayoutManager._layout_circular(graph, spacing)
        else:
            new_pos = TopologyLayoutManager._layout_radial(graph, center_node, spacing)

        # Merge new positions with saved positions (saved take priority if already present)
        for n, coord in new_pos.items():
            if n not in positions:
                positions[n] = coord

        return positions

    @staticmethod
    def _layout_radial(graph: nx.MultiGraph, center: str, spacing: float) -> Dict[str, Tuple[float, float]]:
        """Radial BFS layout from center router."""
        positions: Dict[str, Tuple[float, float]] = {center: (0.0, 0.0)}

        # Run BFS to determine hop distances
        # For disconnected components, we also place them on outer rings
        visited = {center}
        levels: Dict[int, List[str]] = {0: [center]}
        queue = [(center, 0)]

        while queue:
            curr, depth = queue.pop(0)
            for neighbor in graph.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_depth = depth + 1
                    if next_depth not in levels:
                        levels[next_depth] = []
                    levels[next_depth].append(neighbor)
                    queue.append((neighbor, next_depth))

        # Include unvisited disconnected nodes as an additional level
        unvisited = [n for n in graph.nodes if n not in visited]
        if unvisited:
            max_depth = max(levels.keys()) if levels else 0
            levels[max_depth + 1] = unvisited

        # Arrange levels in concentric circles
        for depth, node_list in levels.items():
            if depth == 0:
                continue
            radius = depth * spacing
            count = len(node_list)
            angle_step = 2 * math.pi / max(count, 1)

            for idx, node in enumerate(node_list):
                angle = idx * angle_step
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                positions[node] = (round(x, 1), round(y, 1))

        return positions

    @staticmethod
    def _layout_hierarchical(graph: nx.MultiGraph, center: str, spacing: float) -> Dict[str, Tuple[float, float]]:
        """Top-down hierarchical BFS levels."""
        positions: Dict[str, Tuple[float, float]] = {center: (0.0, 0.0)}
        visited = {center}
        levels: Dict[int, List[str]] = {0: [center]}
        queue = [(center, 0)]

        while queue:
            curr, depth = queue.pop(0)
            for neighbor in graph.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_depth = depth + 1
                    if next_depth not in levels:
                        levels[next_depth] = []
                    levels[next_depth].append(neighbor)
                    queue.append((neighbor, next_depth))

        unvisited = [n for n in graph.nodes if n not in visited]
        if unvisited:
            max_depth = max(levels.keys()) if levels else 0
            levels[max_depth + 1] = unvisited

        for depth, node_list in levels.items():
            count = len(node_list)
            y = depth * spacing * 1.3
            total_width = (count - 1) * spacing
            start_x = -total_width / 2.0

            for idx, node in enumerate(node_list):
                x = start_x + idx * spacing
                positions[node] = (round(x, 1), round(y, 1))

        return positions

    @staticmethod
    def _layout_force(graph: nx.MultiGraph, spacing: float) -> Dict[str, Tuple[float, float]]:
        """Pure-Python Fruchterman-Reingold force-directed layout without requiring numpy."""
        nodes = list(graph.nodes)
        if not nodes:
            return {}
        if len(nodes) == 1:
            return {nodes[0]: (0.0, 0.0)}

        import random

        # Initial placement on circle with jitter
        positions: Dict[str, List[float]] = {}
        radius = spacing * math.sqrt(len(nodes)) / 2.0
        angle_step = 2 * math.pi / len(nodes)
        rng = random.Random(42)  # Deterministic seed

        for i, node in enumerate(nodes):
            angle = i * angle_step
            jitter_x = rng.uniform(-10.0, 10.0)
            jitter_y = rng.uniform(-10.0, 10.0)
            positions[node] = [radius * math.cos(angle) + jitter_x, radius * math.sin(angle) + jitter_y]

        # Fruchterman-Reingold iterations
        k = spacing
        k2 = k * k
        iterations = 60
        temp = spacing * 1.5
        temp_step = temp / iterations

        # Adjacency
        neighbors = {n: set(graph.neighbors(n)) for n in nodes}

        for _ in range(iterations):
            disp = {n: [0.0, 0.0] for n in nodes}

            # Repulsive forces between all pairs of nodes
            for i, n1 in enumerate(nodes):
                pos1 = positions[n1]
                for n2 in nodes[i + 1:]:
                    pos2 = positions[n2]
                    dx = pos1[0] - pos2[0]
                    dy = pos1[1] - pos2[1]
                    dist = math.hypot(dx, dy)
                    if dist < 0.01:
                        dx = rng.uniform(-1.0, 1.0)
                        dy = rng.uniform(-1.0, 1.0)
                        dist = math.hypot(dx, dy)

                    # Repulsion: Fr = k^2 / d
                    fr = k2 / dist
                    fx = (dx / dist) * fr
                    fy = (dy / dist) * fr

                    disp[n1][0] += fx
                    disp[n1][1] += fy
                    disp[n2][0] -= fx
                    disp[n2][1] -= fy

            # Attractive forces along edges
            for n1 in nodes:
                pos1 = positions[n1]
                for n2 in neighbors[n1]:
                    if n1 < n2:  # Process each edge once
                        pos2 = positions[n2]
                        dx = pos1[0] - pos2[0]
                        dy = pos1[1] - pos2[1]
                        dist = math.hypot(dx, dy)
                        if dist < 0.01:
                            continue
                        # Attraction: Fa = d^2 / k
                        fa = (dist * dist) / k
                        fx = (dx / dist) * fa
                        fy = (dy / dist) * fa

                        disp[n1][0] -= fx
                        disp[n1][1] -= fy
                        disp[n2][0] += fx
                        disp[n2][1] += fy

            # Apply displacement capped by temperature
            for n in nodes:
                dx, dy = disp[n]
                d = math.hypot(dx, dy)
                if d > 0.001:
                    capped_d = min(d, temp)
                    positions[n][0] += (dx / d) * capped_d
                    positions[n][1] += (dy / d) * capped_d

            temp = max(temp - temp_step, 1.0)

        return {k: (round(v[0], 1), round(v[1], 1)) for k, v in positions.items()}

    @staticmethod
    def _layout_circular(graph: nx.MultiGraph, spacing: float) -> Dict[str, Tuple[float, float]]:
        """Evenly distributed circle."""
        nodes = list(graph.nodes)
        count = len(nodes)
        radius = max(spacing * 1.5, (count * spacing) / (2 * math.pi))
        angle_step = 2 * math.pi / max(count, 1)

        positions: Dict[str, Tuple[float, float]] = {}
        for idx, node in enumerate(nodes):
            angle = idx * angle_step
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            positions[node] = (round(x, 1), round(y, 1))
        return positions
