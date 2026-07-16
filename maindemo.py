import asyncio
import json
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel  # 新增：用于解析前端发送的 JSON 数据
from typing import Optional  # 【核心修复 1】：引入 Optional
import pandas as pd

# 导入我们之前编写的核心计算模块
# 请确保 tle_manager.py, topology_builder.py, routing_engine.py, simulation_controller.py 都在同级目录
from simulation_controller import SimulationController
from routing_engine import RoutingEngine

# app = FastAPI(title="NTN-TN Simulation API")

# === 新增：全局仿真状态字典，用于存储前端下发的控制参数 ===
sim_state = {
    "strategy": "shortest_distance",
    "src_node": None,  # 新增：动态源节点
    "dst_node": None,  # 新增：动态目的节点
    "is_playing": True,  # 【新增】：播放状态
    "step_idx": 0,  # 【新增】：当前仿真时间步索引
    "speed": 1.0  # 【新增】：仿真播放倍速
}

# ==========================================
# 1. 极简前端测试页面 (HTML + JS)
# 用于验证 WebSocket 连接并打印 JSON 帧数据
# ==========================================
html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>NTN-TN 异构网络 3D 仿真平台</title>
    <!-- 使用官方最新的 1.143 版本 -->
    <script src="https://cesium.com/downloads/cesiumjs/releases/1.143/Build/Cesium/Cesium.js"></script>
    <link href="https://cesium.com/downloads/cesiumjs/releases/1.143/Build/Cesium/Widgets/widgets.css" rel="stylesheet">
    <style>
        html, body, #cesiumContainer { width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden; background-color: #000; }
        #hud {
            position: absolute; top: 20px; left: 20px; width: 320px;
            background: rgba(15, 23, 42, 0.85); color: #e2e8f0;
            padding: 15px; border-radius: 8px; font-family: 'Segoe UI', sans-serif;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #334155;
            z-index: 100; 
        }
        .hud-title { font-size: 16px; font-weight: bold; margin-bottom: 10px; color: #38bdf8; border-bottom: 1px solid #334155; padding-bottom: 5px;}
        .hud-row { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 14px; }
        .val-highlight { color: #10b981; font-weight: bold; }
        .val-warning { color: #f43f5e; font-weight: bold; }
    </style>
</head>
<body>
    <div id="cesiumContainer"></div>
    <div id="hud">
        <div class="hud-title">🛰️ 空间路由状态监测</div>
        <div class="hud-row"><span>系统时间:</span> <span id="sys_time">等待同步...</span></div>
        <div class="hud-row"><span>活跃网元数:</span> <span id="node_count">0</span></div>
        <div class="hud-row"><span>拓扑链路数:</span> <span id="edge_count">0</span></div>
        <div class="hud-title" style="margin-top: 15px; border-top: 1px solid #334155; padding-top: 10px;">⚡ 端到端 QoS 分析</div>
        <div class="hud-row"><span>路由连通性:</span> <span id="route_status">检测中...</span></div>
        <div class="hud-row"><span>单向传播时延:</span> <span id="route_delay">0 ms</span></div>
        <div class="hud-row"><span>路由跳数:</span> <span id="route_hops">0</span></div>

        <!-- === 新增：仿真控制面板 === -->
        <div class="hud-title" style="margin-top: 15px; border-top: 1px solid #334155; padding-top: 10px;">⚙️ 仿真控制</div>

        <!-- 【新增】：收发端点选择下拉框 -->
        <div class="hud-row" style="align-items: center; margin-bottom: 8px;">
            <span>通信源 (Src):</span>
            <select id="src_select" style="background: #1e293b; color: #fff; border: 1px solid #475569; padding: 4px; border-radius: 4px; width: 160px; cursor: pointer; outline: none;"></select>
        </div>
        <div class="hud-row" style="align-items: center; margin-bottom: 12px;">
            <span>目的端 (Dst):</span>
            <select id="dst_select" style="background: #1e293b; color: #fff; border: 1px solid #475569; padding: 4px; border-radius: 4px; width: 160px; cursor: pointer; outline: none;"></select>
        </div>
        <div class="hud-row" style="align-items: center;">
            <span>路由策略:</span>
            <select id="strategy_select" style="background: #1e293b; color: #fff; border: 1px solid #475569; padding: 4px; border-radius: 4px; cursor: pointer; outline: none;">
                <option value="shortest_distance">最短物理距离优先</option>
                <option value="min_hops">最少跳数优先</option>
            </select>
        </div>
        <!-- 【新增】：播放控制面板 -->
        <div class="hud-title" style="margin-top: 15px; border-top: 1px solid #334155; padding-top: 10px;">⏯️ 播放控制</div>
        <div style="display: flex; gap: 8px; justify-content: space-between;">
            <button id="btn_playpause" style="flex: 1; background: #3b82f6; color: white; border: none; padding: 6px; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s;">⏸ 暂停</button>
            <button id="btn_speed" style="flex: 1; background: #10b981; color: white; border: none; padding: 6px; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s;">⏩ 1x</button>
            <button id="btn_reset" style="flex: 1; background: #ef4444; color: white; border: none; padding: 6px; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s;">🔄 重置</button>
        </div>
    </div>

    <script type="module">
        // 1. 填入你的 Token
        Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJjM2I0YTk3OC1mZTVlLTQzNTgtYmUwMC02MmVjNjY0ZDJlN2YiLCJpZCI6NDU0MzUzLCJpc3MiOiJodHRwczovL2FwaS5jZXNpdW0uY29tIiwiYXVkIjoidW5kZWZpbmVkX2RlZmF1bHQiLCJpYXQiOjE3ODM1ODUwOTF9.yiVXDATP4JtxfOi0UwImNnk13qjfwrk-0iJjDwmxsd4';

        // 2. 采用官方最新语法初始化 Viewer
        const viewer = new Cesium.Viewer('cesiumContainer', {
            terrain: Cesium.Terrain.fromWorldTerrain(), // 新版真实地形 API
            baseLayerPicker: false,
            timeline: false,
            animation: false,
            infoBox: false,
            navigationHelpButton: false,
            geocoder: false,
            homeButton: false,
            sceneModePicker: false
        });

        viewer.cesiumWidget.creditContainer.style.display = "none";

        // 将视角聚焦在东亚沿海区域
        viewer.camera.setView({
            destination: Cesium.Cartesian3.fromDegrees(115.0, 20.0, 18000000.0)
        });

        // 3. 建立实体集合与数据源
        const satEntities = {}; 
        const topologySource = new Cesium.CustomDataSource('topology'); 
        const activeRouteSource = new Cesium.CustomDataSource('active_route'); 
        viewer.dataSources.add(topologySource);
        viewer.dataSources.add(activeRouteSource);

        // 4. WebSocket 实时数据接入
        const ws = new WebSocket("ws://localhost:8001/ws");


        // 【新增】：监听收发节点的切换并发送到后端
        let isNodesPopulated = false; // 用于控制只填充一次下拉列表

        function updateNodes() {
            const src = document.getElementById('src_select').value;
            const dst = document.getElementById('dst_select').value;
            fetch('/api/nodes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ src_node: src, dst_node: dst })
            }).then(res => res.json()).then(data => {
                console.log("[控制流] 端点已切换:", data);
            }).catch(err => console.error("节点切换失败:", err));
        }

        document.getElementById('src_select').addEventListener('change', updateNodes);
        document.getElementById('dst_select').addEventListener('change', updateNodes);

        // 【新增】：播放控制相关的事件监听与 API 调用
        let currentSpeed = 1.0;
        const speeds = [1.0, 2.0, 5.0, 10.0];
        let isPlaying = true;

        function sendPlaybackCmd(action, val) {
            fetch('/api/playback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action, value: val })
            }).catch(err => console.error("控制命令发送失败:", err));
        }

        document.getElementById('btn_playpause').addEventListener('click', function(e) {
            isPlaying = !isPlaying;
            e.target.innerText = isPlaying ? "⏸ 暂停" : "▶️ 播放";
            e.target.style.background = isPlaying ? "#3b82f6" : "#f59e0b"; // 切换蓝黄颜色
            sendPlaybackCmd(isPlaying ? 'play' : 'pause', null);
        });

        document.getElementById('btn_speed').addEventListener('click', function(e) {
            let idx = speeds.indexOf(currentSpeed);
            currentSpeed = speeds[(idx + 1) % speeds.length];
            e.target.innerText = `⏩ ${currentSpeed}x`;
            sendPlaybackCmd('speed', currentSpeed);
        });

        document.getElementById('btn_reset').addEventListener('click', function() {
            isPlaying = true;
            currentSpeed = 1.0;
            document.getElementById('btn_playpause').innerText = "⏸ 暂停";
            document.getElementById('btn_playpause').style.background = "#3b82f6";
            document.getElementById('btn_speed').innerText = "⏩ 1x";
            sendPlaybackCmd('reset', null);
        });


        // === 新增：监听下拉框修改，通过 REST API 向后端发送控制指令 ===
        document.getElementById('strategy_select').addEventListener('change', function(e) {
            const newStrategy = e.target.value;
            fetch('/api/strategy', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ strategy: newStrategy })
            }).then(res => res.json()).then(data => {
                console.log("[控制流] 后端路由策略已切换为:", data.strategy);
            }).catch(err => console.error("策略切换失败:", err));
        });

        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);

            // 【新增】：在收到第一帧数据时，动态解析所有卫星名称，填充进下拉框
            if (!isNodesPopulated && Object.keys(data.nodes).length > 0) {
                const nodeIds = Object.keys(data.nodes).sort(); // 按字母排序
                const srcSelect = document.getElementById('src_select');
                const dstSelect = document.getElementById('dst_select');

                nodeIds.forEach(id => {
                    srcSelect.add(new Option(id, id));
                    dstSelect.add(new Option(id, id));
                });

                // 默认选中第一颗和最后一颗（确保和后端初始默认值一致）
                srcSelect.value = nodeIds[0];
                dstSelect.value = nodeIds[nodeIds.length - 1];

                isNodesPopulated = true;
            }


            // 更新 HUD
            document.getElementById('sys_time').innerText = data.timestamp.replace('T', ' ').substring(0, 19);
            document.getElementById('node_count').innerText = Object.keys(data.nodes).length;
            document.getElementById('edge_count').innerText = data.topology_edges.length;

            const routeStatus = document.getElementById('route_status');
            if(data.active_route.success) {
                routeStatus.innerHTML = '<span class="val-highlight">链路通畅</span>';
                document.getElementById('route_delay').innerText = data.active_route.delay_ms.toFixed(2) + ' ms';
                document.getElementById('route_hops').innerText = data.active_route.hops;
            } else {
                routeStatus.innerHTML = '<span class="val-warning">网络割裂 (不可达)</span>';
                document.getElementById('route_delay').innerText = '--';
                document.getElementById('route_hops').innerText = '--';
            }

            // 渲染网元节点 (修复：增加黑色描边，放宽文字显示距离)
            for (const [nodeId, coords] of Object.entries(data.nodes)) {
                const position = Cesium.Cartesian3.fromDegrees(coords.lon, coords.lat, coords.alt * 1000);

                if (!satEntities[nodeId]) {
                    satEntities[nodeId] = viewer.entities.add({
                        id: nodeId,
                        position: position,
                        point: { pixelSize: 6, color: Cesium.Color.CYAN, outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
                        label: {
                            text: nodeId, 
                            font: 'bold 12px sans-serif', // 加粗字体
                            fillColor: Cesium.Color.WHITE,
                            style: Cesium.LabelStyle.FILL_AND_OUTLINE, // 增加描边样式
                            outlineColor: Cesium.Color.BLACK,          // 黑色描边，防重叠
                            outlineWidth: 2,
                            pixelOffset: new Cesium.Cartesian2(0, -15),
                            // 【核心修改】将显示距离放宽到 30,000 公里，初始宏观视角下即可见名字
                            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 60000000)
                        }
                    });
                } else {
                    satEntities[nodeId].position = position;
                }
            }

            // 渲染基础拓扑蓝线 (修复闪烁并加粗)
            const currentEdgeIds = new Set();

            data.topology_edges.forEach(edge => {
                // 生成唯一且无向的边 ID，例如 "SAT-A_SAT-B"
                const edgeId = edge[0] < edge[1] ? edge[0] + '_' + edge[1] : edge[1] + '_' + edge[0];
                currentEdgeIds.add(edgeId);

                const srcCoords = data.nodes[edge[0]];
                const dstCoords = data.nodes[edge[1]];

                if (srcCoords && dstCoords) {
                    const positions = Cesium.Cartesian3.fromDegreesArrayHeights([
                        srcCoords.lon, srcCoords.lat, srcCoords.alt * 1000,
                        dstCoords.lon, dstCoords.lat, dstCoords.alt * 1000
                    ]);

                    let edgeEntity = topologySource.entities.getById(edgeId);
                    if (!edgeEntity) {
                        // 如果线不存在，则新建
                        topologySource.entities.add({
                            id: edgeId,
                            polyline: {
                                positions: positions,
                                width: 2.0, // 【加粗】之前是 1，现在加粗到 2.5
                                material: Cesium.Color.fromCssColorString('rgba(56, 189, 248, 0.4)'), // 提高不透明度，让线更实
                                arcType: Cesium.ArcType.NONE 
                            }
                        });
                    } else {
                        // 如果线已经存在，只更新坐标，不销毁！彻底告别闪烁！
                        edgeEntity.polyline.positions = positions;
                    }
                }
            });

            // 移除当前帧已经断开（不再连通）的拓扑边
            const edgesToRemove = [];
            topologySource.entities.values.forEach(entity => {
                if (!currentEdgeIds.has(entity.id)) {
                    edgesToRemove.push(entity);
                }
            });
            edgesToRemove.forEach(entity => topologySource.entities.remove(entity));

            // 渲染橙色发光路由线
            activeRouteSource.entities.removeAll();
            if (data.active_route.success && data.active_route.path.length > 1) {
                const pathCoords = [];
                data.active_route.path.forEach(nodeId => {
                    const coords = data.nodes[nodeId];
                    if (coords) {
                        pathCoords.push(coords.lon, coords.lat, coords.alt * 1000);
                    }
                });

                activeRouteSource.entities.add({
                    polyline: {
                        positions: Cesium.Cartesian3.fromDegreesArrayHeights(pathCoords),
                        width: 4.5,
                        material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.2, color: Cesium.Color.ORANGE }),
                        arcType: Cesium.ArcType.NONE
                    }
                });
            }
        };
    </script>
