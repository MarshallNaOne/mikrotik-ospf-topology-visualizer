"""Comprehensive unit tests for OSPF LSDB Parser and Topology Matching using standard unittest."""

import unittest
from ospf_viz.models import LinkMatchStatus
from ospf_viz.parser import LSAParser
from ospf_viz.topology import TopologyBuilder


SAMPLE_THREE_PARALLEL_LINKS = """
0 instance=default-v2 area=area0 type="router" originator=10.64.1.1 id=10.64.1.1
  body=
    type=p2p id=10.64.1.8 data=10.0.0.14 metric=3000
    type=stub id=10.0.0.12 data=255.255.255.252 metric=3000
    type=p2p id=10.64.1.8 data=10.0.0.22 metric=3200
    type=stub id=10.0.0.20 data=255.255.255.252 metric=3200
    type=p2p id=10.64.1.8 data=10.0.0.26 metric=3100
    type=stub id=10.0.0.24 data=255.255.255.252 metric=3100

1 instance=default-v2 area=area0 type="router" originator=10.64.1.8 id=10.64.1.8
  body=
    type=p2p id=10.64.1.1 data=10.0.0.13 metric=3000
    type=stub id=10.0.0.12 data=255.255.255.252 metric=3000
    type=p2p id=10.64.1.1 data=10.0.0.21 metric=3200
    type=stub id=10.0.0.20 data=255.255.255.252 metric=3200
    type=p2p id=10.64.1.1 data=10.0.0.25 metric=3100
    type=stub id=10.0.0.24 data=255.255.255.252 metric=3100
"""

SAMPLE_ASYMMETRIC_AND_MISSING = """
0 instance=default-v2 area=area0 type="router" originator=10.64.1.1 id=10.64.1.1
  body=
    type=p2p id=10.64.1.2 data=10.0.1.1 metric=50
    type=stub id=10.0.1.0 data=255.255.255.252 metric=50
    type=p2p id=10.64.1.99 data=10.0.99.1 metric=100

1 instance=default-v2 area=area0 type="router" originator=10.64.1.2 id=10.64.1.2
  body=
    type=p2p id=10.64.1.1 data=10.0.1.2 metric=500
    type=stub id=10.0.1.0 data=255.255.255.252 metric=500
"""

SAMPLE_MIXED_LSA_TYPES = """
0 instance=default-v2 area=area0 type="router" originator=10.64.1.1 id=10.64.1.1
  body=
    type=p2p id=10.64.1.2 data=10.0.1.1 metric=10
    type=stub id=10.0.1.0 data=255.255.255.252 metric=10

1 instance=default-v2 area=area0 type="external" originator=10.64.1.1 id=0.0.0.0
  body=
    netmask=0.0.0.0 forward-address=0.0.0.0 metric=10

2 instance=default-v2 area=area0 type="opaque-area" originator=10.64.1.2 id=1.0.0.0
  body=
    data=something

3 instance=default-v2 area=area0 type="router" originator=10.64.1.2 id=10.64.1.2
  body=
    type=p2p id=10.64.1.1 data=10.0.1.2 metric=10
    type=stub id=10.0.1.0 data=255.255.255.252 metric=10
"""

SAMPLE_MULTI_AREA_INSTANCE = """
0 instance=ospf-core area=backbone type="router" originator=10.64.1.1 id=10.64.1.1
  body=
    type=p2p id=10.64.1.2 data=10.10.10.1 metric=15
    type=stub id=10.10.10.0 data=255.255.255.252 metric=15

1 instance=ospf-core area=backbone type="router" originator=10.64.1.2 id=10.64.1.2
  body=
    type=p2p id=10.64.1.1 data=10.10.10.2 metric=15
    type=stub id=10.10.10.0 data=255.255.255.252 metric=15
"""

