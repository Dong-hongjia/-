import asyncio
import json
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import pandas as pd

from simulation_controller import SimulationController
from topology_builder import TopologyBuilder
from routing_engine import RoutingEngine

app = FastAPI(title="NTN-TN Simulation API")

# 全局仿真状态字典 (绝对纯净版，无播放控制字段)
sim_state = {
    "strategy": "shortest_distance",
    "src_node": None,
    "dst_node": None,
}

html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <title>NTN-TN 异构网络 3D 仿真平台</title>
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

        <div class="hud-title" style="margin-top: 15px; border-top: 1px solid #334155; padding-top: 10px;">⚙️ 仿真控制</div>

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
    </div>

    <script type="module">
        Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJjM2I0YTk3OC1mZTVlLTQzNTgtYmUwMC02MmVjNjY0ZDJlN2YiLCJpZCI6NDU0MzUzLCJpc3MiOiJodHRwczovL2FwaS5jZXNpdW0uY29tIiwiYXVkIjoidW5kZWZpbmVkX2RlZmF1bHQiLCJpYXQiOjE3ODM1ODUwOTF9.yiVXDATP4JtxfOi0UwImNnk13qjfwrk-0iJjDwmxsd4';

        const viewer = new Cesium.Viewer('cesiumContainer', {
            terrain: Cesium.Terrain.fromWorldTerrain(), 
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

        viewer.camera.setView({
            destination: Cesium.Cartesian3.fromDegrees(115.0, 20.0, 18000000.0)
        });

        const satEntities = {}; 
        const topologySource = new Cesium.CustomDataSource('topology'); 
        const activeRouteSource = new Cesium.CustomDataSource('active_route'); 
        viewer.dataSources.add(topologySource);
        viewer.dataSources.add(activeRouteSource);

        const ws = new WebSocket("ws://localhost:8000/ws");

        let isNodesPopulated = false; 

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

            if (!isNodesPopulated && Object.keys(data.nodes).length > 0) {
                const nodeIds = Object.keys(data.nodes).sort(); 
                const srcSelect = document.getElementById('src_select');
                const dstSelect = document.getElementById('dst_select');

                nodeIds.forEach(id => {
                    srcSelect.add(new Option(id, id));
                    dstSelect.add(new Option(id, id));
                });

                srcSelect.value = nodeIds[4];
                dstSelect.value = nodeIds[19];

                isNodesPopulated = true;
            }

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

            // 渲染网元节点 (修复：区分地面站和卫星，地面站更大且为绿色)
            for (const [nodeId, coords] of Object.entries(data.nodes)) {
                const position = Cesium.Cartesian3.fromDegrees(coords.lon, coords.lat, coords.alt * 1000);

                if (!satEntities[nodeId]) {
                    // 根据类型判断样式
                    const isGS = coords.type === 'GS';
                    const dotColor = isGS ? Cesium.Color.LIMEGREEN : Cesium.Color.CYAN;
                    const dotSize = isGS ? 12 : 6; // 地面站尺寸更大

                    satEntities[nodeId] = viewer.entities.add({
                        id: nodeId,
                        position: position,
                        point: { pixelSize: dotSize, color: dotColor, outlineColor: Cesium.Color.WHITE, outlineWidth: 1 },
                        label: {
                            text: nodeId, 
                            font: 'bold 12px sans-serif', 
                            fillColor: isGS ? Cesium.Color.LIMEGREEN : Cesium.Color.WHITE, // 地面站文字也为绿色
                            style: Cesium.LabelStyle.FILL_AND_OUTLINE, 
                            outlineColor: Cesium.Color.BLACK,          
                            outlineWidth: 2,
                            pixelOffset: new Cesium.Cartesian2(0, -15),
                            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 60000000)
                        }
                    });
                } else {
                    satEntities[nodeId].position = position;
                }
            }

            const currentEdgeIds = new Set();

            data.topology_edges.forEach(edge => {
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
                        topologySource.entities.add({
                            id: edgeId,
                            polyline: {
                                positions: positions,
                                width: 2.0, 
                                material: Cesium.Color.fromCssColorString('rgba(56, 189, 248, 0.4)'), 
                                arcType: Cesium.ArcType.NONE 
                            }
                        });
                    } else {
                        edgeEntity.polyline.positions = positions;
                    }
                }
            });

            const edgesToRemove = [];
            topologySource.entities.values.forEach(entity => {
                if (!currentEdgeIds.has(entity.id)) {
                    edgesToRemove.push(entity);
                }
            });
            edgesToRemove.forEach(entity => topologySource.entities.remove(entity));

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
                        width: 8.5,
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
    return HTMLResponse(html)


class StrategyRequest(BaseModel):
    strategy: str


class NodesRequest(BaseModel):
    src_node: str
    dst_node: str


@app.post("/api/strategy")
async def update_strategy(req: StrategyRequest):
    if req.strategy in ["shortest_distance", "min_hops"]:
        sim_state["strategy"] = req.strategy
        return {"status": "success", "strategy": req.strategy}
    return {"status": "error", "msg": "未知的路由策略"}


@app.post("/api/nodes")
async def update_nodes(req: NodesRequest):
    sim_state["src_node"] = req.src_node
    sim_state["dst_node"] = req.dst_node
    return {"status": "success", "src_node": req.src_node, "dst_node": req.dst_node}


@app.websocket("/ws")
async def simulation_endpoint(websocket: WebSocket):
    await websocket.accept()

    REAL_TLE_FILE = r"C:\Users\dongh\Desktop\shixi\TLE.txt"
    sim_start = datetime.now(timezone.utc) + timedelta(days=1)

    try:
        controller = SimulationController(
            tle_file_path=REAL_TLE_FILE,
            start_time_utc=sim_start,
            duration_minutes=60,
            step_seconds=1.0,
            max_isl_range_km=5000.0,
            max_neighbors_per_satellite=6
        )

        active_sats = controller.setup_environment(max_satellites=50)

        if len(active_sats) < 2:
            await websocket.send_json({"error": "卫星数量不足以进行路由。"})
            return

        if sim_state["src_node"] is None:
            sim_state["src_node"] = active_sats[4]
        if sim_state["dst_node"] is None:
            sim_state["dst_node"] = active_sats[19]

        for current_time in controller.time_index:
            snapshot_df = controller._get_snapshot(current_time)
            # 【新增修改】：把控制器里定义的地面站传进去，要求卫星仰角必须大于 15 度
            graph = TopologyBuilder.build_snapshot_graph(
                snapshot_df,
                controller.max_isl_range_km,
                ground_stations=controller.ground_stations,
                min_elevation_deg=15.0,
                max_neighbors_per_satellite=controller.max_neighbors_per_satellite
            )

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
                    "alt": round(row['altitude_km'], 2),
                    "type": "SAT"
                }
            # 2. 【新增修改】：把地面站的坐标也提取出来给前端渲染
            for gs_name, gs_info in controller.ground_stations.items():
                nodes_data[gs_name] = {
                    "lat": gs_info['lat'],
                    "lon": gs_info['lon'],
                    "alt": gs_info.get('alt', 0.0),
                    "type": "GS"
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
                    "hops": route_res['hops'] if route_res['success'] else 0
                }
            }

            await websocket.send_json(payload)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print("[!] 客户端断开连接。")
    except Exception as e:
        print(f"[x] 发生错误: {e}")
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass

# uvicorn main:app --reload
# http://localhost:8000
