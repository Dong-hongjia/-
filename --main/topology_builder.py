import math
import numpy as np
import pandas as pd
import networkx as nx
from scipy.spatial import cKDTree
from typing import List, Dict


class TopologyBuilder:
    """
    星间网络拓扑构建器。
    基于时间切片 (Time Snapshot)，利用矩阵运算瞬间生成全局时变图 (TVG) 拓扑。
    """
    EARTH_RADIUS_KM = 6371.0

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
                             max_neighbors_per_satellite: int = 6) -> nx.Graph:
        """
        构建包含 星间链路(ISL) 和 星地链路(SGL) 的异构拓扑图。

        星间链路使用三维 KD-Tree 搜索通信距离内的候选卫星对，随后执行
        地球遮挡判断，并按距离从短到长保留链路。每颗卫星最多建立
        max_neighbors_per_satellite 条 ISL；该限制不包含星地链路。
        """
        if max_isl_range_km <= 0:
            raise ValueError("max_isl_range_km 必须大于 0")
        if max_neighbors_per_satellite <= 0:
            raise ValueError("max_neighbors_per_satellite 必须大于 0")

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
            r12 = pos2 - pos1
            distances = np.linalg.norm(r12, axis=1)

            # 重复 TLE 索引可能生成空间位置完全相同的伪节点，不为其建立零距离链路。
            nonzero = distances > 1e-9
            row_idx = row_idx[nonzero]
            col_idx = col_idx[nonzero]
            pos1 = pos1[nonzero]
            r12 = r12[nonzero]
            distances = distances[nonzero]

            if distances.size > 0:
                # 仅对 KD-Tree 返回的候选边执行地球遮挡判断。
                unit_vectors = r12 / distances[:, np.newaxis]
                p = np.sum(-pos1 * unit_vectors, axis=1)
                d_sq = np.maximum(0.0, np.sum(pos1 ** 2, axis=1) - p ** 2)
                earth_r_sq = cls.EARTH_RADIUS_KM ** 2
                is_visible = (p < 0) | (p > distances) | (d_sq >= earth_r_sq)

                row_idx = row_idx[is_visible]
                col_idx = col_idx[is_visible]
                distances = distances[is_visible]

                # 优先选择短链路，并保证每颗卫星的 ISL 度数不超过配置上限。
                order = np.argsort(distances, kind='stable')
                isl_degrees = np.zeros(len(sat_names), dtype=np.int32)
                isl_edges = []

                for edge_idx in order:
                    i = int(row_idx[edge_idx])
                    j = int(col_idx[edge_idx])
                    if (isl_degrees[i] >= max_neighbors_per_satellite or
                            isl_degrees[j] >= max_neighbors_per_satellite):
                        continue

                    dist = float(distances[edge_idx])
                    isl_edges.append((
                        sat_names[i],
                        sat_names[j],
                        {'weight': dist, 'distance_km': dist, 'type': 'ISL'}
                    ))
                    isl_degrees[i] += 1
                    isl_degrees[j] += 1

                G.add_edges_from(isl_edges)

        # ==========================================
        # 阶段 2：注入地面站 (TN) 并构建星地链路 (SGL)
        # ==========================================
        if ground_stations:
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

                # 判定条件：仰角必须大于设定的最小阈值 (比如 15度)
                valid_sats_idx = np.where(elevations >= min_elevation_deg)[0]

                sgl_edges = []
                for idx in valid_sats_idx:
                    sat_name = sat_names[idx]
                    dist = distances_to_sats[idx]
                    sgl_edges.append((gs_name, sat_name, {'weight': dist, 'distance_km': dist, 'type': 'SGL'}))

                G.add_edges_from(sgl_edges)

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
