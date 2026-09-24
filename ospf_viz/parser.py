"""Robust parser for MikroTik RouterOS 7 LSA output.

Parses command output:
`/routing/ospf/lsa/print detail without-paging`

Handles:
- Router-LSA (type="router") with body items:
  - type=p2p id=<neighbor_rid> data=<local_ip> metric=<cost>
  - type=stub id=<net> data=<mask> metric=<cost>
  - other body types (transit, virtual, etc.)
- Graceful skipping of non-router LSAs:
  - type="external"
  - type="opaque-area"
  - type="network"
  - type="inter-area-prefix" / summary
  - other custom or future LSA types
- Multi-line body indentation formats across RouterOS v7 minor versions.
"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple, Dict, Any, Optional
from ospf_viz.models import P2PEndpoint, StubNetwork, OSPFRouter

logger = logging.getLogger(__name__)


class LSAParser:
    """Parses RouterOS LSA print output into structured OSPF data."""

    def __init__(self):
        self.warnings: List[str] = []

    def parse(self, text: str) -> Dict[str, OSPFRouter]:
        """
        Parses full MikroTik LSA text output.
        Returns a dictionary of Router ID -> OSPFRouter.
        """
        self.warnings.clear()
        routers: Dict[str, OSPFRouter] = {}

        if not text or not text.strip():
            logger.warning("Empty LSA text provided")
            return routers

        # Separate LSA blocks.
        # RouterOS detail blocks typically start with an index number or flags like:
        # 0 instance=default-v2 area=area0 type="router" ...
        # or just instance=default-v2 ...
        raw_blocks = self._split_lsa_blocks(text)

        for block in raw_blocks:
            try:
                self._process_lsa_block(block, routers)
            except Exception as e:
                msg = f"Failed to parse LSA block: {e}"
                logger.warning(msg)
                self.warnings.append(msg)

        return routers

    def _split_lsa_blocks(self, text: str) -> List[str]:
        """
        Splits LSA print detail output into individual LSA records.
        Records in RouterOS `print detail` start at column 0 with optional flags/indices,
        followed by key=value tokens, or start with `instance=` / `type=` / `[0-9]+ `.
        """
        blocks: List[str] = []
        current_lines: List[str] = []

        # Matches the start of a new record in RouterOS detail output:
        # e.g.:
        # " 0 instance=default-v2 ..."
        # " 1  SD instance=default-v2 ..."
        # " 2   D instance=default-v2 ..."
        # "0  type=\"router\" ..."
        # "instance=default-v2 ..."
        # "type=\"router\" ..."
        # "flags=... instance=..."
        record_start_regex = re.compile(
            r"^(?:\s*\d+\s+)?(?:[A-Za-z\-]+\s+)?(?:flags=\S+\s+)?(?:instance=|type=|originator=|id=|sequence=)"
        )

        for line in text.splitlines():
            # Check if this line looks like a header/prompt/legend or empty
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("[admin@") or "routing/ospf/lsa/print" in stripped:
                continue
            if stripped.startswith("Flags:"):
                continue

            # Check if this line begins a new record
            if record_start_regex.match(line):
                if current_lines:
                    blocks.append("\n".join(current_lines))
                    current_lines = []
                current_lines.append(line)
            else:
                if current_lines:
                    current_lines.append(line)
                else:
                    # Might be the very first record without standard header regex match
                    current_lines.append(line)

        if current_lines:
            blocks.append("\n".join(current_lines))

        return blocks

    def _extract_key_values(self, text: str) -> Dict[str, str]:
        """
        Extracts key=value or key="quoted value" pairs from a string.
        """
        kv: Dict[str, str] = {}
        # Pattern handles: key="value with spaces" or key=value_without_spaces
        pattern = re.compile(r'([a-zA-Z0-9_\-]+)=(?:"([^"]*)"|(\S+))')
        for match in pattern.finditer(text):
            k = match.group(1)
            v = match.group(2) if match.group(2) is not None else match.group(3)
            kv[k] = v
        return kv

    def _process_lsa_block(self, block_text: str, routers: Dict[str, OSPFRouter]) -> None:
        """Parses a single LSA block."""
        # Split block into top-level metadata and the 'body' section
        # In RouterOS:
        # instance=default-v2 area=area0 type="router" originator=10.64.1.1 id=10.64.1.1 ...
        #   body=
        #     type=p2p id=10.64.1.8 data=10.0.0.14 metric=3000
        #     type=stub id=10.0.0.12 data=255.255.255.252 metric=3000
        # or body inline: body=type=p2p ...

        # Find where 'body=' begins
        body_idx = block_text.find("body=")
        if body_idx != -1:
            header_text = block_text[:body_idx]
            body_text = block_text[body_idx + len("body="):]
        else:
            header_text = block_text
            body_text = ""

        header_kv = self._extract_key_values(header_text)
        lsa_type = header_kv.get("type", "").strip('"').lower()

        # We gracefully ignore non-router types for topology graph
        if lsa_type != "router":
            logger.debug("Skipping non-router LSA type: %s", lsa_type)
            return

        originator = header_kv.get("originator") or header_kv.get("id")
        if not originator:
            self.warnings.append(f"Router-LSA missing originator/id: {header_text[:60]}")
            return

        area = header_kv.get("area", "area0")
        instance = header_kv.get("instance", "default-v2")

        if originator not in routers:
            routers[originator] = OSPFRouter(router_id=originator, has_lsa=True)
        else:
            routers[originator].has_lsa = True

        router = routers[originator]
        router.add_area(area)
        router.add_instance(instance)

        # Parse body entries
        if body_text:
            self._parse_router_lsa_body(originator, area, instance, body_text, router)

    def _parse_router_lsa_body(
        self,
        originator: str,
        area: str,
        instance: str,
        body_text: str,
        router: OSPFRouter
    ) -> None:
        """
        Parses items within the body of a Router-LSA.
        Items can be:
        type=p2p id=10.64.1.8 data=10.0.0.14 metric=3000
        type=stub id=10.0.0.12 data=255.255.255.252 metric=3000
        Items might be separated by newlines, spaces, or semicolons.
        """
        # Split body into item chunks based on occurrences of 'type='
        # Example body text:
        # "type=p2p id=10.64.1.8 data=10.0.0.14 metric=3000\n  type=stub id=..."
        # or multiple type= tokens on lines
        item_chunks = re.split(r'(?=(?:^|\s)type=)', body_text.strip())

        for chunk in item_chunks:
            chunk = chunk.strip()
            if not chunk or not chunk.startswith("type="):
                continue

            kv = self._extract_key_values(chunk)
            item_type = kv.get("type", "").lower()

            if item_type == "p2p":
                neighbor_id = kv.get("id")
                local_ip = kv.get("data")
                metric_str = kv.get("metric", "10")
                try:
                    metric = int(metric_str)
                except ValueError:
                    metric = 10

                if neighbor_id:
                    endpoint = P2PEndpoint(
                        originator=originator,
                        neighbor_id=neighbor_id,
                        local_ip=local_ip,
                        metric=metric,
                        area=area,
                        instance=instance,
                        raw_text=chunk
                    )
                    router.p2p_endpoints.append(endpoint)
                else:
                    self.warnings.append(f"Router {originator} P2P entry missing neighbor id: {chunk}")

            elif item_type == "stub":
                network = kv.get("id")
                netmask = kv.get("data")
                metric_str = kv.get("metric", "10")
                try:
                    metric = int(metric_str)
                except ValueError:
                    metric = 10

                if network and netmask:
                    stub = StubNetwork(
                        network=network,
                        netmask=netmask,
                        metric=metric,
                        originator=originator,
                        area=area,
                        instance=instance
                    )
                    router.stubs.append(stub)
            else:
                # Other types inside router LSA: transit, virtual
                logger.debug("Other body type in router-lsa: %s", item_type)
