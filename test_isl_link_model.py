import unittest

import networkx as nx

from isl_link_model import ISLLinkModel
from routing_engine import RoutingEngine


class ISLLinkModelTests(unittest.TestCase):
    def setUp(self):
        self.model = ISLLinkModel()

    def test_distance_selects_deterministic_service_mode(self):
        near = self.model.evaluate(1000.0)
        far = self.model.evaluate(5000.0)
        unavailable = self.model.evaluate(7000.0)

        self.assertEqual(near["link_state"], "UP")
        self.assertEqual(near["service_mode"], "HIGH")
        self.assertEqual(near["capacity_gbps"], 10.0)

        self.assertEqual(far["link_state"], "DEGRADED")
        self.assertEqual(far["service_mode"], "ROBUST")
        self.assertEqual(far["capacity_gbps"], 1.0)

        self.assertEqual(unavailable["link_state"], "DOWN")
        self.assertFalse(unavailable["routable"])
        self.assertIsNone(unavailable["total_delay_ms"])

    def test_only_isl_edges_are_annotated(self):
        graph = nx.Graph()
        graph.add_edge("SAT-A", "SAT-B", type="ISL", distance_km=1500.0, weight=1500.0)
        graph.add_edge("GS", "SAT-A", type="SGL", distance_km=800.0, weight=800.0)

        self.model.apply_to_graph(graph)

        isl_data = graph["SAT-A"]["SAT-B"]
        sgl_data = graph["GS"]["SAT-A"]
        self.assertEqual(isl_data["link_model"], "isl_proxy_v1")
        self.assertIn("capacity_gbps", isl_data)
        self.assertNotIn("link_model", sgl_data)
        self.assertNotIn("capacity_gbps", sgl_data)

    def test_routing_avoids_down_isl_and_aggregates_proxy_metrics(self):
        graph = nx.Graph()
        graph.add_edge("A", "B", type="ISL", distance_km=7000.0, weight=1.0)
        graph.add_edge("A", "C", type="ISL", distance_km=1000.0, weight=1000.0)
        graph.add_edge("C", "B", type="ISL", distance_km=1500.0, weight=1500.0)
        self.model.apply_to_graph(graph)

        result = RoutingEngine.calculate_shortest_distance_path(graph, "A", "B")

        self.assertTrue(result["success"])
        self.assertEqual(result["path"], ["A", "C", "B"])
        self.assertEqual(result["isl_hops"], 2)
        self.assertEqual(result["isl_bottleneck_capacity_gbps"], 10.0)
        self.assertGreater(result["total_delay_ms"], result["propagation_delay_ms"])
        self.assertGreater(result["expected_packet_loss_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
