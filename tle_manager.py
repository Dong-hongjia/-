import os
from typing import Dict, List, Optional, Tuple
from orbit_propagator import OrbitPropagator  # 导入我们上一节写的传播器


class TLEManager:
    """
    TLE 本地文件数据管理器与卫星工厂。
    支持解析 2行/3行 格式的 TLE 文件，并批量构建 OrbitPropagator。
    """

    def __init__(self, file_path: str):
        """
        初始化管理器并建立本地 TLE 索引。

        参数:
            file_path: 本地 TLE 文本文件路径 (.txt 或 .tle)
        """
        self.file_path = file_path
        # 内部存储结构: { satellite_id_or_name: (line1, line2, name) }
        self._tle_db: Dict[str, Tuple[str, str, str]] = {}

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"未找到指定的 TLE 文件: {file_path}")

        self._parse_tle_file()

    def _parse_tle_file(self) -> None:
        """
        内部解析函数：读取 TLE 文件并建立内存索引（兼容 2行 和 3行 格式）。
        """
        with open(self.file_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        i = 0
        while i < len(lines):
            # 检查当前行是否为标准 TLE 的第一行 (以 1 开头，且包含特定长度和格式验证)
            if lines[i].startswith('1 ') and (i + 1) < len(lines) and lines[i + 1].startswith('2 '):
                # 场景 A：两行式格式（无显式名称行）
                line1 = lines[i]
                line2 = lines[i + 1]
                norad_id = line1[2:7].strip()  # 提取 5 位 NORAD 目录号
                name = f"NORAD-{norad_id}"  # 默认名称

                self._tle_db[norad_id] = (line1, line2, name)
                i += 2
            elif i + 2 < len(lines) and lines[i + 1].startswith('1 ') and lines[i + 2].startswith('2 '):
                # 场景 B：传统三行式格式（第一行是名称）
                name = lines[i]
                line1 = lines[i + 1]
                line2 = lines[i + 2]
                norad_id = line1[2:7].strip()

                # 同时支持用名称和 ID 进行检索
                self._tle_db[name.upper()] = (line1, line2, name)
                self._tle_db[norad_id] = (line1, line2, name)
                i += 3
            else:
                # 无法识别的噪声行，跳过
                i += 1

        print(f"成功加载 TLE 文件，共索引了 {len(self._tle_db)} 条卫星检索项。")

    def get_satellite_names(self) -> List[str]:
        """获取文件中所有已加载的卫星唯一标识或名称"""
        return list(self._tle_db.keys())

    def create_propagator(self, identifier: str) -> Optional[OrbitPropagator]:
        """
        根据名称或 NORAD ID 创建对应的独立轨道推算器实例。

        参数:
            identifier: 卫星名称（如 'STARLINK-30113'）或 NORAD ID（如 '52758'）
        """
        key = identifier.upper()
        if key not in self._tle_db:
            print(f"警告: 在当前 TLE 文件中未找到卫星: {identifier}")
            return None

        line1, line2, name = self._tle_db[key]
        return OrbitPropagator(name=name, line1=line1, line2=line2)

    def create_batch_propagators(self, identifiers: List[str]) -> Dict[str, OrbitPropagator]:
        """
        批量创建多个卫星的轨道推算器，适用于星座仿真或多网元场景。
        """
        propagators = {}
        for identifier in identifiers:
            prog = self.create_propagator(identifier)
            if prog:
                propagators[identifier] = prog
        return propagators


# ==========================================
# 本地验证与演练
# ==========================================
if __name__ == "__main__":
    # 直接使用本地真实的 TLE 文件路径
    REAL_FILE_PATH = r"C:\Users\dongh\Desktop\shixi\TLE.txt"

    print(f"--- 启动 TLE 数据管理层，加载本地文件: {REAL_FILE_PATH} ---")
    try:
        # 1. 初始化管理器
        manager = TLEManager(REAL_FILE_PATH)

        # 2. 获取并打印加载的卫星总数，确认读取成功
        available_sats = manager.get_satellite_names()
        print(f"成功加载，当前文件中包含 {len(available_sats)} 个有效空间网元。")

        # 3. 抽取部分卫星打印出来看看，确保索引正常
        if len(available_sats) > 0:
            print(f"部分可用卫星列表: {available_sats[:5]}")

            # 随机提取第一个卫星进行测试
            test_sat_id = available_sats[0]
            test_prog = manager.create_propagator(test_sat_id)
            if test_prog:
                print(f"成功实例化测试网元: {test_prog.name}")

    except FileNotFoundError as e:
        print(f"错误: {e}\n请检查路径是否正确，以及文件是否存在。")
    except Exception as e:
        print(f"解析文件时发生未知错误: {e}")