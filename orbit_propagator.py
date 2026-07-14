import pandas as pd
import numpy as np
from skyfield.api import load, EarthSatellite, wgs84
from datetime import datetime, timedelta, timezone
from typing import Optional


class OrbitPropagator:
    """
    基于 Skyfield (SGP4/SDP4) 的轨道推算核心模块。
    专为 NTN-TN 异构网络仿真设计，输出高精度的 WGS84 时空序列数据。
    """

    def __init__(self, name: str, line1: str, line2: str):
        """
        初始化卫星传播器。

        参数:
            name: 卫星名称 (如 'STARLINK-1234')
            line1: TLE 数据第一行
            line2: TLE 数据第二行
        """
        self.name = name
        # 加载时间刻度表 (首次运行会自动下载 de421.bsp 或 leapseconds 文件到当前目录)
        # 在高频仿真的服务器环境中，建议固定下载目录以复用这些天文数据文件
        self.ts = load.timescale()

        # 实例化 SGP4 模型
        self.satellite = EarthSatellite(line1, line2, self.name, self.ts)

    def propagate(
            self,
            start_time_utc: datetime,
            duration_minutes: float,
            step_seconds: float = 1.0
    ) -> pd.DataFrame:
        """
        推算时间窗口内的卫星空间坐标。

        参数:
            start_time_utc: 仿真的起始时间 (必须是 UTC 且 timezone-aware)
            duration_minutes: 仿真持续时间（分钟）
            step_seconds: 采样步长（秒），默认 1 秒

        返回:
            包含时间、经度、纬度、高度的 pandas.DataFrame，便于后续的数学变换与矩阵运算
        """
        # 1. 构建时间序列数组 (矢量化生成，避免 for 循环带来的性能损耗)
        total_steps = int((duration_minutes * 60) / step_seconds) + 1
        time_list = [
            start_time_utc + timedelta(seconds=i * step_seconds)
            for i in range(total_steps)
        ]

        # 将 datetime 转换为 skyfield 的 Time 对象数组
        t_array = self.ts.from_datetimes(time_list)

        # 2. 核心 SGP4 轨道外推计算
        # 这会一次性计算出所有时间点的地心惯性坐标 (TEME)
        geocentric = self.satellite.at(t_array)

        # 3. 坐标系转换 (TEME -> WGS84 经纬高)
        # 对于 LEO 卫星的下行覆盖计算，WGS84 是绝对的基准标准
        subpoint = geocentric.subpoint()

        # 提取具体数值
        latitudes = subpoint.latitude.degrees
        longitudes = subpoint.longitude.degrees
        altitudes_km = subpoint.elevation.km

        # 4. 封装为 DataFrame
        df = pd.DataFrame({
            'timestamp': time_list,
            'latitude': latitudes,
            'longitude': longitudes,
            'altitude_km': altitudes_km
        })

        # 将时间戳设为索引，方便后续按时间切片或进行时序对齐
        df.set_index('timestamp', inplace=True)

        return df
