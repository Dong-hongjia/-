import math
import numpy as np
import pandas as pd
import networkx as nx
from scipy.spatial import cKDTree
from typing import Dict, Optional, Set, Tuple


class TopologyBuilder:
    """
    星间网络拓扑构建器。
    基于时间切片 (Time Snapshot)，利用矩阵运算瞬间生成全局时变图 (TVG) 拓扑。
    """
    EARTH_RADIUS_KM = 6371.0

    @classmethod
    def _check_pair_visibility(cls, pos1: np.ndarray, pos2: np.ndarray) -> np.ndarray:
        """判断成对卫星连线是否被地球遮挡，输入 Shape 均为 (N, 3)。"""
        r12 = pos2 - pos1
        distances = np.linalg.norm(r12, axis=1)
        visible = np.zeros(len(distances), dtype=bool)
        nonzero = distances > 1e-9
        if not np.any(nonzero):
            return visible

        unit_vectors = r12[nonzero] / distances[nonzero, np.newaxis]
        p = np.sum(-pos1[nonzero] * unit_vectors, axis=1)
        d_sq = np.maximum(
            0.0,
            np.sum(pos1[nonzero] ** 2, axis=1) - p ** 2
        )
        visible[nonzero] = (
            (p < 0)
            | (p > distances[nonzero])
            | (d_sq >= cls.EARTH_RADIUS_KM ** 2)
        )
        return visible

    @staticmethod
    def _terminal_sectors(origins: np.ndarray, targets: np.ndarray, sector_count: int) -> np.ndarray:
        """
        将目标方向投影到卫星局部切平面，并映射到固定方向终端槽位。

        这不是卫星姿态控制器，而是在缺少轨道面和终端姿态数据时，用于避免
        所有 ISL 都集中在同一空间方向的近似终端约束。
        """
        radial = origins / np.linalg.norm(origins, axis=1)[:, np.newaxis]
        references = np.tile(np.array([0.0, 0.0, 1.0]), (len(origins), 1))
        near_pole = np.abs(radial[:, 2]) > 0.95
        references[near_pole] = np.array([0.0, 1.0, 0.0])

        east = np.cross(references, radial)
        east /= np.linalg.norm(east, axis=1)[:, np.newaxis]
        north = np.cross(radial, east)

        direction = targets - origins
        radial_projection = np.sum(direction * radial, axis=1)
        tangent = direction - radial_projection[:, np.newaxis] * radial
        tangent_norm = np.linalg.norm(tangent, axis=1)
        valid = tangent_norm > 1e-9
        tangent[valid] /= tangent_norm[valid, np.newaxis]

        east_component = np.sum(tangent * east, axis=1)
        north_component = np.sum(tangent * north, axis=1)
        azimuth = np.arctan2(east_component, north_component)
        sector_width = 2.0 * math.pi / sector_count
        sectors = np.floor((azimuth + sector_width / 2.0) / sector_width).astype(np.int32)
        sectors %= sector_count
        sectors[~valid] = 0
        return sectors

    @classmethod
    def _terminal_sector(cls, origin: np.ndarray, target: np.ndarray, sector_count: int) -> int:
        """单个方向的终端槽位包装，主要用于少量上一帧保留链路。"""
        return int(cls._terminal_sectors(origin[np.newaxis, :], target[np.newaxis, :], sector_count)[0])

    @classmethod
    def _to_cartesian(cls, lat_deg: np.ndarray, lon_deg: np.ndarray, alt_km: np.ndarray) -> np.ndarray:
        """经纬高转地心空间直角坐标系 (N, 3)"""
        lat_rad = np.radians(lat_deg)
        lon_rad = np.radians(lon_deg)
        r = cls.EARTH_RADIUS_KM + alt_km
        x = r * np.cos(lat_rad) * np.cos(lon_rad)
        y = r * np.cos(lat_rad) * np.sin(lon_rad)
        z = r * np.sin(lat_rad)
        return np.column_stack((x, y, z))

    @classmethod
    def calculate_elevation_angle(cls, gs_pos: np.ndarray, sat_pos: np.ndarray) -> np.ndarray:
        """
        利用空间向量点乘，计算地面站看卫星的仰角 (Elevation Angle)
        参数:
            gs_pos: 地面站 XYZ 向量, Shape (3,)
            sat_pos: 卫星群 XYZ 向量矩阵, Shape (N, 3)
        返回:
            仰角数组 (度), Shape (N,)
        """
        # 1. 计算地面站到卫星的视线向量 V (N, 3)
        v = sat_pos - gs_pos
        v_norm = np.linalg.norm(v, axis=-1)

        # 2. 地面站的天顶方向向量 (即地心指向地面站的单位向量)
        zenith = gs_pos / np.linalg.norm(gs_pos)

        # 3. 计算视线向量与天顶向量的夹角余弦 (向量点乘)
        # v dot zenith = |v| * |zenith| * cos(theta)
        dot_product = np.sum(v * zenith, axis=-1)
        cos_theta = dot_product / v_norm

        # 4. 仰角 = 90度 - 天顶角，所以 sin(仰角) = cos(天顶角)
        # 限制在 [-1, 1] 之间防止浮点误差导致 arcsin 报错
        cos_theta = np.clip(cos_theta, -1.0, 1.0)
        elevation_rad = np.arcsin(cos_theta)

        return np.degrees(elevation_rad)

    @classmethod
    def calculate_sun_vector_ecef(cls, current_time) -> np.ndarray:
        """粗略计算指定 UTC 时刻太阳在 ECEF (地心平赤道) 坐标系下的单位向量"""
        day_of_year = current_time.timetuple().tm_yday
        # 太阳赤纬 (黄赤交角带来的纬度变化)
        sun_lat_deg = 23.44 * math.sin(2 * math.pi / 365.25 * (day_of_year - 80))
        # 太阳经度 (UTC 中午 12 点时，太阳直射 0 度经线附近)
        utc_decimal_hours = current_time.hour + current_time.minute / 60.0 + current_time.second / 3600.0
        sun_lon_deg = 180.0 - (utc_decimal_hours / 24.0 * 360.0)

        lat_rad = math.radians(sun_lat_deg)
        lon_rad = math.radians(sun_lon_deg)

        x = math.cos(lat_rad) * math.cos(lon_rad)
        y = math.cos(lat_rad) * math.sin(lon_rad)
        z = math.sin(lat_rad)
        return np.array([x, y, z])

    @classmethod
    def check_eclipse(cls, sat_pos: np.ndarray, sun_vec: np.ndarray) -> np.ndarray:
        """
        地影圆柱模型检测：判断卫星是否进入地球的阴影区 (Eclipse/UMBRA)
        """
        # 卫星坐标在太阳向量上的投影长度
        p = np.sum(sat_pos * sun_vec, axis=-1)
        # 卫星到地心距离的平方
        sat_r_sq = np.sum(sat_pos ** 2, axis=-1)
        # 卫星到地日连线(圆柱中心轴)垂直距离的平方 (勾股定理)
        d_sq = sat_r_sq - p ** 2
        earth_r_sq = cls.EARTH_RADIUS_KM ** 2

        # 判定条件：卫星在地球背面 (投影 p < 0) 且 落入地球半径形成的圆柱阴影中
        return (p < 0) & (d_sq < earth_r_sq)

    @classmethod
    def build_snapshot_graph(cls,
                             sat_df: pd.DataFrame,
                             max_isl_range_km: float = 5000.0,
                             ground_stations: Dict[str, dict] = None,
                             min_elevation_deg: float = 15.0,
                             max_isl_terminals_per_satellite: int = 4,
                             max_sgl_terminals_per_satellite: int = 1,
                             max_sgl_terminals_per_ground_station: int = 2,
                             previous_graph: Optional[nx.Graph] = None,
                             isl_range_hysteresis_km: float = 200.0,
                             sgl_elevation_hysteresis_deg: float = 2.0) -> nx.Graph:
        """
        构建包含 星间链路(ISL) 和 星地链路(SGL) 的异构拓扑图。

        ISL 使用三维 KD-Tree 搜索候选卫星对。每颗卫星具有固定数量的方向
        终端槽位，上一帧仍满足断开阈值的链路优先保留；新链路按距离建立。

        SGL 分别限制卫星端和地面站端的终端数量，优先保留上一帧链路，
        空闲终端按仰角从高到低连接。建立与断开采用不同阈值以抑制抖动。
        """
        if max_isl_range_km <= 0:
            raise ValueError("max_isl_range_km 必须大于 0")
        if max_isl_terminals_per_satellite <= 0:
            raise ValueError("max_isl_terminals_per_satellite 必须大于 0")
        if max_sgl_terminals_per_satellite <= 0:
            raise ValueError("max_sgl_terminals_per_satellite 必须大于 0")
        if max_sgl_terminals_per_ground_station <= 0:
            raise ValueError("max_sgl_terminals_per_ground_station 必须大于 0")
        if isl_range_hysteresis_km < 0:
            raise ValueError("isl_range_hysteresis_km 不能小于 0")
        if sgl_elevation_hysteresis_deg < 0:
            raise ValueError("sgl_elevation_hysteresis_deg 不能小于 0")

        G = nx.Graph()
        if sat_df.empty:
            return G

        # ==========================================
        # 阶段 1：构建纯星间链路 (ISL)
        # ==========================================
        sat_names = sat_df.index.tolist()
        lats = sat_df['latitude'].values
        lons = sat_df['longitude'].values
        alts = sat_df['altitude_km'].values

        # 将卫星加入图中
        for i, name in enumerate(sat_names):
            G.add_node(name, lat=lats[i], lon=lons[i], alt=alts[i], type='SAT')

        sat_pos = cls._to_cartesian(lats, lons, alts)  # (N, 3)
        sat_index = {name: idx for idx, name in enumerate(sat_names)}

        isl_degrees = np.zeros(len(sat_names), dtype=np.int32)
        occupied_sectors: list[Set[int]] = [set() for _ in sat_names]
        selected_isl_pairs: Set[Tuple[int, int]] = set()

        def add_isl(i: int, j: int, distance: float, age_steps: int,
                    sector_i: Optional[int] = None,
                    sector_j: Optional[int] = None) -> bool:
            if i == j:
                return False
            pair = (min(i, j), max(i, j))
            if pair in selected_isl_pairs:
                return False
            if (isl_degrees[i] >= max_isl_terminals_per_satellite or
                    isl_degrees[j] >= max_isl_terminals_per_satellite):
                return False

            if sector_i is None:
                sector_i = cls._terminal_sector(
                    sat_pos[i], sat_pos[j], max_isl_terminals_per_satellite
                )
            if sector_j is None:
                sector_j = cls._terminal_sector(
                    sat_pos[j], sat_pos[i], max_isl_terminals_per_satellite
                )
            if sector_i in occupied_sectors[i] or sector_j in occupied_sectors[j]:
                return False

            G.add_edge(
                sat_names[i], sat_names[j],
                weight=float(distance),
                distance_km=float(distance),
                type='ISL',
                link_age_steps=age_steps,
                terminal_sector_u=sector_i,
                terminal_sector_v=sector_j
            )
            selected_isl_pairs.add(pair)
            occupied_sectors[i].add(sector_i)
            occupied_sectors[j].add(sector_j)
            isl_degrees[i] += 1
            isl_degrees[j] += 1
            return True

        # 先保留上一帧仍可见、且未超过“断开距离”的 ISL。链路寿命越长越优先。
        retained_isl = []
        if previous_graph is not None:
            for u, v, data in previous_graph.edges(data=True):
                if data.get('type') != 'ISL' or u not in sat_index or v not in sat_index:
                    continue
                i, j = sat_index[u], sat_index[v]
                distance = float(np.linalg.norm(sat_pos[j] - sat_pos[i]))
                if distance > max_isl_range_km + isl_range_hysteresis_km or distance <= 1e-9:
                    continue
                if not cls._check_pair_visibility(sat_pos[[i]], sat_pos[[j]])[0]:
                    continue
                retained_isl.append((
                    -int(data.get('link_age_steps', 1)),
                    distance,
                    i,
                    j,
                    int(data.get('link_age_steps', 1)) + 1
                ))

        sorted_retained_isl = sorted(retained_isl)
        if sorted_retained_isl:
            retained_i = np.array([item[2] for item in sorted_retained_isl], dtype=np.int32)
            retained_j = np.array([item[3] for item in sorted_retained_isl], dtype=np.int32)
            retained_sectors_i = cls._terminal_sectors(
                sat_pos[retained_i], sat_pos[retained_j], max_isl_terminals_per_satellite
            )
            retained_sectors_j = cls._terminal_sectors(
                sat_pos[retained_j], sat_pos[retained_i], max_isl_terminals_per_satellite
            )
            for item_idx, (_, distance, i, j, age_steps) in enumerate(sorted_retained_isl):
                add_isl(
                    i,
                    j,
                    distance,
                    age_steps,
                    sector_i=int(retained_sectors_i[item_idx]),
                    sector_j=int(retained_sectors_j[item_idx])
                )

        # 通过三维 KD-Tree 只找最大通信距离内的卫星对，避免构造 N×N 矩阵。
        tree = cKDTree(sat_pos)
        candidate_pairs = tree.query_pairs(
            r=max_isl_range_km,
            output_type='ndarray'
        )

        if candidate_pairs.size > 0:
            row_idx = candidate_pairs[:, 0]
            col_idx = candidate_pairs[:, 1]
            pos1 = sat_pos[row_idx]
            pos2 = sat_pos[col_idx]
            distances = np.linalg.norm(pos2 - pos1, axis=1)

            # 重复 TLE 索引可能生成空间位置完全相同的伪节点，不为其建立零距离链路。
            nonzero = distances > 1e-9
            row_idx = row_idx[nonzero]
            col_idx = col_idx[nonzero]
            pos1 = pos1[nonzero]
            distances = distances[nonzero]

            if distances.size > 0:
                # 仅对 KD-Tree 返回的候选边执行地球遮挡判断。
                is_visible = cls._check_pair_visibility(pos1, sat_pos[col_idx])

                row_idx = row_idx[is_visible]
                col_idx = col_idx[is_visible]
                distances = distances[is_visible]

                # 批量计算候选边两端的方向终端槽位，避免在 Python 循环中逐边做向量运算。
                sectors_at_row = cls._terminal_sectors(
                    sat_pos[row_idx], sat_pos[col_idx], max_isl_terminals_per_satellite
                )
                sectors_at_col = cls._terminal_sectors(
                    sat_pos[col_idx], sat_pos[row_idx], max_isl_terminals_per_satellite
                )

                # 已保留链路占用终端后，再按距离为剩余方向终端建立新链路。
                order = np.argsort(distances, kind='stable')

                for edge_idx in order:
                    i = int(row_idx[edge_idx])
                    j = int(col_idx[edge_idx])
                    add_isl(
                        i,
                        j,
                        float(distances[edge_idx]),
                        age_steps=1,
                        sector_i=int(sectors_at_row[edge_idx]),
                        sector_j=int(sectors_at_col[edge_idx])
                    )

        # ==========================================
        # 阶段 2：注入地面站 (TN) 并构建星地链路 (SGL)
        # ==========================================
        if ground_stations:
            # 先加入地面站节点，并一次性生成全部 SGL 候选。
            sgl_candidates = {}
            for gs_name, gs_info in ground_stations.items():
                gs_lat = gs_info['lat']
                gs_lon = gs_info['lon']
                gs_alt = gs_info.get('alt', 0.0)  # 地面站默认高度为 0

                # 将地面站加入图中
                G.add_node(gs_name, lat=gs_lat, lon=gs_lon, alt=gs_alt, type='GS')

                # 计算该地面站的 XYZ
                gs_pos = cls._to_cartesian(np.array([gs_lat]), np.array([gs_lon]), np.array([gs_alt]))[0]

                # 批量计算该地面站到所有卫星的物理距离和仰角
                v_to_sats = sat_pos - gs_pos
                distances_to_sats = np.linalg.norm(v_to_sats, axis=-1)
                elevations = cls.calculate_elevation_angle(gs_pos, sat_pos)

                for idx, sat_name in enumerate(sat_names):
                    sgl_candidates[(gs_name, sat_name)] = (
                        float(elevations[idx]),
                        float(distances_to_sats[idx])
                    )

            sat_sgl_degrees = {name: 0 for name in sat_names}
            gs_sgl_degrees = {name: 0 for name in ground_stations}
            selected_sgl_pairs: Set[Tuple[str, str]] = set()

            def add_sgl(gs_name: str, sat_name: str, elevation: float,
                        distance: float, age_steps: int) -> bool:
                pair = (gs_name, sat_name)
                if pair in selected_sgl_pairs:
                    return False
                if gs_sgl_degrees[gs_name] >= max_sgl_terminals_per_ground_station:
                    return False
                if sat_sgl_degrees[sat_name] >= max_sgl_terminals_per_satellite:
                    return False

                G.add_edge(
                    gs_name, sat_name,
                    weight=distance,
                    distance_km=distance,
                    elevation_deg=elevation,
                    type='SGL',
                    link_age_steps=age_steps
                )
                selected_sgl_pairs.add(pair)
                gs_sgl_degrees[gs_name] += 1
                sat_sgl_degrees[sat_name] += 1
                return True

            # 保留链路允许降到略低的断开仰角；长寿命链路优先占用有限终端。
            retained_sgl = []
            if previous_graph is not None:
                for u, v, data in previous_graph.edges(data=True):
                    if data.get('type') != 'SGL':
                        continue
                    if u in ground_stations and v in sat_index:
                        gs_name, sat_name = u, v
                    elif v in ground_stations and u in sat_index:
                        gs_name, sat_name = v, u
                    else:
                        continue
                    elevation, distance = sgl_candidates[(gs_name, sat_name)]
                    if elevation < min_elevation_deg - sgl_elevation_hysteresis_deg:
                        continue
                    retained_sgl.append((
                        -int(data.get('link_age_steps', 1)),
                        -elevation,
                        gs_name,
                        sat_name,
                        elevation,
                        distance,
                        int(data.get('link_age_steps', 1)) + 1
                    ))

            for _, _, gs_name, sat_name, elevation, distance, age_steps in sorted(retained_sgl):
                add_sgl(gs_name, sat_name, elevation, distance, age_steps)

            # 新 SGL 必须达到建立仰角，且优先占用高仰角（通常链路裕量更好）的卫星。
            new_sgl = [
                (-elevation, distance, gs_name, sat_name, elevation)
                for (gs_name, sat_name), (elevation, distance) in sgl_candidates.items()
                if elevation >= min_elevation_deg
            ]
            for _, distance, gs_name, sat_name, elevation in sorted(new_sgl):
                add_sgl(gs_name, sat_name, elevation, distance, age_steps=1)

        return G


