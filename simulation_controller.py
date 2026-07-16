import pandas as pd
import numpy as np
import networkx as nx
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# 导入我们之前编写的四大核心模块
from tle_manager import TLEManager
from topology_builder import TopologyBuilder
from routing_engine import RoutingEngine
from isl_link_model import ISLLinkModel, ISLLinkModelConfig


class SimulationController:
    """
    NTN-TN 网络全链路自动化仿真控制器。
    协调 TLE 读取、轨道外推、动态拓扑构建与路由寻址。
    """

    def __init__(self,
                 tle_file_path: str,
                 start_time_utc: datetime,
                 duration_minutes: float = 10.0,
                 step_seconds: float = 1.0,
                 max_isl_range_km: float = 5000.0,
                 max_isl_terminals_per_satellite: int = 4,
                 max_sgl_terminals_per_satellite: int = 1,
                 max_sgl_terminals_per_ground_station: int = 2,
                 isl_range_hysteresis_km: float = 200.0,
                 sgl_elevation_hysteresis_deg: float = 2.0,
                 isl_link_model_config: Optional[ISLLinkModelConfig] = None):
        self.tle_file_path = tle_file_path
        self.start_time = start_time_utc
        self.duration_minutes = duration_minutes
        self.step_seconds = step_seconds
        self.max_isl_range_km = max_isl_range_km
        self.max_isl_terminals_per_satellite = max_isl_terminals_per_satellite
        self.max_sgl_terminals_per_satellite = max_sgl_terminals_per_satellite
        self.max_sgl_terminals_per_ground_station = max_sgl_terminals_per_ground_station
        self.isl_range_hysteresis_km = isl_range_hysteresis_km
        self.sgl_elevation_hysteresis_deg = sgl_elevation_hysteresis_deg
        self.isl_link_model = ISLLinkModel(isl_link_model_config)

        self.trajectories: Dict[str, pd.DataFrame] = {}
        self.time_index: List[datetime] = []
        self.previous_topology: Optional[nx.Graph] = None
        self._isl_model_activation_printed = False

        # 全局注册的固定地面节点 (TN)
        self.ground_stations = {
            "GS-Beijing": {"lat": 39.9042, "lon": 116.4074, "alt": 0.0},
            "GS-Singapore": {"lat": 1.3521, "lon": 103.8198, "alt": 0.0}
        }
        # 【第一步新增】：为每颗卫星维护当前电量 (满电为 100.0)
        self.battery_states: Dict[str, float] = {}

    def reset_topology_state(self) -> None:
        """清除上一帧拓扑，用于开始新仿真或播放重置。"""
        self.previous_topology = None
        self._isl_model_activation_printed = False

    def build_topology(self, snapshot_df: pd.DataFrame) -> nx.Graph:
        """构建带终端约束和链路滞回的拓扑，并保存为下一帧的参考状态。"""
        graph = TopologyBuilder.build_snapshot_graph(
            snapshot_df,
            self.max_isl_range_km,
            ground_stations=self.ground_stations,
            min_elevation_deg=15.0,
            max_isl_terminals_per_satellite=self.max_isl_terminals_per_satellite,
            max_sgl_terminals_per_satellite=self.max_sgl_terminals_per_satellite,
            max_sgl_terminals_per_ground_station=self.max_sgl_terminals_per_ground_station,
            previous_graph=self.previous_topology,
            isl_range_hysteresis_km=self.isl_range_hysteresis_km,
            sgl_elevation_hysteresis_deg=self.sgl_elevation_hysteresis_deg
        )
        # 拓扑层只决定链路是否具备建链资格；此处仅评估 ISL 的网络层代理指标。
        # SGL 边不会被 ISLLinkModel 修改。
        self.isl_link_model.apply_to_graph(graph)

        if not self._isl_model_activation_printed:
            stats = self.isl_link_model.summarize_graph(graph)
            print(
                "[+] ISL 近似链路模型已生效: "
                f"评估 {stats['total']} 条 ISL "
                f"(UP={stats['up']}, DEGRADED={stats['degraded']}, DOWN={stats['down']})"
            )
            self._isl_model_activation_printed = True

        self.previous_topology = graph
        return graph

    def setup_environment(self, max_satellites: int = 50) -> List[str]:
        print("\n=== [阶段 1] 环境初始化与轨道预计算 ===")
        print(f"[*] 正在读取本地 TLE 数据: {self.tle_file_path}")
        print(f"[*] ISL 近似链路模型: {self.isl_link_model.configuration_summary()}")
        print("[*] 模型边界: 仅评估星间链路，星地链路保持原有几何拓扑逻辑。")

        manager = TLEManager(self.tle_file_path)
        all_sats = manager.get_satellite_names()

        if not all_sats:
            raise ValueError("TLE 文件中未解析到任何有效卫星。")

        target_sats = all_sats[:max_satellites]
        print(f"[*] 筛选出 {len(target_sats)} 颗卫星参与本次仿真...")

        # 【初始化电量】：发给它们每人一块满格电池
        self.battery_states = {name: 100.0 for name in target_sats}

        propagators = manager.create_batch_propagators(target_sats)

        print(f"[*] 开始并行推算 {self.duration_minutes} 分钟的轨道时序数据...")
        for name, prog in propagators.items():
            df = prog.propagate(self.start_time, self.duration_minutes, self.step_seconds)
            self.trajectories[name] = df

        if self.trajectories:
            first_sat_name = list(self.trajectories.keys())[0]
            self.time_index = self.trajectories[first_sat_name].index.tolist()

        print("[+] 轨道预计算完成！\n")
        return list(self.ground_stations.keys()) + target_sats

    def _get_snapshot(self, current_time: datetime) -> pd.DataFrame:
        snapshot_data = {'latitude': [], 'longitude': [], 'altitude_km': []}
        node_names = []

        for name, df in self.trajectories.items():
            try:
                row = df.loc[current_time]
                node_names.append(name)
                snapshot_data['latitude'].append(row['latitude'])
                snapshot_data['longitude'].append(row['longitude'])
                snapshot_data['altitude_km'].append(row['altitude_km'])
            except KeyError:
                continue

        return pd.DataFrame(snapshot_data, index=node_names)

    # ==========================================
    # 【第一步新增】：电量模型处理引擎
    # ==========================================
    def process_battery_model(self, snapshot_df: pd.DataFrame, current_time: datetime) -> pd.DataFrame:
        """
        物理电量模型处理：
        1. 计算哪些卫星在地球阴影区。
        2. 更新电量。
        3. 剔除电量耗尽的宕机卫星。
        """
        sat_names = snapshot_df.index.tolist()
        if not sat_names:
            return snapshot_df

        lats = snapshot_df['latitude'].values
        lons = snapshot_df['longitude'].values
        alts = snapshot_df['altitude_km'].values

        sat_pos = TopologyBuilder._to_cartesian(lats, lons, alts)
        sun_vec = TopologyBuilder.calculate_sun_vector_ecef(current_time)
        in_eclipse = TopologyBuilder.check_eclipse(sat_pos, sun_vec)

        active_sats = []
        for i, sat in enumerate(sat_names):
            battery = self.battery_states.get(sat, 100.0)

            if in_eclipse[i]:
                # 在阴影区：无法使用太阳能，以 1.0%/秒 疯狂耗电
                battery -= (1.0 * self.step_seconds)
            else:
                # 在光照区：太阳能帆板供电，以 0.5%/秒 充电
                battery += (0.5 * self.step_seconds)

            battery = max(0.0, min(100.0, battery))
            self.battery_states[sat] = battery

            # 只有电量 > 0 的卫星才被允许参与本次网络拓扑！
            if battery > 0:
                active_sats.append(sat)

        # 仅返回依然存活 (没被饿死) 的卫星数据
        return snapshot_df.loc[active_sats]

    def run_simulation(self, source_node: str, target_node: str, output_csv: str = "simulation_results.csv",
                       strategy: str = "shortest_distance") -> pd.DataFrame:
        print(f"\n=== [阶段 2] 步进式动态拓扑与路由仿真 ===")
        print(f"[*] 路由任务: {source_node}  ------>  {target_node}")
        print(f"[*] 路由策略: {strategy}")
        print(f"[*] 仿真总步数: {len(self.time_index)} 步")
        print("-" * 60)

        results_log = []
        last_path = None
        self.reset_topology_state()

        for step, current_time in enumerate(self.time_index):
            time_str = current_time.strftime("%H:%M:%S")
            snapshot_df = self._get_snapshot(current_time)

            # 2. 【电量模型接管】：过滤掉被“饿死”的宕机卫星
            snapshot_df = self.process_battery_model(snapshot_df, current_time)

            graph = self.build_topology(snapshot_df)
            isl_stats = self.isl_link_model.summarize_graph(graph)

            if strategy == "shortest_distance":
                route_res = RoutingEngine.calculate_shortest_distance_path(graph, source_node, target_node)
            else:
                route_res = RoutingEngine.calculate_minimum_hops_path(graph, source_node, target_node)

            status_tag = "[失败]"
            handover_flag = False

            if route_res['success']:
                status_tag = "[通畅]"
                current_path = route_res['path']
                if last_path is not None and current_path != last_path:
                    handover_flag = True
                last_path = current_path
            else:
                last_path = None

            if step % 60 == 0 or handover_flag:  # 减少日常打印频率，但切换必打
                event_mark = "⚠️ 路由切换" if handover_flag else "        "

                # 顺便抽查一颗存活卫星的电量看看
                sample_sat = snapshot_df.index[1] if not snapshot_df.empty else "N/A"
                batt_info = f"| 抽查 {sample_sat} 电量: {self.battery_states.get(sample_sat, 0):.1f}%"
                model_info = (
                    f"| ISL状态 UP/DEG/DOWN: {isl_stats['up']}/"
                    f"{isl_stats['degraded']}/{isl_stats['down']}"
                )

                if route_res['success']:
                    bottleneck = route_res['isl_bottleneck_capacity_gbps']
                    bottleneck_info = (
                        f"{bottleneck:.2f}Gbps" if bottleneck is not None else "N/A"
                    )
                    print(
                        f"[{time_str}] {status_tag} {event_mark} "
                        f"| 传播时延: {route_res['propagation_delay_ms']:>6.2f}ms "
                        f"| 估算总时延: {route_res['total_delay_ms']:>6.2f}ms "
                        f"| 跳数: {route_res['hops']} (ISL {route_res['isl_hops']}) "
                        f"| ISL瓶颈: {bottleneck_info} "
                        f"| 期望丢包: {route_res['expected_packet_loss_rate']:.3e} "
                        f"{model_info} {batt_info}"
                    )
                else:
                    print(
                        f"[{time_str}] {status_tag} {event_mark} "
                        f"| 网络不可达 (割裂)! {model_info} {batt_info}"
                    )

            results_log.append({
                'timestamp': current_time,
                'is_success': route_res['success'],
                'is_handover': handover_flag,
                'hops': route_res['hops'] if route_res['success'] else np.nan,
                'distance_km': route_res['total_distance_km'] if route_res['success'] else np.nan,
                'delay_ms': route_res['propagation_delay_ms'] if route_res['success'] else np.nan,
                'total_delay_ms': route_res['total_delay_ms'] if route_res['success'] else np.nan,
                'isl_hops': route_res['isl_hops'] if route_res['success'] else np.nan,
                'isl_bottleneck_capacity_gbps': route_res['isl_bottleneck_capacity_gbps'] if route_res['success'] else np.nan,
                'expected_packet_loss_rate': route_res['expected_packet_loss_rate'] if route_res['success'] else np.nan,
                'min_proxy_margin_db': route_res['min_proxy_margin_db'] if route_res['success'] else np.nan,
                'path_str': ' -> '.join(route_res['path']) if route_res['success'] else ""
            })

        print("-" * 60)
        df_results = pd.DataFrame(results_log)
        df_results.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"[+] 仿真日志已导出至: {output_csv}")

        return df_results

    @staticmethod
    def generate_summary_report(df: pd.DataFrame, step_seconds: float = 1.0):
        """
        基于 Pandas 的专业 QoS 分析报告生成器
        """
        print("\n==================================================")
        print("📊 NTN-TN 端到端 QoS 离线评估报告")
        print("==================================================")

        total_steps = len(df)
        total_duration = total_steps * step_seconds

        # 1. 连通性分析
        success_count = df['is_success'].sum()
        availability = (success_count / total_steps) * 100

        # 计算最大连续中断时间
        # 找到所有 is_success 为 False 的连续区间
        df['downtime_block'] = (df['is_success'] != df['is_success'].shift()).cumsum()
        downtime_blocks = df[df['is_success'] == False]
        if not downtime_blocks.empty:
            max_downtime_steps = downtime_blocks.groupby('downtime_block').size().max()
            max_downtime = max_downtime_steps * step_seconds
        else:
            max_downtime = 0.0

        print("[1] 连通性分析 (Availability)")
        print(f"    - 总仿真时长:     {total_duration:.1f} 秒")
        print(f"    - 链路连通率:     {availability:.2f} %")
        print(f"    - 最大连续中断:   {max_downtime:.1f} 秒")

        # 2. 时延分析
        connected_df = df[df['is_success'] == True]
        if not connected_df.empty:
            avg_delay = connected_df['delay_ms'].mean()
            max_delay = connected_df['delay_ms'].max()
            min_delay = connected_df['delay_ms'].min()
            jitter_std = connected_df['delay_ms'].std()
            p99_delay = connected_df['delay_ms'].quantile(0.99)

            # 找到发生最大延迟的具体时间
            max_delay_row = connected_df.loc[connected_df['delay_ms'].idxmax()]
            max_delay_time = max_delay_row['timestamp'].strftime("%H:%M:%S") if isinstance(max_delay_row['timestamp'],
                                                                                           datetime) else max_delay_row[
                'timestamp']

            print("\n[2] 时延分析 (Delay & Jitter)")
            print(f"    - 平均时延:       {avg_delay:.2f} ms")
            print(f"    - 最小时延:       {min_delay:.2f} ms")
            print(f"    - 最大时延:       {max_delay:.2f} ms (发生在 {max_delay_time})")
            print(f"    - 时延抖动(Std):  {jitter_std:.2f} ms")
            print(f"    - P99 时延:       {p99_delay:.2f} ms")
        else:
            print("\n[2] 时延分析 (Delay & Jitter)")
            print("    - 警告: 仿真期间网络从未连通，无时延数据。")

        # 3. 拓扑与路由稳定性
        handovers = df['is_handover'].sum()
        avg_route_duration = total_duration / (handovers + 1) if handovers >= 0 else 0

        if not connected_df.empty:
            avg_hops = connected_df['hops'].mean()
            max_hops = connected_df['hops'].max()
            print("\n[3] 拓扑与路由稳定性 (Routing Stability)")
            print(f"    - 平均跳数:       {avg_hops:.1f} Hops (最大 {max_hops:.0f} Hops)")
            print(f"    - 路由切换次数:   {handovers} 次")
            print(f"    - 路由平均寿命:   {avg_route_duration:.1f} 秒/次")
        else:
            print("\n[3] 拓扑与路由稳定性 (Routing Stability)")
            print("    - 警告: 仿真期间网络从未连通，无路由数据。")

        # 4. ISL 确定性代理链路模型结果（SGL 不在本节统计范围内）
        if not connected_df.empty and 'isl_bottleneck_capacity_gbps' in connected_df:
            isl_route_df = connected_df[connected_df['isl_hops'] > 0]
            print("\n[4] ISL 近似链路模型 (Deterministic Proxy)")
            if not isl_route_df.empty:
                print(
                    f"    - 平均估算总时延: "
                    f"{isl_route_df['total_delay_ms'].mean():.2f} ms"
                )
                print(
                    f"    - 平均瓶颈容量:   "
                    f"{isl_route_df['isl_bottleneck_capacity_gbps'].mean():.2f} Gbps"
                )
                print(
                    f"    - 平均期望丢包率: "
                    f"{isl_route_df['expected_packet_loss_rate'].mean():.3e}"
                )
                print(
                    f"    - 最低代理裕量:   "
                    f"{isl_route_df['min_proxy_margin_db'].min():.2f} dB"
                )
                print("    - 说明: 以上为 ISL 网络层代理指标，不是真实激光信道测量值。")
            else:
                print("    - 当前成功路径不包含 ISL，暂无代理链路指标。")

        print("==================================================\n")


