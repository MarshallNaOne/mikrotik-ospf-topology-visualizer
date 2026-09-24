"""Data models for OSPF topology representation."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class LinkMatchStatus(str, Enum):
    MATCHED = "matched"              # Matched bidirectionally with high confidence
    ASYMMETRIC = "asymmetric"        # Matched bidirectionally, but metrics differ
    ONE_WAY = "one_way"              # Observed only from Router A -> Router B (incomplete)
    AMBIGUOUS = "ambiguous"          # Multiple candidates or unresolvable matching


@dataclass
class P2PEndpoint:
    """Represents a single P2P link record observed from one router's perspective."""
    originator: str                  # Router ID of the advertising router
    neighbor_id: str                 # Neighbor Router ID (from id field)
    local_ip: Optional[str] = None   # Local IP address on P2P interface (from data field)
    metric: int = 10                 # OSPF cost
    area: str = "area0"
    instance: str = "default-v2"
    matched_subnet: Optional[str] = None  # Determined from stub or calculation (e.g. 10.0.0.12/30)
    raw_text: Optional[str] = None


@dataclass
class StubNetwork:
    """Represents a stub network record from Router-LSA."""
    network: str                     # From id field, e.g. 10.0.0.12 or 192.168.1.0
    netmask: str                     # From data field, e.g. 255.255.255.252
    metric: int = 10
    originator: str = ""
    area: str = "area0"
    instance: str = "default-v2"

    @property
    def cidr(self) -> Optional[ipaddress.IPv4Network]:
        try:
            return ipaddress.IPv4Network(f"{self.network}/{self.netmask}", strict=False)
        except Exception:
            return None


@dataclass
class OSPFRouter:
    """Represents an OSPF Router node in the topology."""
    router_id: str
    has_lsa: bool = True             # True if Router-LSA was present in LSDB, False if discovered only as neighbor
    areas: List[str] = field(default_factory=list)
    instances: List[str] = field(default_factory=list)
    p2p_endpoints: List[P2PEndpoint] = field(default_factory=list)
    stubs: List[StubNetwork] = field(default_factory=list)
    extra_attributes: Dict[str, Any] = field(default_factory=dict)

    def add_area(self, area: str) -> None:
        if area and area not in self.areas:
            self.areas.append(area)

    def add_instance(self, instance: str) -> None:
        if instance and instance not in self.instances:
            self.instances.append(instance)


@dataclass
class OSPFLink:
    """Represents a bidirectional (or one-way incomplete) physical/logical P2P connection."""
    id: str                          # Globally unique link ID
    router_a: str                    # Router ID side A
    router_b: str                    # Router ID side B
    ip_a: Optional[str] = None       # Local IP on side A
    ip_b: Optional[str] = None       # Local IP on side B
    metric_a_to_b: Optional[int] = None
    metric_b_to_a: Optional[int] = None
    subnet: Optional[str] = None     # CIDR subnet, e.g. "10.0.0.12/30"
    area: str = "area0"
    instance: str = "default-v2"
    status: LinkMatchStatus = LinkMatchStatus.MATCHED
    warnings: List[str] = field(default_factory=list)

    @property
    def is_asymmetric(self) -> bool:
        if self.metric_a_to_b is not None and self.metric_b_to_a is not None:
            return self.metric_a_to_b != self.metric_b_to_a
        return False

    @property
    def is_one_way(self) -> bool:
        return self.metric_a_to_b is None or self.metric_b_to_a is None or self.ip_a is None or self.ip_b is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "router_a": self.router_a,
            "router_b": self.router_b,
            "ip_a": self.ip_a,
            "ip_b": self.ip_b,
            "metric_a_to_b": self.metric_a_to_b,
            "metric_b_to_a": self.metric_b_to_a,
            "subnet": self.subnet,
            "area": self.area,
            "instance": self.instance,
            "status": self.status.value,
            "is_asymmetric": self.is_asymmetric,
            "warnings": list(self.warnings),
        }
