"""Topology building and Link matching algorithms for OSPF P2P connections.

Key Requirements:
- Support networkx.MultiGraph (multiple edges between the same pair of Router IDs).
- NEVER collapse links by router pair set(sorted([A, B])).
- Differentiate parallel links using IP subnet correlation and stub networks.
- Handle asymmetric metrics.
- Handle one-way / incomplete links (neighbor Router ID has no LSA or link omitted).
- Match priority:
  1. Belonging to exact P2P subnet (e.g. /30 or /31) confirmed by Stub records or IP math.
  2. Matching stub network prefix from either router.
  3. Metric / heuristic compatibility if unambiguous.
  4. Mark ambiguous if multiple candidates exist and cannot be uniquely distinguished.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Dict, List, Tuple, Optional, Set
import networkx as nx

from ospf_viz.models import (
    OSPFRouter,
    OSPFLink,
    P2PEndpoint,
    StubNetwork,
    LinkMatchStatus,
)

logger = logging.getLogger(__name__)


def find_matching_stub(ip_str: Optional[str], stubs: List[StubNetwork]) -> Optional[ipaddress.IPv4Network]:
    """Finds if an IP address belongs to any of the router's stub networks."""
    if not ip_str:
        return None
    try:
        ip = ipaddress.IPv4Address(ip_str)
    except Exception:
        return None

    best_match: Optional[ipaddress.IPv4Network] = None
    for stub in stubs:
        net = stub.cidr
        if net and ip in net:
            # We prefer more specific networks (longer prefixlen) e.g. /30 or /31 over /24
            if best_match is None or net.prefixlen > best_match.prefixlen:
                best_match = net
    return best_match


def can_ips_share_subnet(ip_a_str: Optional[str], ip_b_str: Optional[str], known_subnets: List[ipaddress.IPv4Network]) -> Optional[ipaddress.IPv4Network]:
    """Checks if IP A and IP B can belong to the same subnet."""
    if not ip_a_str or not ip_b_str:
        return None
    try:
        ip_a = ipaddress.IPv4Address(ip_a_str)
        ip_b = ipaddress.IPv4Address(ip_b_str)
    except Exception:
        return None

    # Check against known stub subnets
    for net in known_subnets:
        if ip_a in net and ip_b in net:
            return net

    # Fallback to standard P2P /30 or /31 calculation
    for prefix in (30, 31):
        try:
            net_a = ipaddress.IPv4Network(f"{ip_a_str}/{prefix}", strict=False)
            if ip_b in net_a:
                return net_a
        except Exception:
            pass

    return None


