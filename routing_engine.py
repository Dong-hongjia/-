import networkx as nx
from typing import Dict, List, Optional, Any


class RoutingEngine:
    """
    星地/星间网络路由仿真引擎。
    支持在动态时变图 (TVG) 的单帧快照上执行多种路由策略。
    """

    # 光速，单位：千米/秒 (km/s)，用于计算传播时延
    SPEED_OF_LIGHT_KM_S = 299792.458

    @classmethod
    def calculate_shortest_distance_path(cls,
                                         graph: nx.Graph,
                                         source: str,
                                         target: str) -> Dict[str, Any]:
        """
        策略 1: 最短物理距离路由 (Dijkstra 算法)
        寻找端到端物理距离最短、传播时延最低的路径。
        """
        return cls._execute_routing(graph, source, target, weight_attr='weight')

    @classmethod
    def calculate_minimum_hops_path(cls,
                                    graph: nx.Graph,
                                    source: str,
                                    target: str) -> Dict[str, Any]:
        """
        策略 2: 最少跳数路由 (BFS 算法)
        寻找经过中继卫星节点最少的路径，常用于减少节点排队和处理时延。
        """
        # weight_attr=None 意味着 NetworkX 会忽略所有边的权重，把每条边当成长度 1
        return cls._execute_routing(graph, source, target, weight_attr=None)

    @classmethod
    def _execute_routing(cls,
                         graph: nx.Graph,
                         source: str,
                         target: str,
                         weight_attr: Optional[str]) -> Dict[str, Any]:
        """
        内部核心路由执行器，统一处理寻路逻辑、指标统计与异常捕获。
        """
        result = {
            'success': False,
            'source': source,
            'target': target,
            'path': [],
            'hops': 0,
            'total_distance_km': 0.0,
            'propagation_delay_ms': 0.0,
            'error_msg': ""
        }

        # 1. 前置校验：节点是否存在于当前拓扑图中
        if source not in graph or target not in graph:
            result['error_msg'] = f"路由失败: 源节点 '{source}' 或 目的节点 '{target}' 不在当前拓扑快照中。"
            return result

        try:
            # 2. 执行网络寻路算法 (底层依据 weight_attr 是否为 None 自动选择算法)
            path = nx.shortest_path(graph, source=source, target=target, weight=weight_attr)

            # 3. 统计路由关键指标 (QoS)
            total_distance = 0.0

            # 遍历路径中的每一跳，累加物理距离
            for i in range(len(path) - 1):
                u = path[i]
                v = path[i + 1]
                # 获取图中该边的属性字典
                edge_data = graph.get_edge_data(u, v)
                total_distance += edge_data.get('distance_km', 0.0)

            # 计算传播时延 (毫秒)
            delay_ms = (total_distance / cls.SPEED_OF_LIGHT_KM_S) * 1000.0

            # 组装成功结果
            result['success'] = True
            result['path'] = path
            result['hops'] = len(path) - 1  # 3个节点构成的路径是 2 跳
            result['total_distance_km'] = total_distance
            result['propagation_delay_ms'] = delay_ms

        except nx.NetworkXNoPath:
            result['error_msg'] = f"路由失败: '{source}' 到 '{target}' 之间无物理连通路径 (网络割裂)。"
        except Exception as e:
            result['error_msg'] = f"路由计算发生未知错误: {str(e)}"

        return result


# ==========================================
# 本地测试与调试代码
# ==========================================
if __name__ == "__main__":
    print("--- 启动路由仿真引擎测试 ---")

    # 手动构建一个简单的测试拓扑图来验证算法
    # 模拟场景:
    # 从 A 到 D 有两条路：
    # 路线 1: A -> B -> D (2跳，但 B到D 距离极远，总距离 100 + 5000 = 5100km)
    # 路线 2: A -> C -> E -> D (3跳，但每段都很近，总距离 100 + 100 + 100 = 300km)

    G = nx.Graph()
    # 添加节点
    G.add_nodes_from(['SAT-A', 'SAT-B', 'SAT-C', 'SAT-D', 'SAT-E', 'SAT-ISOLATED'])

    # 添加边与距离权重
    edges = [
        ('SAT-A', 'SAT-B', {'weight': 100.0, 'distance_km': 100.0}),
        ('SAT-B', 'SAT-D', {'weight': 5000.0, 'distance_km': 5000.0}),
        ('SAT-A', 'SAT-C', {'weight': 100.0, 'distance_km': 100.0}),
        ('SAT-C', 'SAT-E', {'weight': 100.0, 'distance_km': 100.0}),
        ('SAT-E', 'SAT-D', {'weight': 100.0, 'distance_km': 100.0}),
    ]
    G.add_edges_from(edges)

    print("\n[测试场景] 寻找 SAT-A 到 SAT-D 的最优路由")

    # 测试 1: 最短距离优先
    res_dist = RoutingEngine.calculate_shortest_distance_path(G, 'SAT-A', 'SAT-D')
    print("\n>> 策略 1: 最短物理距离路由结果:")
    print(f"  成功态: {res_dist['success']}")
    print(f"  选择路径: {' -> '.join(res_dist['path'])}")
    print(f"  总跳数: {res_dist['hops']} Hops")
    print(f"  总距离: {res_dist['total_distance_km']:.2f} km")
    print(f"  传播时延: {res_dist['propagation_delay_ms']:.4f} ms")

    # 测试 2: 最少跳数优先
    res_hops = RoutingEngine.calculate_minimum_hops_path(G, 'SAT-A', 'SAT-D')
    print("\n>> 策略 2: 最少跳数优先路由结果:")
    print(f"  选择路径: {' -> '.join(res_hops['path'])}")
    print(f"  总跳数: {res_hops['hops']} Hops")
    print(f"  总距离: {res_hops['total_distance_km']:.2f} km")

    # 测试 3: 网络不可达测试
    res_fail = RoutingEngine.calculate_shortest_distance_path(G, 'SAT-A', 'SAT-ISOLATED')
    print("\n>> 测试 3: 孤岛节点不可达测试:")
    print(f"  成功态: {res_fail['success']}")
    print(f"  错误信息: {res_fail['error_msg']}")