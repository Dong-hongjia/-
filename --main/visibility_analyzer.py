import numpy as np
import pandas as pd


class VisibilityAnalyzer:
    """
    星间链路 (ISL) 实时可见性分析引擎。
    利用 Numpy 矢量化运算，基于地球遮挡几何模型，快速批量推算两星连通状态。
    """

    # 设定地球平均半径 (千米)
    EARTH_RADIUS_KM = 6371.0

    @classmethod
    def _to_cartesian(cls, lat_deg: np.ndarray, lon_deg: np.ndarray, alt_km: np.ndarray) -> np.ndarray:
        """
        内部辅助方法：将 WGS84 经纬高转换为近似的地心空间直角坐标系 (X, Y, Z)。
        为保证星间视线计算的极速性能，此处将地球近似为标准球体。

        返回: Shape 为 (N, 3) 的 Numpy 数组
        """
        lat_rad = np.radians(lat_deg)
        lon_rad = np.radians(lon_deg)

        # 卫星到地心的距离
        r = cls.EARTH_RADIUS_KM + alt_km

        # 球面坐标转直角坐标
        x = r * np.cos(lat_rad) * np.cos(lon_rad)
        y = r * np.cos(lat_rad) * np.sin(lon_rad)
        z = r * np.sin(lat_rad)

        # 按列拼接成 (N, 3) 的矩阵
        return np.column_stack((x, y, z))

    @classmethod
    def check_line_of_sight(cls, df1: pd.DataFrame, df2: pd.DataFrame) -> pd.Series:
        """
        批量计算两条卫星轨迹之间的实时可见性。

        参数:
            df1: 卫星 1 的时序坐标 DataFrame (必须包含 latitude, longitude, altitude_km)
            df2: 卫星 2 的时序坐标 DataFrame (必须与 df1 长度和时间戳对齐)

        返回:
            pd.Series: 布尔值序列 (True 表示可视连通，False 表示被地球遮挡断开)
        """
        # 1. 确保两个 DataFrame 长度一致
        if len(df1) != len(df2):
            raise ValueError("两颗卫星的轨迹数据长度不一致，请确保仿真时间窗口和步长相同。")

        # 2. 提取并转换为直角坐标系矩阵 (N, 3)
        pos1 = cls._to_cartesian(df1['latitude'].values, df1['longitude'].values, df1['altitude_km'].values)
        pos2 = cls._to_cartesian(df2['latitude'].values, df2['longitude'].values, df2['altitude_km'].values)

        # 3. 核心矢量化几何解算
        # 相对位置向量 r12 = pos2 - pos1
        r12 = pos2 - pos1

        # 计算两星间距的模长 D (沿 axis=1 求范数)
        D = np.linalg.norm(r12, axis=1)

        # 防止重合导致除以 0 的情况（虽然物理上不可能，但增强代码健壮性）
        D_safe = np.where(D == 0, 1e-9, D)

        # 计算视线方向的单位向量 u
        u = r12 / D_safe[:, np.newaxis]

        # 投影计算：地心到卫星 1 的向量 (-pos1) 在视线方向 (u) 上的投影 p
        # 使用批量点积 np.einsum 或 np.sum
        p = np.sum(-pos1 * u, axis=1)

        # 计算垂距的平方: d^2 = |r1|^2 - p^2
        r1_norm_sq = np.sum(pos1 ** 2, axis=1)

        # 避免浮点数精度导致的微小负数，使用 np.maximum 兜底
        d_sq = np.maximum(0, r1_norm_sq - p ** 2)

        # 4. 可见性逻辑判定
        # 条件 A: 最短距离点（垂足）在卫星 1 背后 (p < 0)
        # 条件 B: 最短距离点（垂足）在卫星 2 背后 (p > D)
        # 条件 C: 垂足在两星之间，但垂线距离大于地球半径 (d^2 >= R^2)
        earth_r_sq = cls.EARTH_RADIUS_KM ** 2
        is_visible = (p < 0) | (p > D) | (d_sq >= earth_r_sq)

        # 5. 封装为与原时序对齐的 Pandas Series
        return pd.Series(is_visible, index=df1.index, name="is_visible")


# ==========================================
# 本地测试与调试代码
# ==========================================
if __name__ == "__main__":
    from datetime import datetime, timedelta, timezone

    # 为了测试，我们快速生成两组伪造的时序坐标数据
    # 模拟场景：两颗卫星分别在地球的两端（必然遮挡），以及运行到相近位置（必然可见）
    times = [datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=i) for i in range(3)]

    # 卫星 A: 始终在赤道，经度 0度，高度 500km
    df_A = pd.DataFrame({
        'latitude': [0.0, 0.0, 0.0],
        'longitude': [0.0, 0.0, 0.0],
        'altitude_km': [500.0, 500.0, 500.0]
    }, index=times)

    # 卫星 B:
    # T0: 在背面，经度 180度 (被地球完全遮挡)
    # T1: 在侧面，经度 90度 (临界状态，可能遮挡)
    # T2: 靠得很近，经度 10度 (清晰可见)
    df_B = pd.DataFrame({
        'latitude': [0.0, 0.0, 0.0],
        'longitude': [180.0, 90.0, 10.0],
        'altitude_km': [500.0, 500.0, 500.0]
    }, index=times)

    print("--- 启动 ISL 空间可见性矢量化计算 ---")
    visibility_result = VisibilityAnalyzer.check_line_of_sight(df_A, df_B)

    # 将结果拼接起来直观展示
    result_df = pd.DataFrame({
        'Sat_A_Lon': df_A['longitude'],
        'Sat_B_Lon': df_B['longitude'],
        'Is_Visible': visibility_result
    })

    print("\n计算结果对比：")
    print(result_df)