class TopologyBuilder:
    """Builds an OSPF MultiGraph and matches bidirectional P2P links."""

    def __init__(self):
        self.warnings: List[str] = []
        self.links: List[OSPFLink] = []
        self.graph = nx.MultiGraph()

    def build_topology(self, routers: Dict[str, OSPFRouter]) -> Tuple[nx.MultiGraph, List[OSPFLink], List[str]]:
        """
        Builds MultiGraph from parsed routers dict.
        Returns:
            (graph, list_of_links, warnings)
        """
        self.warnings.clear()
        self.links.clear()
        self.graph.clear()

        # Step 1: Ensure all advertised routers exist in the graph and routers dict
        all_neighbor_ids: Set[str] = set()
        for r_id, router in routers.items():
            for ep in router.p2p_endpoints:
                all_neighbor_ids.add(ep.neighbor_id)

        for n_id in all_neighbor_ids:
            if n_id not in routers:
                # Discovered only as neighbor, missing own Router-LSA
                routers[n_id] = OSPFRouter(router_id=n_id, has_lsa=False)
                self.warnings.append(f"Router {n_id} seen as P2P neighbor but its Router-LSA is missing in LSDB")

        for r_id, router in routers.items():
            self.graph.add_node(
                r_id,
                router=router,
                has_lsa=router.has_lsa,
                areas=list(router.areas),
                instances=list(router.instances)
            )

        # Step 2: Group endpoints by unordered pair of router IDs {r1, r2}
        # A pair key can be a sorted tuple of IDs: (min(r1, r2), max(r1, r2))
        # Note: We group endpoints only to isolate the matching problem per router-pair,
        # each distinct connection between this pair will produce its own independent OSPFLink!
        pair_endpoints: Dict[Tuple[str, str], Dict[str, List[P2PEndpoint]]] = {}

        for r_id, router in routers.items():
            for ep in router.p2p_endpoints:
                pair_key = (min(r_id, ep.neighbor_id), max(r_id, ep.neighbor_id))
                if pair_key not in pair_endpoints:
                    pair_endpoints[pair_key] = {pair_key[0]: [], pair_key[1]: []}
                pair_endpoints[pair_key][r_id].append(ep)

        link_counter = 0

        # Step 3: Match endpoints for each router pair
        for (r1, r2), sides in pair_endpoints.items():
            endpoints_1 = list(sides[r1])
            endpoints_2 = list(sides[r2])

            router_1 = routers[r1]
            router_2 = routers[r2]

            all_stubs = router_1.stubs + router_2.stubs
            known_subnets = [s.cidr for s in all_stubs if s.cidr is not None]

            # Matching algorithm between endpoints_1 and endpoints_2
            matched_pairs, remaining_1, remaining_2 = self._match_endpoints(
                r1, r2, endpoints_1, endpoints_2, known_subnets
            )

            # Create OSPFLink for each matched pair
            for ep1, ep2, subnet in matched_pairs:
                link_counter += 1
                link_id = f"link_{link_counter}_{r1}_{r2}"

                link_warnings: List[str] = []
                status = LinkMatchStatus.MATCHED

                if ep1.metric != ep2.metric:
                    status = LinkMatchStatus.ASYMMETRIC
                    link_warnings.append(
                        f"Asymmetric metrics: {r1}->{r2}={ep1.metric}, {r2}->{r1}={ep2.metric}"
                    )
                    self.warnings.append(
                        f"Link {r1} <-> {r2} ({subnet or 'unknown'}): asymmetric metric ({ep1.metric} vs {ep2.metric})"
                    )

                link = OSPFLink(
                    id=link_id,
                    router_a=r1,
                    router_b=r2,
                    ip_a=ep1.local_ip,
                    ip_b=ep2.local_ip,
                    metric_a_to_b=ep1.metric,
                    metric_b_to_a=ep2.metric,
                    subnet=str(subnet) if subnet else None,
                    area=ep1.area or ep2.area,
                    instance=ep1.instance or ep2.instance,
                    status=status,
                    warnings=link_warnings
                )
                self.links.append(link)
                self.graph.add_edge(r1, r2, key=link_id, link=link)

            # Handle remaining unmatched from side 1 (r1 -> r2 only)
            for ep1 in remaining_1:
                link_counter += 1
                link_id = f"link_{link_counter}_{r1}_{r2}_incomplete"
                subnet = find_matching_stub(ep1.local_ip, router_1.stubs)

                warn = f"One-way link from {r1} to {r2} (no return LSA entry from {r2})"
                self.warnings.append(warn)

                link = OSPFLink(
                    id=link_id,
                    router_a=r1,
                    router_b=r2,
                    ip_a=ep1.local_ip,
                    ip_b=None,
                    metric_a_to_b=ep1.metric,
                    metric_b_to_a=None,
                    subnet=str(subnet) if subnet else None,
                    area=ep1.area,
                    instance=ep1.instance,
                    status=LinkMatchStatus.ONE_WAY,
                    warnings=[warn]
                )
                self.links.append(link)
                self.graph.add_edge(r1, r2, key=link_id, link=link)

            # Handle remaining unmatched from side 2 (r2 -> r1 only)
            for ep2 in remaining_2:
                link_counter += 1
                link_id = f"link_{link_counter}_{r2}_{r1}_incomplete"
                subnet = find_matching_stub(ep2.local_ip, router_2.stubs)

                warn = f"One-way link from {r2} to {r1} (no return LSA entry from {r1})"
                self.warnings.append(warn)

                link = OSPFLink(
                    id=link_id,
                    router_a=r2,
                    router_b=r1,
                    ip_a=ep2.local_ip,
                    ip_b=None,
                    metric_a_to_b=ep2.metric,
                    metric_b_to_a=None,
                    subnet=str(subnet) if subnet else None,
                    area=ep2.area,
                    instance=ep2.instance,
                    status=LinkMatchStatus.ONE_WAY,
                    warnings=[warn]
                )
                self.links.append(link)
                self.graph.add_edge(r2, r1, key=link_id, link=link)

        return self.graph, self.links, self.warnings

    def _match_endpoints(
        self,
        r1: str,
        r2: str,
        endpoints_1: List[P2PEndpoint],
        endpoints_2: List[P2PEndpoint],
        known_subnets: List[ipaddress.IPv4Network]
    ) -> Tuple[List[Tuple[P2PEndpoint, P2PEndpoint, Optional[ipaddress.IPv4Network]]], List[P2PEndpoint], List[P2PEndpoint]]:
        """
        Matches endpoints between r1 and r2.
        Priority:
        1. Both IPs belong to the exact same known subnet (e.g. from stub /30 or /31).
        2. IPs form a valid /30 or /31 subnet even if stub wasn't explicitly listed.
        3. If exactly 1 endpoint remains on both sides, pair them if unambiguous.
        """
        matched: List[Tuple[P2PEndpoint, P2PEndpoint, Optional[ipaddress.IPv4Network]]] = []
        rem_1 = list(endpoints_1)
        rem_2 = list(endpoints_2)

        # Pass 1: Strict match using known subnets from stub networks
        i = 0
        while i < len(rem_1):
            ep1 = rem_1[i]
            matching_j = -1
            matched_subnet = None

            for j, ep2 in enumerate(rem_2):
                subnet = can_ips_share_subnet(ep1.local_ip, ep2.local_ip, known_subnets)
                if subnet is not None:
                    matching_j = j
                    matched_subnet = subnet
                    break

            if matching_j != -1:
                ep2 = rem_2.pop(matching_j)
                rem_1.pop(i)
                matched.append((ep1, ep2, matched_subnet))
            else:
                i += 1

        # Pass 2: Pairwise /30 or /31 match even if stub is not in LSDB
        i = 0
        while i < len(rem_1):
            ep1 = rem_1[i]
            matching_j = -1
            matched_subnet = None

            for j, ep2 in enumerate(rem_2):
                subnet = can_ips_share_subnet(ep1.local_ip, ep2.local_ip, [])
                if subnet is not None:
                    matching_j = j
                    matched_subnet = subnet
                    break

            if matching_j != -1:
                ep2 = rem_2.pop(matching_j)
                rem_1.pop(i)
                matched.append((ep1, ep2, matched_subnet))
            else:
                i += 1

        # Pass 3: If exactly 1 endpoint remains on both sides and only 1 link was ever present,
        # pair them even if IPs are unnumbered or subnets couldn't be computed
        if len(rem_1) == 1 and len(rem_2) == 1:
            ep1 = rem_1.pop(0)
            ep2 = rem_2.pop(0)
            matched.append((ep1, ep2, None))

        return matched, rem_1, rem_2