</body>
</html>
"""


@app.get("/")
async def get_test_page():
    """返回用于测试的 HTML 页面"""
    return HTMLResponse(html)


# === 新增：接收前端控制指令的 REST API 接口 ===
class StrategyRequest(BaseModel):
    strategy: str


# 【新增】：接收端点切换的 Pydantic 模型
class NodesRequest(BaseModel):
    src_node: str
    dst_node: str


# 【核心修复 2】：使用 Optional 显式声明 value 允许接收前端的 null 空值
class PlaybackRequest(BaseModel):
    action: str
    value: Optional[float] = None


@app.post("/api/strategy")
async def update_strategy(req: StrategyRequest):
    if req.strategy in ["shortest_distance", "min_hops"]:
        sim_state["strategy"] = req.strategy
        return {"status": "success", "strategy": req.strategy}
    return {"status": "error", "msg": "未知的路由策略"}


# 【新增】：处理前端发来的源/目的节点切换请求
@app.post("/api/nodes")
async def update_nodes(req: NodesRequest):
    sim_state["src_node"] = req.src_node
    sim_state["dst_node"] = req.dst_node
    return {"status": "success", "src_node": req.src_node, "dst_node": req.dst_node}


# 【新增】：处理前端发来的播放控制请求
@app.post("/api/playback")
async def control_playback(req: PlaybackRequest):
    if req.action == 'play':
        sim_state["is_playing"] = True
    elif req.action == 'pause':
        sim_state["is_playing"] = False
    elif req.action == 'speed' and req.value is not None:
        sim_state["speed"] = req.value
    elif req.action == 'reset':
        sim_state["step_idx"] = 0
        sim_state["is_playing"] = True
        sim_state["speed"] = 1.0
    return {"status": "success", "action": req.action, "state": sim_state}


# ==========================================
# 2. WebSocket 实时推流接口
# ==========================================
# @app.websocket("/ws")
async def simulation_endpoint(websocket: WebSocket):
    await websocket.accept()

    # ==== 【核心终极修复 1：防止 F5 刷新导致的进度污染】 ====
    # 只要有新的网页连接进来，强制将仿真引擎归零！
    sim_state["step_idx"] = 0
    sim_state["is_playing"] = True
    sim_state["speed"] = 1.0
    # ======================================================

    REAL_TLE_FILE = r"C:\Users\dongh\Desktop\shixi\TLE.txt"
    sim_start = datetime.now(timezone.utc)

    try:
        controller = SimulationController(
            tle_file_path=REAL_TLE_FILE,
            start_time_utc=sim_start,
            duration_minutes=20,
            step_seconds=1.0,
            max_isl_range_km=5000.0,
            max_isl_terminals_per_satellite=4,
            max_sgl_terminals_per_satellite=1,
            max_sgl_terminals_per_ground_station=2,
            isl_range_hysteresis_km=200.0,
            sgl_elevation_hysteresis_deg=2.0
        )

        active_sats = controller.setup_environment(max_satellites=50)

        if len(active_sats) < 2:
            await websocket.send_json({"error": "卫星数量不足以进行路由。"})
            return

        if sim_state["src_node"] is None:
            sim_state["src_node"] = active_sats[4]
        if sim_state["dst_node"] is None:
            sim_state["dst_node"] = active_sats[19]

        total_steps = len(controller.time_index)

        while True:
            # ==== 【核心终极修复 2：防止死循环产生僵尸进程】 ====
            # 在暂停或结束状态下，必须发送一个带错误捕获的"空包/心跳包"
            # 以探测客户端是否已经刷新或关闭了网页
            if not sim_state["is_playing"] or sim_state["step_idx"] >= total_steps:
                try:
                    # 随便发一点信息作为心跳探测
                    await websocket.send_json({"status": "paused_or_finished", "timestamp": "heartbeat"})
                    await asyncio.sleep(0.5)
                    continue
                except:
                    break  # 如果网页关闭了，发送失败，立刻跳出 while True 释放资源！
            # ======================================================

            # 读取当前播放帧的索引并获取时间
            current_idx = sim_state["step_idx"]
            current_time = controller.time_index[current_idx]

            if current_idx == 0:
                controller.reset_topology_state()

            snapshot_df = controller._get_snapshot(current_time)
            graph = controller.build_topology(snapshot_df)

            src_node = sim_state["src_node"]
            dst_node = sim_state["dst_node"]

            if sim_state["strategy"] == "shortest_distance":
                route_res = RoutingEngine.calculate_shortest_distance_path(graph, src_node, dst_node)
            else:
                route_res = RoutingEngine.calculate_minimum_hops_path(graph, src_node, dst_node)

            nodes_data = {}
            for idx, row in snapshot_df.iterrows():
                nodes_data[idx] = {
                    "lat": round(row['latitude'], 4),
                    "lon": round(row['longitude'], 4),
                    "alt": round(row['altitude_km'], 2)
                }

            edges_data = list(graph.edges())

            payload = {
                "timestamp": current_time.isoformat(),
                "nodes": nodes_data,
                "topology_edges": edges_data,
                "active_route": {
                    "success": route_res['success'],
                    "path": route_res['path'] if route_res['success'] else [],
                    "delay_ms": round(route_res['propagation_delay_ms'], 2) if route_res['success'] else 0.0,
                    "total_delay_ms": round(route_res['total_delay_ms'], 2) if route_res['success'] else 0.0,
                    "hops": route_res['hops'] if route_res['success'] else 0,
                    "isl_hops": route_res['isl_hops'] if route_res['success'] else 0,
                    "isl_bottleneck_capacity_gbps": route_res['isl_bottleneck_capacity_gbps'] if route_res['success'] else None,
                    "expected_packet_loss_rate": route_res['expected_packet_loss_rate'] if route_res['success'] else None
                }
            }

            await websocket.send_json(payload)

            sim_state["step_idx"] += 1
            sleep_duration = 1.0 / sim_state["speed"]
            await asyncio.sleep(sleep_duration)

    except WebSocketDisconnect:
        print("[!] 客户端正常断开连接。")
    except Exception as e:
        print(f"[x] 发生错误: {e}")

# uvicorn main:app --reload
# http://localhost:8000