# ==========================================
# 本地测试与调试代码
# ==========================================
if __name__ == "__main__":
    print("--- 启动星间网络拓扑构建器测试 ---")

    # 模拟某个时间戳下，5 颗卫星的空间快照位置
    # 场景设定：
    # SAT-A, B, C 在赤道上方，经度相差 15 度，依次相邻。
    # SAT-D 在地球背面（经度180度），与前三者均被地球遮挡。
    # SAT-E 离 A 很近（经度5度），但高度极高（MEO/GEO轨道，50000km）。
    snapshot_data = {
        'latitude': [0.0, 0.0, 0.0, 0.0, 0.0],
        'longitude': [0.0, 15.0, 30.0, 180.0, 5.0],
        'altitude_km': [500.0, 500.0, 500.0, 500.0, 50000.0]
    }
    nodes = ['SAT-A', 'SAT-B', 'SAT-C', 'SAT-D', 'SAT-E']
    df_snapshot = pd.DataFrame(snapshot_data, index=nodes)

    print("\n当前时刻全网节点空间快照:")
    print(df_snapshot)

    # 构建拓扑图，设定最大通信距离为 3000 km
    # SAT-A 到 SAT-B 的弧长距离约 1600+ km，应该能连通。
    # SAT-A 到 SAT-C 约 3300+ km，会因为超出 3000km 阈值而断开。
    MAX_RANGE = 3000.0

    topology = TopologyBuilder.build_snapshot_graph(df_snapshot, max_isl_range_km=MAX_RANGE)

    print(f"\n拓扑构建完成！总节点数: {topology.number_of_nodes()}, 总边数: {topology.number_of_edges()}")

    print("\n网络连通边详情:")
    for u, v, data in topology.edges(data=True):
        print(f"  {u} <---> {v}  | 距离: {data['distance_km']:.2f} km")

    print("\n[高阶路由分析] 寻找从 SAT-A 到 SAT-C 的最短路径 (基于距离权重):")
    try:
        # 使用 Dijkstra 算法寻找总距离最短的路由路径
        path = nx.shortest_path(topology, source='SAT-A', target='SAT-C', weight='weight')
        length = nx.shortest_path_length(topology, source='SAT-A', target='SAT-C', weight='weight')
        print(f"  --> 路由跃点 (Hops): {path}")
        print(f"  --> 端到端总物理距离: {length:.2f} km")
    except nx.NetworkXNoPath:
        print("  --> 警告: 无法找到连通路径 (目标不可达)！")
