# Orbit 模块交接说明

> 更新时间：2026-07-23  
> 一站式公开入口：`orbitserve.orbit.generate_orbit_trace`

## 1. 模块职责

Orbit 接收结构化 SGP4 平均根数、采样时刻、地面入口和候选 ISL 对，生成：

- TEME 与 ITRS 位置、速度；
- SGL、ISL 和日照窗口；
- 可校验、字节级可复现的 Orbit Trace。

Orbit 只输出物理几何和环境事实。带宽、终端、路由、队列、能耗、SOC 和 active
graph 均不属于 Orbit。

## 2. 代码结构

```text
orbit/
  __init__.py         # 唯一跨模块公开入口
  trace.py            # Orbit Trace 规范化写入、读取、哈希校验
  sgp4/
    elements.py       # SGP4 平均根数验证与 element_set_id
    propagation.py    # python-sgp4 / WGS-72 / TEME
    frames.py         # Astropy TEME -> ITRS 与 Sun -> ITRS
    geometry.py       # WGS-84 SGL/ISL/日照几何
    trace.py          # 一站式生成流程与 Trace 适配
  data/iers/...       # 固定 IERS 与闰秒数据
```

旧圆轨道配置、旧 simulator、surrogate trace、旧 trace builder 和
`RuntimeTrace*` 兼容别名均已删除。其他模块只能从 `orbitserve.orbit` 导入，
不得直接依赖 `sgp4/` 内部脚本。

## 3. 运行依赖

根 `pyproject.toml` 固定：

- `sgp4==2.27`
- `astropy==6.1.3`
- `astropy-iers-data==0.2026.5.11.1.8.52`

Orbit 使用仓库内固定的 IERS-A 与闰秒数据，运行时不联网更新。数据缺失、哈希
不符、覆盖范围不足或闰秒表过期时失败关闭。

## 4. 输入要求

### SGP4 平均根数

上游必须提供 `orbitserve.sgp4_element_bundle.v1`，并通过公开
`load_sgp4_element_bundle` 接入。结构化、全精度 SGP4 mean elements 是传播
权威输入；两行 TLE 仅可作为审计工件，不作为生产传播输入。完整字段、单位与
校验规则见 [`SGP4_INPUT_CONTRACT.md`](SGP4_INPUT_CONTRACT.md)。

### Workload gateway

Workload 提供稳定的 `gateway_id`、`lat_deg` 和 `lon_deg`。Runtime 或集成层通过
Workload 公开入口读取并转换为：

```python
{
    "ingress_id": gateway.gateway_id,
    "lat_deg": gateway.lat_deg,
    "lon_deg": gateway.lon_deg,
    "altitude_km": 0.0,
    "min_elevation_deg": runtime_min_elevation_deg,
}
```

`ingress_id` 必须与请求中的入口 ID 一致；`min_elevation_deg` 是运行场景策略。
gateway 带宽、成本和运行时可用性不得传给 Orbit。

### ISL 候选

`isl_pairs` 是卫星 ID 二元组序列。Orbit 只计算几何可见性、距离和传播时延，
不决定网络拓扑、终端分配、带宽或 active graph。

## 5. 标准调用

```python
from orbitserve.orbit import generate_orbit_trace

manifest = generate_orbit_trace(
    "results/orbit/case-a",
    elements="scenario_sgp4_elements.json",
    simulation_epoch_utc="2026-07-20T00:00:00.000000Z",
    sample_times_s=tuple(range(0, 3601, 60)),
    ground_ingresses=ground_ingresses,
    isl_pairs=(("sat-00001", "sat-00002"),),
)
```

需要分步控制时，只使用公开入口：

- `load_sgp4_element_bundle`
- `propagate_sgp4_teme`
- `transform_sgp4_teme_to_itrs`
- `compute_sgp4_sun_positions_itrs`
- `evaluate_sgp4_geometry`
- `write_sgp4_orbit_trace`
- `write_orbit_trace`
- `load_orbit_trace`

## 6. 输出合同

输出目录固定包含：

- `trace_manifest.json`
- `satellite_catalog.json`
- `ephemeris_trace.json`
- `sgl_windows.json`
- `isl_windows.json`
- `sunlight_windows.json`

schema 固定为 `orbitserve.orbit_trace`，不带 `v1`/`v2` 格式标记。相同规范化
输入必须产生完全相同的文件集合、原始字节、SHA-256 和 `trace_id`。

`load_orbit_trace` 返回 `OrbitTraceBundle`，公开字段为：

- `trace_manifest`、`trace_id`、`trace_model`、`scope`、`time`
- `warnings`、`provenance`
- `satellite_catalog`、`ephemeris_samples`
- `sgl_windows`、`isl_windows`、`sunlight_windows`

## 7. 输出依赖模块迁移要求

Runtime、DSE、Experiments 或其他使用方需要：

1. 只导入 `OrbitTraceManifest`、`OrbitTraceBundle`、`generate_orbit_trace` 或
   `load_orbit_trace` 等 `orbitserve.orbit` 公开符号；
2. 不再导入 `ConstellationDesign`、`SimulationConfig`、`run_simulation`、
   `RuntimeTrace*`、surrogate/circular 常量或已删除的内部脚本；
3. 从 `bundle.sgl_windows`、`bundle.isl_windows` 和
   `bundle.sunlight_windows` 读取几何窗口；
4. 由 Runtime 根据 Orbit 几何、Architecture 和运行配置生成
   `satellite_initial_soc`、`terminal_catalog`、`active_graph_snapshots`；
5. 由 Runtime/Architecture 派生容量、带宽、终端占用、路由、队列、SOC 和
   能耗状态，不得要求 Orbit Trace 恢复这些字段。

DSE/Experiments 的 SGP4 参数生成与搜索路径留待后续阶段处理；Orbit 不为其保留
旧圆轨道兼容接口。

## 8. 验证

Orbit 负责人执行：

```bash
python -m unittest discover -s tests/unit/orbit -t .
python -m unittest tests.unit.test_module_boundaries
python -m unittest discover -s tests/integration/fixed_design -t .
python -m unittest discover -s tests/smoke -t .
```

Orbit 单元测试必须先通过。边界、integration 或 smoke 中仍导入旧 Orbit 接口的
失败应由对应测试/消费模块负责人迁移，Orbit 负责人不越界修改。完整 Runtime 或
DSE 新路径完成后再补跑 slow tests。

2026-07-23 验证状态：

- Orbit unit：通过，`39/39`；
- module boundary：Runtime 仍导入 `CIRCULAR_GEOMETRY_TRACE`，待 Runtime 负责人迁移；
- fixed-design integration：Experiments 仍导入 `ConstellationDesign`，Runtime
  仍导入 circular 常量，待对应负责人迁移；
- smoke：Experiments 与 DSE 仍导入 `ConstellationDesign`，待后续阶段迁移；
- slow：本阶段不运行，等完整 Runtime/DSE SGP4 路径接通后补跑。

当前扫描未发现 Workload、Architecture 或 Serving 对已删除 Orbit 接口的直接
依赖。