# ==========================================
# 仿真主程序入口 (Headless / 离线模式测试)
# ==========================================
if __name__ == "__main__":
    # 配置仿真参数
    REAL_TLE_FILE = r"C:\Users\dongh\Desktop\shixi\TLE.txt"  # 你的本地真实文件路径

    # 假设从明天开始仿真
    sim_start = datetime.now(timezone.utc) + timedelta(days=1)

    try:
        # 实例化控制器 (仿真时长设定长一点，比如 30 分钟，更能看出效果)
        controller = SimulationController(
            tle_file_path=REAL_TLE_FILE,
            start_time_utc=sim_start,
            duration_minutes=20.0, #min
            step_seconds=1.0,  #s
            max_isl_range_km=6000.0,  # 链路最大建立距离
            max_isl_terminals_per_satellite=4,
            max_sgl_terminals_per_satellite=1,
            max_sgl_terminals_per_ground_station=2,
            isl_range_hysteresis_km=200.0,
            sgl_elevation_hysteresis_deg=2.0
        )

        active_nodes = controller.setup_environment(max_satellites=50)

        # 选择通信源和目的节点 (我们直接测试地面站到地面站的跨国链路！)
        SRC = "GS-Beijing"
        DST = "GS-Singapore"

        # 确保这两个节点在环境中
        if SRC in active_nodes and DST in active_nodes:
            # 运行仿真并获取结果 DataFrame
            csv_path = "routing_simulation_report.csv"
            df_results = controller.run_simulation(
                source_node=SRC,
                target_node=DST,
                output_csv=csv_path,
                strategy="shortest_distance"  # 可以换成 "min_hops" 对比测试
            )

            # 🔥 调用全新编写的报告生成器
            SimulationController.generate_summary_report(df_results, step_seconds=controller.step_seconds)

        else:
            print(f"错误: 节点 {SRC} 或 {DST} 不在活动节点列表中。")

    except Exception as e:
        print(f"仿真过程中发生严重错误: {e}")
