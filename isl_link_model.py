import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import networkx as nx


@dataclass(frozen=True)
class ISLLinkModelConfig:
    """星间链路确定性代理模型参数。

    这些参数用于网络层算法实验，不代表具体激光通信设备的实测指标。
    后续接入真实激光信道模型时，可以保持输出属性不变并替换内部计算。
    """

    model_name: str = "isl_proxy_v1"
    reference_distance_km: float = 1000.0
    reference_margin_db: float = 18.0
    fixed_loss_db: float = 2.0

    minimum_margin_db: float = 0.0
    standard_margin_db: float = 3.0
    high_margin_db: float = 6.0

    robust_capacity_gbps: float = 1.0
    standard_capacity_gbps: float = 5.0
    high_capacity_gbps: float = 10.0

    robust_packet_loss_rate: float = 1e-3
    standard_packet_loss_rate: float = 1e-5
    high_packet_loss_rate: float = 1e-6

    packet_size_bytes: int = 1500
    processing_delay_ms: float = 0.2

    def __post_init__(self) -> None:
        if self.reference_distance_km <= 0:
            raise ValueError("reference_distance_km 必须大于 0")
        if not (self.minimum_margin_db < self.standard_margin_db < self.high_margin_db):
            raise ValueError("代理裕量阈值必须满足 minimum < standard < high")
        if not (0 < self.robust_capacity_gbps <= self.standard_capacity_gbps <= self.high_capacity_gbps):
            raise ValueError("容量档位必须为正数且按 robust、standard、high 递增")
        for value in (
            self.robust_packet_loss_rate,
            self.standard_packet_loss_rate,
            self.high_packet_loss_rate,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("期望丢包率必须位于 [0, 1]")
        if self.packet_size_bytes <= 0:
            raise ValueError("packet_size_bytes 必须大于 0")
        if self.processing_delay_ms < 0:
            raise ValueError("processing_delay_ms 不能小于 0")


class ISLLinkModel:
    """仅面向 ISL 的几何感知确定性代理链路模型。"""

    SPEED_OF_LIGHT_KM_S = 299792.458

    def __init__(self, config: Optional[ISLLinkModelConfig] = None):
        self.config = config or ISLLinkModelConfig()

    def evaluate(self, distance_km: float) -> Dict[str, object]:
        """根据链路距离生成网络层可用的近似链路指标。"""
        if distance_km <= 0:
            raise ValueError("ISL 距离必须大于 0")

        cfg = self.config
        relative_distance_loss_db = 20.0 * math.log10(
            distance_km / cfg.reference_distance_km
        )
        proxy_margin_db = (
            cfg.reference_margin_db
            - relative_distance_loss_db
            - cfg.fixed_loss_db
        )

        if proxy_margin_db >= cfg.high_margin_db:
            state = "UP"
            service_mode = "HIGH"
            capacity_gbps = cfg.high_capacity_gbps
            packet_loss_rate = cfg.high_packet_loss_rate
        elif proxy_margin_db >= cfg.standard_margin_db:
            state = "UP"
            service_mode = "STANDARD"
            capacity_gbps = cfg.standard_capacity_gbps
            packet_loss_rate = cfg.standard_packet_loss_rate
        elif proxy_margin_db >= cfg.minimum_margin_db:
            state = "DEGRADED"
            service_mode = "ROBUST"
            capacity_gbps = cfg.robust_capacity_gbps
            packet_loss_rate = cfg.robust_packet_loss_rate
        else:
            state = "DOWN"
            service_mode = "NONE"
            capacity_gbps = 0.0
            packet_loss_rate = 1.0

        propagation_delay_ms = (
            distance_km / self.SPEED_OF_LIGHT_KM_S
        ) * 1000.0

        if capacity_gbps > 0:
            capacity_bps = capacity_gbps * 1e9
            serialization_delay_ms = (
                cfg.packet_size_bytes * 8.0 / capacity_bps
            ) * 1000.0
            total_delay_ms = (
                propagation_delay_ms
                + serialization_delay_ms
                + cfg.processing_delay_ms
            )
        else:
            capacity_bps = 0.0
            serialization_delay_ms = None
            total_delay_ms = None

        return {
            "link_model": cfg.model_name,
            "link_state": state,
            "service_mode": service_mode,
            "routable": state != "DOWN",
            "proxy_margin_db": proxy_margin_db,
            "capacity_bps": capacity_bps,
            "capacity_gbps": capacity_gbps,
            "expected_packet_loss_rate": packet_loss_rate,
            "propagation_delay_ms": propagation_delay_ms,
            "serialization_delay_ms": serialization_delay_ms,
            "processing_delay_ms": cfg.processing_delay_ms,
            "total_delay_ms": total_delay_ms,
        }

    def apply_to_graph(self, graph: nx.Graph) -> None:
        """仅给图中的 ISL 边补充代理指标；SGL 和其他边保持不变。"""
        for _, _, data in graph.edges(data=True):
            if data.get("type") != "ISL":
                continue
            metrics = self.evaluate(float(data["distance_km"]))
            data.update(metrics)

    def summarize_graph(self, graph: nx.Graph) -> Dict[str, object]:
        """汇总当前快照中的 ISL 模型状态，供日志输出和测试使用。"""
        counts = {"UP": 0, "DEGRADED": 0, "DOWN": 0}
        capacities: List[float] = []
        margins: List[float] = []

        for _, _, data in graph.edges(data=True):
            if data.get("type") != "ISL" or data.get("link_model") != self.config.model_name:
                continue
            state = str(data["link_state"])
            counts[state] = counts.get(state, 0) + 1
            margins.append(float(data["proxy_margin_db"]))
            if data.get("routable"):
                capacities.append(float(data["capacity_gbps"]))

        return {
            "total": sum(counts.values()),
            "up": counts["UP"],
            "degraded": counts["DEGRADED"],
            "down": counts["DOWN"],
            "min_capacity_gbps": min(capacities) if capacities else None,
            "max_capacity_gbps": max(capacities) if capacities else None,
            "min_proxy_margin_db": min(margins) if margins else None,
            "max_proxy_margin_db": max(margins) if margins else None,
        }

    def configuration_summary(self) -> str:
        """返回适合在仿真启动阶段打印的一行配置说明。"""
        cfg = self.config
        return (
            f"{cfg.model_name} | 仅 ISL | 参考距离 {cfg.reference_distance_km:.0f} km "
            f"| 参考裕量 {cfg.reference_margin_db:.1f} dB | 固定损耗 {cfg.fixed_loss_db:.1f} dB "
            f"| 容量档位 {cfg.robust_capacity_gbps:g}/{cfg.standard_capacity_gbps:g}/"
            f"{cfg.high_capacity_gbps:g} Gbps | 报文 {cfg.packet_size_bytes} B"
        )