SAMPLE_SYNTHETIC_TOPOLOGY_WITH_FLAGS = """
Flags: S - SELF-ORIGINATED; D - DYNAMIC
 0   D instance=default-v2 type="external" originator=10.0.0.8 id=10.100.0.0
       sequence=0x80000609 age=1435 checksum=0x2795 body=
          options=E netmask=255.255.255.0 metric=1 type-1

 1  SD instance=default-v2 area=area0 type="router" originator=10.0.0.1
       id=10.0.0.1 sequence=0x8000C9A5 age=425 checksum=0xF413 body=
          options=E bits=E
              type=p2p id=10.0.0.2 data=192.168.1.1 metric=100
              type=stub id=192.168.1.0 data=255.255.255.252 metric=100
              type=p2p id=10.0.0.3 data=192.168.2.1 metric=500
              type=stub id=192.168.2.0 data=255.255.255.252 metric=500
              type=p2p id=10.0.0.99 data=192.168.99.1 metric=1000

 2   D instance=default-v2 area=area0 type="router" originator=10.0.0.2
       id=10.0.0.2 sequence=0x8000A1B2 age=310 checksum=0x1234 body=
          options=E bits=E
              type=p2p id=10.0.0.1 data=192.168.1.2 metric=100
              type=stub id=192.168.1.0 data=255.255.255.252 metric=100
              type=p2p id=10.0.0.3 data=192.168.3.1 metric=200
              type=stub id=192.168.3.0 data=255.255.255.252 metric=200

 3   D instance=default-v2 area=area0 type="router" originator=10.0.0.3
       id=10.0.0.3 sequence=0x8000B2C3 age=120 checksum=0x5678 body=
          options=E bits=E
              type=p2p id=10.0.0.1 data=192.168.2.2 metric=50
              type=stub id=192.168.2.0 data=255.255.255.252 metric=50
              type=p2p id=10.0.0.2 data=192.168.3.2 metric=200
              type=stub id=192.168.3.0 data=255.255.255.252 metric=200
"""


