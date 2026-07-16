import unittest

import pandas as pd

from topology_builder import TopologyBuilder


class TopologyBuilderTerminalTests(unittest.TestCase):
    @staticmethod
    def snapshot(longitudes):
        names = [f"SAT-{idx}" for idx in range(len(longitudes))]
        return pd.DataFrame(
            {
                "latitude": [0.0] * len(longitudes),
                "longitude": longitudes,
                "altitude_km": [550.0] * len(longitudes),
            },
            index=names,
        )

    def test_isl_terminal_limit_and_stability(self):
        snapshot = self.snapshot([-12, -8, -4, 0, 4, 8, 12])
        first = TopologyBuilder.build_snapshot_graph(
            snapshot,
            max_isl_range_km=3500.0,
            max_isl_terminals_per_satellite=2,
        )
        second = TopologyBuilder.build_snapshot_graph(
            snapshot,
            max_isl_range_km=3500.0,
            max_isl_terminals_per_satellite=2,
            previous_graph=first,
        )

        for satellite in snapshot.index:
            isl_degree = sum(
                data["type"] == "ISL"
                for _, _, data in first.edges(satellite, data=True)
            )
            self.assertLessEqual(isl_degree, 2)

        self.assertEqual(set(first.edges()), set(second.edges()))
        self.assertTrue(
            all(data["link_age_steps"] == 2 for _, _, data in second.edges(data=True))
        )

    def test_isl_distance_hysteresis(self):
        initial = self.snapshot([0.0, 8.0])
        moved = self.snapshot([0.0, 9.0])

        first = TopologyBuilder.build_snapshot_graph(
            initial,
            max_isl_range_km=1000.0,
            max_isl_terminals_per_satellite=2,
            isl_range_hysteresis_km=200.0,
        )
        retained = TopologyBuilder.build_snapshot_graph(
            moved,
            max_isl_range_km=1000.0,
            max_isl_terminals_per_satellite=2,
            previous_graph=first,
            isl_range_hysteresis_km=200.0,
        )
        fresh = TopologyBuilder.build_snapshot_graph(
            moved,
            max_isl_range_km=1000.0,
            max_isl_terminals_per_satellite=2,
            isl_range_hysteresis_km=200.0,
        )

        self.assertEqual(first.number_of_edges(), 1)
        self.assertEqual(retained.number_of_edges(), 1)
        self.assertEqual(fresh.number_of_edges(), 0)

    def test_sgl_terminal_limits_and_elevation_hysteresis(self):
        ground_stations = {
            "GS-1": {"lat": 0.0, "lon": 0.0, "alt": 0.0},
            "GS-2": {"lat": 0.0, "lon": 0.0, "alt": 0.0},
        }
        initial = self.snapshot([0.0, 2.0, -2.0, 4.0, -4.0])
        graph = TopologyBuilder.build_snapshot_graph(
            initial,
            max_isl_range_km=100.0,
            ground_stations=ground_stations,
            min_elevation_deg=15.0,
            max_sgl_terminals_per_satellite=1,
            max_sgl_terminals_per_ground_station=2,
        )

        for satellite in initial.index:
            sgl_degree = sum(
                data["type"] == "SGL"
                for _, _, data in graph.edges(satellite, data=True)
            )
            self.assertLessEqual(sgl_degree, 1)
        for station in ground_stations:
            sgl_degree = sum(
                data["type"] == "SGL"
                for _, _, data in graph.edges(station, data=True)
            )
            self.assertLessEqual(sgl_degree, 2)

        one_station = {"GS": ground_stations["GS-1"]}
        above_threshold = self.snapshot([12.0])
        below_threshold = self.snapshot([12.5])
        first = TopologyBuilder.build_snapshot_graph(
            above_threshold,
            max_isl_range_km=100.0,
            ground_stations=one_station,
            min_elevation_deg=15.0,
            sgl_elevation_hysteresis_deg=2.0,
        )
        retained = TopologyBuilder.build_snapshot_graph(
            below_threshold,
            max_isl_range_km=100.0,
            ground_stations=one_station,
            min_elevation_deg=15.0,
            previous_graph=first,
            sgl_elevation_hysteresis_deg=2.0,
        )
        fresh = TopologyBuilder.build_snapshot_graph(
            below_threshold,
            max_isl_range_km=100.0,
            ground_stations=one_station,
            min_elevation_deg=15.0,
            sgl_elevation_hysteresis_deg=2.0,
        )

        self.assertEqual(first.number_of_edges(), 1)
        self.assertEqual(retained.number_of_edges(), 1)
        self.assertEqual(fresh.number_of_edges(), 0)


if __name__ == "__main__":
    unittest.main()