class TestOSPFParserAndTopology(unittest.TestCase):

    def test_parser_basic(self):
        parser = LSAParser()
        routers = parser.parse(SAMPLE_THREE_PARALLEL_LINKS)
        self.assertIn("10.64.1.1", routers)
        self.assertIn("10.64.1.8", routers)
        self.assertEqual(len(routers["10.64.1.1"].p2p_endpoints), 3)
        self.assertEqual(len(routers["10.64.1.8"].p2p_endpoints), 3)
        self.assertEqual(len(routers["10.64.1.1"].stubs), 3)

    def test_three_parallel_links_preserved(self):
        """Verify that 3 parallel links between the SAME router IDs are kept distinct."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_THREE_PARALLEL_LINKS)

        builder = TopologyBuilder()
        graph, links, warnings = builder.build_topology(routers)

        # Must be 3 distinct links
        self.assertEqual(len(links), 3)
        # Graph must have 3 edges between 10.64.1.1 and 10.64.1.8
        self.assertEqual(graph.number_of_edges("10.64.1.1", "10.64.1.8"), 3)

        subnets = {l.subnet for l in links}
        self.assertIn("10.0.0.12/30", subnets)
        self.assertIn("10.0.0.20/30", subnets)
        self.assertIn("10.0.0.24/30", subnets)

        # Check distinct IDs
        link_ids = [l.id for l in links]
        self.assertEqual(len(set(link_ids)), 3)

        # All should be MATCHED and symmetric
        for l in links:
            self.assertEqual(l.status, LinkMatchStatus.MATCHED)
            self.assertFalse(l.is_asymmetric)

    def test_asymmetric_metrics(self):
        """Verify that asymmetric metrics are preserved and flagged with warning."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_ASYMMETRIC_AND_MISSING)

        builder = TopologyBuilder()
        graph, links, warnings = builder.build_topology(routers)

        # Link between 10.64.1.1 and 10.64.1.2 has 50 and 500
        matched_link = next(l for l in links if "10.64.1.2" in (l.router_a, l.router_b) and "10.64.1.1" in (l.router_a, l.router_b))
        self.assertTrue(matched_link.is_asymmetric)
        self.assertEqual(matched_link.status, LinkMatchStatus.ASYMMETRIC)

        if matched_link.router_a == "10.64.1.1":
            self.assertEqual(matched_link.metric_a_to_b, 50)
            self.assertEqual(matched_link.metric_b_to_a, 500)
        else:
            self.assertEqual(matched_link.metric_a_to_b, 500)
            self.assertEqual(matched_link.metric_b_to_a, 50)

    def test_router_id_without_own_lsa_and_one_way(self):
        """Verify router 10.64.1.99 is created with has_lsa=False and one-way link."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_ASYMMETRIC_AND_MISSING)

        builder = TopologyBuilder()
        graph, links, warnings = builder.build_topology(routers)

        self.assertIn("10.64.1.99", routers)
        self.assertFalse(routers["10.64.1.99"].has_lsa)

        one_way_link = next(l for l in links if l.router_b == "10.64.1.99" or l.router_a == "10.64.1.99")
        self.assertEqual(one_way_link.status, LinkMatchStatus.ONE_WAY)
        self.assertTrue(one_way_link.is_one_way)

    def test_external_and_opaque_lsa_ignored_gracefully(self):
        """Verify external and opaque LSAs do not crash parser or pollute topology."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_MIXED_LSA_TYPES)

        self.assertEqual(len(routers), 2)
        self.assertIn("10.64.1.1", routers)
        self.assertIn("10.64.1.2", routers)

        builder = TopologyBuilder()
        graph, links, warnings = builder.build_topology(routers)
        self.assertEqual(len(links), 1)
        self.assertEqual(graph.number_of_nodes(), 2)

    def test_multiple_areas_and_instances(self):
        """Verify area and instance parsing."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_MULTI_AREA_INSTANCE)

        r1 = routers["10.64.1.1"]
        self.assertIn("backbone", r1.areas)
        self.assertIn("ospf-core", r1.instances)

        builder = TopologyBuilder()
        graph, links, _ = builder.build_topology(routers)
        self.assertEqual(links[0].area, "backbone")
        self.assertEqual(links[0].instance, "ospf-core")

    def test_malformed_input(self):
        """Verify that corrupt strings and empty lines are handled without uncaught exceptions."""
        parser = LSAParser()
        routers = parser.parse(" random gibberish !!! \n  another invalid line \n")
        self.assertEqual(len(routers), 0)

        builder = TopologyBuilder()
        graph, links, _ = builder.build_topology(routers)
        self.assertEqual(len(links), 0)
        self.assertEqual(graph.number_of_nodes(), 0)

    def test_synthetic_topology_with_flags(self):
        """Verify parsing with RouterOS flags SD, D, S and asymmetric/one-way links."""
        parser = LSAParser()
        routers = parser.parse(SAMPLE_SYNTHETIC_TOPOLOGY_WITH_FLAGS)
        self.assertEqual(len(routers), 3)

        builder = TopologyBuilder()
        graph, links, warnings = builder.build_topology(routers)

        self.assertEqual(graph.number_of_nodes(), 4)
        self.assertEqual(len(links), 4)

        # 10.0.0.99 has no own LSA, created by builder
        self.assertIn("10.0.0.99", routers)
        self.assertFalse(routers["10.0.0.99"].has_lsa)

        # Asymmetric link between 10.0.0.1 and 10.0.0.3 (metrics 500 and 50)
        asym = [l for l in links if l.is_asymmetric]
        self.assertEqual(len(asym), 1)

        # One way link to 10.0.0.99
        one_way = [l for l in links if l.is_one_way]
        self.assertEqual(len(one_way), 1)


if __name__ == "__main__":
    unittest.main()
