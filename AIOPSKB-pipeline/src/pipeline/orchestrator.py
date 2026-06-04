import os
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import DATA_DIR, REPORTS_DIR, MIN_PASS_SCORE, MAX_CONSECUTIVE_FAILURES, INDUSTRY_CODES
from agents.collector import collect_layer
from agents.judge import judge_layer, judge_single
from reports import write_report, write_judge_report
from file_manager import write_kb_file, read_kb_file, ensure_data_dir


class Orchestrator:
    _thread_id_counter = 0
    _thread_id_lock = threading.Lock()
    _thread_local = threading.local()

    def __init__(self, industry: str, seed_subs: list[str] = None):
        self.industry = industry
        self.code = INDUSTRY_CODES[industry]
        self.data_dir = os.path.join(DATA_DIR, self._slug(industry))
        self.log_lines = []
        self.seed_subs = seed_subs
        self._log_lock = threading.Lock()
        self._progress_done = 0
        self._progress_lock = threading.Lock()

    @classmethod
    def _get_thread_tag(cls) -> str:
        """Return a short thread tag like 'T1', 'T2', etc. per unique thread."""
        tag = getattr(cls._thread_local, 'tag', None)
        if tag is None:
            with cls._thread_id_lock:
                cls._thread_id_counter += 1
                tag = f"T{cls._thread_id_counter}"
            cls._thread_local.tag = tag
        return tag

    # ── slug helpers ──

    def _slug(self, name: str) -> str:
        return {"电力": "power", "石化": "petrochemical", "冶金": "metallurgy",
                "水泥": "cement", "煤炭": "coal", "轨道交通": "rail_transit",
                "制造业": "manufacturing", "航空航天与船舶": "aerospace_marine"}.get(name, name)

    def _slug_sub(self, name: str) -> str:
        return {"火电": "thermal", "水电": "hydro", "风电": "wind", "光伏": "pv",
                "核电": "nuclear", "燃气轮机": "gas_turbine", "抽水蓄能": "pumped_storage",
                "输电": "transmission", "变电": "substation", "配电": "distribution",
                "储能": "energy_storage"}.get(name, name)

    def _slug_eq(self, name: str) -> str:
        # 已有英文目录的设备保留映射，其余直接用设备名
        known = {
            "锅炉": "boiler", "汽轮机": "steam_turbine", "发电机": "generator",
            "主变压器": "main_transformer", "水轮机": "hydro_turbine",
            "凝汽器": "condenser", "励磁系统": "excitation_system",
            "冷却塔/空冷岛": "cooling_tower",
            "箱式变压器（风电用）": "箱式变压器",
            "发电机出口断路器": "发电机出口断路器(GCB)",
        }
        return known.get(name, name.replace("/", "_").replace("／", "_").replace("（", "(").replace("）", ")"))

    # ── logging ──

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        tag = self._get_thread_tag()
        line = f"[{ts}] [{tag}] {msg}"
        with self._log_lock:
            print(line, flush=True)
            self.log_lines.append(line)

    def _write_run_log(self):
        run_dir = os.path.join(REPORTS_DIR, self._slug(self.industry))
        ensure_data_dir(run_dir)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(run_dir, f"runlog_{ts}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# 运行日志: {self.industry}\n> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for line in self.log_lines:
                f.write(line + "\n")
        self.log(f"运行日志已保存: {path}")

    # ── disk I/O helpers ──

    def _read_sub_list(self) -> list[str]:
        """从 index.md 读取子行业名称列表"""
        index_path = os.path.join(self.data_dir, "index.md")
        content = read_kb_file(index_path)
        if not content:
            return []
        subs = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if not cells:
                    continue
                name = cells[0].strip("*").strip()
                if name and name not in ("子行业名称", "代码", "子行业/领域名称", ":---"):
                    subs.append(name)
        return subs

    def _read_equipment_list(self, sub_dir: str, with_types: bool = False):
        """从 equipment_registry.md 读取设备列表。
        with_types=False → 返回 list[str] (仅名称)
        with_types=True  → 返回 list[tuple(str,str)] (名称, 类型)
        """
        path = os.path.join(sub_dir, "equipment_registry.md")
        content = read_kb_file(path)
        if not content:
            return []
        equips = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if not cells:
                    continue
                name = cells[0].strip("*").strip()
                if name and name not in ("设备名称", "设备代码", ":---"):
                    if with_types and len(cells) >= 2:
                        etype = cells[1].strip()
                        equips.append((name, etype))
                    else:
                        equips.append(name)
        return equips

    def _read_component_list(self, equip_dir: str) -> list[str]:
        """从 components.md 读取全部部件列表（叶节点优先，父节点在后）"""
        path = os.path.join(equip_dir, "components.md")
        content = read_kb_file(path)
        if not content:
            return []

        all_names = []
        parent_names = set()
        seen = set()
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 2:
                    name = cells[0].strip("*").strip()
                    parent = cells[1].strip()
                    if name and name not in ("部件名称",) and name not in seen:
                        all_names.append(name)
                        seen.add(name)
                        if parent and parent not in ("—", "-", ""):
                            parent_names.add(parent)

        # 叶节点优先（无子部件），父节点在后（有子部件但存在整体宏观故障）
        leaves = [n for n in all_names if n not in parent_names]
        parents = [n for n in all_names if n in parent_names]
        return leaves + parents

    def _get_children(self, equip_dir: str, comp_name: str) -> list[str]:
        """获取某部件的直接子部件列表"""
        path = os.path.join(equip_dir, "components.md")
        content = read_kb_file(path)
        if not content:
            return []
        children = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 2:
                    name = cells[0].strip("*").strip()
                    parent = cells[1].strip()
                    if parent == comp_name and name not in ("部件名称",):
                        children.append(name)
        return children

    def _read_sub_equipment_names(self, equip_dir: str) -> list[str]:
        """读取 sub_equipment.md，返回子设备名称列表。
        无 sub_equipment.md 时返回空列表，表示该设备无子设备层级。"""
        sub_eq_path = os.path.join(equip_dir, "sub_equipment.md")
        if not os.path.exists(sub_eq_path):
            return []
        content = read_kb_file(sub_eq_path)
        if not content:
            return []
        names = []
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
            if cells and cells[0] not in ("子设备名称", ""):
                names.append(cells[0])
        return names

    @staticmethod
    def _sanitize_sub_eq_name(name: str) -> str:
        """将子设备名称转为安全的目录名。"""
        return name.replace("/", "／").replace("\\", "＼").strip()

    # ── Phase 1: Sub-industry ──

    def run_sub_industry(self):
        self.log(f"===== 阶段1: 子行业划分 - {self.industry} =====")
        ensure_data_dir(self.data_dir)

        if self.seed_subs:
            self.log(f"  使用用户提供的种子子行业: {self.seed_subs}")
            sub_list = self.seed_subs
            sub_industry_data = self._build_sub_industry_index(sub_list)
            has_subs = True
        else:
            sub_industry_data, has_subs, sub_list = self._run_layer(
                layer="sub_industry",
                context={"industry": self.industry},
                output_path=os.path.join(self.data_dir, "index.md"),
            )

        if has_subs and sub_list:
            self.log(f"  确定 {len(sub_list)} 个子行业: {sub_list}")
            write_kb_file(os.path.join(self.data_dir, "index.md"), sub_industry_data)
            write_report(self._slug(self.industry), "phase1_sub_industry", sub_industry_data)
        else:
            self.log("  该行业不需要子行业划分")
            write_kb_file(os.path.join(self.data_dir, "index.md"), sub_industry_data)

        self.log(f"===== 阶段1 完成 =====")
        self._write_run_log()

    # ── Phase 2: Equipment ──

    def run_equipment(self, sub_filter: str = None):
        self.log(f"===== 阶段2: 设备枚举 - {self.industry} =====")

        sub_list = self._get_sub_list(sub_filter)
        for sub in sub_list:
            self.log(f"  处理子行业: {sub}")
            sub_dir = os.path.join(self.data_dir, self._slug_sub(sub))
            ensure_data_dir(sub_dir)

            equip_result = self._run_layer(
                layer="equipment",
                context={"industry": self.industry, "sub_industry": sub},
                output_path=os.path.join(sub_dir, "equipment_registry.md"),
            )
            equip_data = equip_result[0]
            write_kb_file(os.path.join(sub_dir, "equipment_registry.md"), equip_data)
            write_report(self._slug(self.industry), f"phase2_{self._slug_sub(sub)}_equipment", equip_data)

            # Phase 2.5: Sub-equipment split
            sub_equips = self._identify_sub_equipment_needs(sub, equip_data)
            for eq_name in sub_equips:
                self.log(f"  阶段2.5: 子设备拆分 - {eq_name}")
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                ensure_data_dir(eq_dir)

                sub_eq_result = self._run_layer(
                    layer="sub_equipment",
                    context={"industry": self.industry, "sub_industry": sub, "equipment": eq_name},
                    output_path=os.path.join(eq_dir, "sub_equipment.md"),
                )
                sub_eq_data = sub_eq_result[0]
                write_kb_file(os.path.join(eq_dir, "sub_equipment.md"), sub_eq_data)
                write_report(self._slug(self.industry),
                             f"phase2.5_{self._slug_sub(sub)}_{self._slug_eq(eq_name)}_sub_equip", sub_eq_data)

        self.log(f"===== 阶段2 完成 =====")
        self._write_run_log()

    # ── Phase 3: Component ──

    def run_component(self, sub_filter: str = None, equip_filter: str = None,
                      equip_type: str = None):
        self.log(f"===== 阶段3: 部件拆解 - {self.industry} =====")
        if equip_type:
            self.log(f"  设备类型筛选: {equip_type}")

        sub_list = self._get_sub_list(sub_filter)
        for sub in sub_list:
            sub_dir = os.path.join(self.data_dir, self._slug_sub(sub))
            equip_list = self._get_equip_list(sub_dir, equip_filter, equip_type)

            for eq_name in equip_list:
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                ensure_data_dir(eq_dir)

                # 检查是否有子设备层级
                sub_eq_names = self._read_sub_equipment_names(eq_dir)

                if sub_eq_names:
                    # 有子设备：逐个子设备生成部件树
                    for sub_eq_name in sub_eq_names:
                        sub_eq_dirname = self._sanitize_sub_eq_name(sub_eq_name)
                        sub_eq_dir = os.path.join(eq_dir, sub_eq_dirname)
                        comp_path = os.path.join(sub_eq_dir, "components.md")

                        # 增量构建：跳过已有数据的子设备
                        if os.path.exists(comp_path):
                            existing = read_kb_file(comp_path)
                            if existing and existing.strip():
                                self.log(f"  跳过(已有数据): {sub} - {eq_name} - {sub_eq_name}")
                                continue

                        self.log(f"  处理子设备: {sub} - {eq_name} - {sub_eq_name}")
                        ensure_data_dir(sub_eq_dir)

                        comp_result = self._run_layer(
                            layer="component",
                            context={"industry": self.industry, "sub_industry": sub,
                                     "equipment": eq_name, "sub_equipment": sub_eq_name},
                            output_path=comp_path,
                        )
                        comp_data = comp_result[0]
                        write_kb_file(comp_path, comp_data)
                        write_report(self._slug(self.industry),
                                     f"phase3_{self._slug_sub(sub)}_{self._slug_eq(eq_name)}_{sub_eq_dirname}_components",
                                     comp_data)
                else:
                    # 无子设备：直接在设备目录下生成（原逻辑）
                    comp_path = os.path.join(eq_dir, "components.md")

                    # 增量构建：跳过已有部件数据的设备
                    if os.path.exists(comp_path):
                        existing = read_kb_file(comp_path)
                        if existing and existing.strip():
                            self.log(f"  跳过(已有数据): {sub} - {eq_name}")
                            continue

                    self.log(f"  处理设备: {sub} - {eq_name}")

                    comp_result = self._run_layer(
                        layer="component",
                        context={"industry": self.industry, "sub_industry": sub, "equipment": eq_name},
                        output_path=comp_path,
                    )
                    comp_data = comp_result[0]
                    write_kb_file(comp_path, comp_data)
                    write_report(self._slug(self.industry),
                                 f"phase3_{self._slug_sub(sub)}_{self._slug_eq(eq_name)}_components", comp_data)

        self.log(f"===== 阶段3 完成 =====")
        self._write_run_log()

    # ── Phase 4: Fault ──

    def run_fault(self, sub_filter: str = None, equip_filter: str = None,
                  comp_filter: str = None, equip_type: str = None,
                  force: bool = False, workers: int = 1):
        self.log(f"===== 阶段4: 故障知识 - {self.industry} (workers={workers}) =====")

        # Phase 1: Collect all tasks
        tasks = []
        sub_list = self._get_sub_list(sub_filter)
        for sub in sub_list:
            sub_dir = os.path.join(self.data_dir, self._slug_sub(sub))
            equip_list = self._get_equip_list(sub_dir, equip_filter, equip_type)

            for eq_name in equip_list:
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                sub_eq_names = self._read_sub_equipment_names(eq_dir)

                if sub_eq_names:
                    # 有子设备：逐个子设备的部件生成故障
                    for sub_eq_name in sub_eq_names:
                        sub_eq_dirname = self._sanitize_sub_eq_name(sub_eq_name)
                        sub_eq_dir = os.path.join(eq_dir, sub_eq_dirname)
                        if not os.path.isdir(sub_eq_dir):
                            continue
                        comp_list = self._get_comp_list(sub_eq_dir, comp_filter)

                        for comp_name in comp_list:
                            safe_comp = comp_name.replace("/", "／")
                            faults_dir = os.path.join(sub_eq_dir, "faults")
                            ensure_data_dir(faults_dir)
                            fault_path = os.path.join(faults_dir, f"{safe_comp}.md")

                            # Incremental skip
                            if not force and os.path.exists(fault_path):
                                existing = read_kb_file(fault_path)
                                if existing and existing.strip():
                                    self.log(f"  跳过(已有数据): {sub} - {eq_name} - {sub_eq_name} - {comp_name}")
                                    continue

                            children = self._get_children(sub_eq_dir, comp_name)

                            tasks.append({
                                "sub": sub, "eq_name": eq_name,
                                "sub_equipment": sub_eq_name,
                                "comp_name": comp_name,
                                "safe_comp": safe_comp, "fault_path": fault_path,
                                "context": {"industry": self.industry, "sub_industry": sub,
                                            "equipment": eq_name, "component": comp_name,
                                            "children": children, "sub_equipment": sub_eq_name},
                            })
                else:
                    # 无子设备：原逻辑（直接在设备目录下）
                    comp_list = self._get_comp_list(eq_dir, comp_filter)

                    for comp_name in comp_list:
                        safe_comp = comp_name.replace("/", "／")
                        faults_dir = os.path.join(eq_dir, "faults")
                        ensure_data_dir(faults_dir)
                        fault_path = os.path.join(faults_dir, f"{safe_comp}.md")

                        # Incremental skip
                        if not force and os.path.exists(fault_path):
                            existing = read_kb_file(fault_path)
                            if existing and existing.strip():
                                self.log(f"  跳过(已有数据): {sub} - {eq_name} - {comp_name}")
                                continue

                        children = self._get_children(eq_dir, comp_name)

                        tasks.append({
                            "sub": sub, "eq_name": eq_name,
                            "sub_equipment": "",
                            "comp_name": comp_name,
                            "safe_comp": safe_comp, "fault_path": fault_path,
                            "context": {"industry": self.industry, "sub_industry": sub,
                                        "equipment": eq_name, "component": comp_name,
                                        "children": children, "sub_equipment": ""},
                        })

        total = len(tasks)
        self.log(f"  共 {total} 个部件待处理")
        if total == 0:
            self.log(f"===== 阶段4 完成（无任务）=====")
            self._write_run_log()
            return

        self._progress_done = 0

        # Phase 2: Execute
        if workers <= 1:
            for i, task in enumerate(tasks, 1):
                self._process_fault_component(task, i, total)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for i, task in enumerate(tasks, 1):
                    f = pool.submit(self._process_fault_component, task, i, total)
                    futures[f] = task
                for f in as_completed(futures):
                    task = futures[f]
                    try:
                        f.result()
                    except Exception as e:
                        self.log(f"  ERROR: {task['sub']} - {task['eq_name']} - {task['comp_name']}: {e}")

        self.log(f"===== 阶段4 完成 =====")
        self._write_run_log()

    def _process_fault_component(self, task: dict, idx: int, total: int):
        """Process a single fault component through Phase A→B→C. Thread-safe."""
        sub = task["sub"]
        eq_name = task["eq_name"]
        comp_name = task["comp_name"]
        fault_path = task["fault_path"]
        ctx = task["context"]
        safe_comp = task["safe_comp"]

        self.log(f"  [{idx}/{total}] 处理部件: {sub} - {eq_name} - {comp_name}")

        fault_result = self._run_layer(layer="fault", context=ctx, output_path=fault_path)
        fault_data = fault_result[0]
        write_kb_file(fault_path, fault_data)
        write_report(self._slug(self.industry),
                     f"phase4_{self._slug_sub(sub)}_{self._slug_eq(eq_name)}_{safe_comp}_faults",
                     fault_data)

        with self._progress_lock:
            self._progress_done += 1
            done = self._progress_done
        self.log(f"  [{done}/{total}] 完成: {sub} - {eq_name} - {comp_name}")

    # ── Phase 5: Validate ──

    def run_validate(self, sub_filter: str = None):
        self.log(f"===== 阶段5: 验证 - {self.industry} =====")
        self.log("  (待实现)")
        self._write_run_log()

    # ── Schema migration: D1-D10 → D1-D9 + component-level attrs ──

    def _parse_component_table(self, content: str) -> list[dict]:
        """Parse components.md into list of dicts with leaf detection."""
        lines = content.split("\n")
        headers = None
        rows = []

        for line in lines:
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
            if not cells:
                continue
            if headers is None:
                headers = cells
                continue
            if len(cells) != len(headers):
                continue
            row = {}
            for h, v in zip(headers, cells):
                row[h] = v
            rows.append(row)

        # Determine leaf nodes
        all_names = {r.get("部件名称", "") for r in rows}
        parent_names = {r.get("父部件", "") for r in rows
                        if r.get("父部件") and r["父部件"] not in ("—", "-", "")}
        for r in rows:
            name = r.get("部件名称", "")
            r["is_leaf"] = name not in parent_names

        return rows

    def _rebuild_component_table(self, content: str, maint_map: dict) -> str:
        """Rebuild components.md with 维护方法+报废方法 columns added."""
        lines = content.split("\n")
        new_lines = []
        col_count = None

        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|"):
                new_lines.append(line)
                continue

            if re.match(r'^\|[\s\-:|]+\|$', stripped):
                # Separator: add two more columns
                new_lines.append(stripped[:-1] + ":---|:---|")
                continue

            cells = [c for c in stripped.split("|")]
            # Remove empty first/last from split
            inner = cells[1:-1] if cells[0] == "" and cells[-1] == "" else cells

            first_cell = inner[0].strip().strip("*") if inner else ""
            if first_cell in ("部件名称",):
                # Header row: append 维护方法 + 报废方法
                new_lines.append(stripped[:-1] + " 维护方法 | 报废方法 |")
                col_count = len(inner) + 2
                continue

            # Data row: look up 维护方法 and 报废方法
            name = first_cell
            maint_val, disposal_val = maint_map.get(name, ("—", "—"))
            new_lines.append(stripped[:-1] + f" {maint_val} | {disposal_val} |")

        return "\n".join(new_lines)

    def _parse_fault_table(self, content: str) -> list[dict]:
        """Parse a fault markdown table into list of dicts with column keys."""
        lines = content.split("\n")
        headers = None
        rows = []

        for line in lines:
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
            if not cells:
                continue
            if headers is None:
                headers = cells
                continue
            if len(cells) != len(headers):
                continue
            row = {}
            for h, v in zip(headers, cells):
                row[h] = v if v not in ("—", "-", "") else ""
            rows.append(row)

        # Map column names to short keys (supports both D1-D10 and D1-D9 schemas)
        key_map = {
            "故障名称": "故障名称",
            "D1 故障类别": "D1", "D2 故障等级": "D2",
            "D3 故障描述与机理": "D3", "D4 故障征兆": "D4",
            "D5 故障特征参数": "D5", "D6 监测与检测手段": "D6",
            "D7 诊断方法": "D7", "D8 检修方法": "D8",
            "D9 预防措施": "D9", "D10 易混淆故障": "D10",
        }
        mapped_rows = []
        for row in rows:
            mapped = {}
            for h, v in row.items():
                key = key_map.get(h, h)
                mapped[key] = v
            mapped_rows.append(mapped)
        return mapped_rows

    def _build_fault_table(self, rows: list[dict]) -> str:
        """Build a D1-D9 markdown table from row dicts."""
        columns = [
            ("故障名称", "故障名称"),
            ("D1", "D1 故障类别"),
            ("D2", "D2 故障等级"),
            ("D3", "D3 故障描述与机理"),
            ("D4", "D4 故障征兆"),
            ("D5", "D5 故障特征参数"),
            ("D6", "D6 监测与检测手段"),
            ("D7", "D7 诊断方法"),
            ("D8", "D8 检修方法"),
            ("D9", "D9 预防措施"),
            ("D10", "D10 易混淆故障"),
        ]

        lines = []
        # Header
        lines.append("| " + " | ".join(display for _, display in columns) + " |")
        # Separator
        lines.append("| " + " | ".join(":---" for _ in columns) + " |")
        # Data rows
        for row in rows:
            cells = []
            for key, _ in columns:
                val = row.get(key, "—") or "—"
                cells.append(val)
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines) + "\n"

    # ── Filtered list helpers (read from disk) ──

    def _get_sub_list(self, sub_filter: str = None) -> list[str]:
        sub_list = self._read_sub_list()
        if not sub_list:
            # check if there's no sub-industry (index.md might not exist or be empty)
            self.log("  未找到子行业数据，请先运行阶段1")
            return []
        if sub_filter:
            if sub_filter not in sub_list:
                self.log(f"  警告: 子行业 '{sub_filter}' 不在已有列表中")
                return []
            self.log(f"  仅处理子行业: {sub_filter}")
            return [sub_filter]
        self.log(f"  处理全部 {len(sub_list)} 个子行业")
        return sub_list

    def _get_equip_list(self, sub_dir: str, equip_filter: str = None,
                        equip_type: str = None) -> list[str]:
        # 如果需要按类型筛选，读取带类型的列表
        if equip_type:
            equip_with_types = self._read_equipment_list(sub_dir, with_types=True)
            if not equip_with_types:
                self.log(f"  未找到设备数据: {sub_dir}，请先运行阶段2")
                return []
            filtered = [name for name, etype in equip_with_types if etype == equip_type]
            if not filtered:
                self.log(f"  设备类型 '{equip_type}' 下无匹配设备")
            self.log(f"  筛选出 {len(filtered)} 台{equip_type}")
            if equip_filter:
                if equip_filter not in filtered:
                    self.log(f"  警告: 设备 '{equip_filter}' 不在类型 '{equip_type}' 下")
                    return []
                return [equip_filter]
            return filtered

        equip_list = self._read_equipment_list(sub_dir)
        if not equip_list:
            self.log(f"  未找到设备数据: {sub_dir}，请先运行阶段2")
            return []
        if equip_filter:
            if equip_filter not in equip_list:
                self.log(f"  警告: 设备 '{equip_filter}' 不在已有列表中")
                return []
            return [equip_filter]
        return equip_list

    def _get_comp_list(self, equip_dir: str, comp_filter: str = None) -> list[str]:
        comp_list = self._read_component_list(equip_dir)
        if not comp_list:
            self.log(f"  未找到部件数据: {equip_dir}，请先运行阶段3")
            return []
        if comp_filter:
            if comp_filter not in comp_list:
                self.log(f"  警告: 部件 '{comp_filter}' 不在已有列表中")
                return []
            return [comp_filter]
        return comp_list

    # ── Core layer execution (shared by all phases) ──

    def _run_layer(self, layer: str, context: dict, output_path: str) -> tuple:
        accumulated = ""
        consecutive_failures = 0
        round_num = 0
        max_judge_rounds = 2
        skip_consolidation = False

        # Phase A: Expansion (max 2 collection rounds, max 2 judge rounds)
        self.log(f"  阶段A: 扩充 - {layer}")
        for i in range(2):
            round_num += 1
            self.log(f"    扩充第{i+1}轮")

            result, search_info = collect_layer(layer, context | {"existing": accumulated})
            if accumulated:
                # 去掉后续轮次的表头和分隔符行，只追加数据行
                _hdrs = {"sub_industry": {"子行业名称"}, "equipment": {"设备名称"},
                         "sub_equipment": {"子设备名称"}, "component": {"部件名称"},
                         "fault": {"故障名称"}}
                hdrs = _hdrs.get(layer, set())
                data_lines = []
                for line in result.split("\n"):
                    stripped = line.strip()
                    if not stripped.startswith("|"):
                        continue
                    if re.match(r'^\|[\s\-:|]+\|$', stripped):
                        continue
                    cells = [c.strip().strip("*") for c in stripped.split("|")[1:-1]]
                    if cells and cells[0] in hdrs:
                        continue
                    data_lines.append(line)
                accumulated += "\n" + "\n".join(data_lines)
            else:
                accumulated = result

            # Judge review
            if round_num >= max_judge_rounds:
                self.log(f"    已达Judge上限({max_judge_rounds}轮)，跳过Judge直接通过")
                break

            judge_result = judge_single(layer, context, accumulated)
            write_judge_report(self._slug(self.industry), layer, round_num, judge_result, None)

            score = judge_result.get("score", 0)
            missing = judge_result.get("missing_items", [])
            critical = judge_result.get("critical_issues", [])
            fatal = [c for c in critical if c.get("severity") == "致命"]
            self.log(f"    Judge评分: {score}")

            # Fatal critical issues always override score — force another round
            if fatal:
                consecutive_failures += 1
                fatal_summary = [f"[{c.get('dimension','')}]{c.get('issue','')[:40]}" for c in fatal]
                self.log(f"    ⚠ 发现{len(fatal)}个致命问题，强制修正: {fatal_summary}")
                context["critical_issues"] = fatal
                context["missing_items"] = missing
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.log(f"    连续{MAX_CONSECUTIVE_FAILURES}轮未通过，记录当前结果继续")
                    break
            # High score + no missing + no fatal → skip consolidation entirely
            elif score >= 8.0 and not missing:
                self.log(f"    高分通过 (score={score})，跳过整合直接定稿")
                context.pop("critical_issues", None)
                skip_consolidation = True
                break
            elif score >= MIN_PASS_SCORE and not missing:
                self.log(f"    扩充阶段通过 (score={score}，无缺失项)")
                context.pop("critical_issues", None)
                break
            elif score >= MIN_PASS_SCORE and missing:
                self.log(f"    评分达标但有缺失项: {missing[:3]}... 继续补充")
                context["missing_items"] = missing
            else:
                consecutive_failures += 1
                self.log(f"    评分不达标 (score={score})，需要补充")
                context["missing_items"] = missing
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.log(f"    连续{MAX_CONSECUTIVE_FAILURES}轮未通过，记录当前结果继续")
                    break

        # Phase B: Consolidation (skip if already high-quality)
        if skip_consolidation:
            self.log(f"  阶段B: 跳过整合(高分定稿)")
            final = accumulated
        else:
            self.log(f"  阶段B: 整合 - {layer}")
            final = self._consolidate(layer, context, accumulated)

        # Phase C: Kimi standard verification (fault layer only)
        # Eliminates '待核实', upgrades '经验值' where possible, validates '标准值' claims
        if layer == "fault":
            self.log(f"  阶段C: Kimi标准核查 - D5置信升级")
            from agents.standard_checker import run_standard_checker
            final, checker_stats = run_standard_checker(context, final)
            if checker_stats["status"] == "parse_error":
                self.log(f"    Kimi响应解析失败，跳过本次核查")
            elif checker_stats["applied"] > 0:
                self.log(f"    Kimi核查完成: {checker_stats['summary']}")
            else:
                self.log(f"    Kimi核查完成: D5标注无需修改")

            # Post-Phase-C safety net: convert residual 待核实/unknown → 经验值-未核实
            _residual = final.count("置信：待核实")
            _unknown = final.count("置信：unknown")
            _total_fallback = _residual + _unknown
            if _total_fallback > 0:
                # Write audit trail
                import json as _json
                from datetime import datetime as _dt
                _audit_dir = os.path.join(REPORTS_DIR, "d5_fallback_audit")
                os.makedirs(_audit_dir, exist_ok=True)
                _safe_eq = context.get("equipment", "unknown").replace("/", "_")
                _safe_comp = context.get("component", "unknown").replace("/", "_")
                _audit_path = os.path.join(_audit_dir, f"{_safe_eq}_{_safe_comp}.json")
                _audit_entry = {
                    "timestamp": _dt.now().isoformat(),
                    "context": {k: context.get(k) for k in ("industry", "sub_industry", "equipment", "component")},
                    "residual_pending": _residual,
                    "kimi_unknown": _unknown,
                    "fallback_label": "经验值-未核实",
                }
                with open(_audit_path, "w", encoding="utf-8") as _af:
                    _json.dump(_audit_entry, _af, ensure_ascii=False, indent=2)
                self.log(f"    Post-Phase-C清扫: 残留{_residual}条待核实 + {_unknown}条unknown → 标记为经验值-未核实")
                self.log(f"    审计文件: {_audit_path}")
                final = final.replace("置信：待核实", "置信：经验值-未核实")
                final = final.replace("置信：unknown", "置信：经验值-未核实")

        has_subs, sub_list = self._extract_sub_industries(final) if layer == "sub_industry" else (False, [])

        return final, has_subs, sub_list

    # ── Sub-industry index builder (seeded mode) ──

    def _build_sub_industry_index(self, sub_list: list[str]) -> str:
        from agents.base import call_llm
        subs_text = "、".join(sub_list)
        prompt = f"""以下是用户提供的【{self.industry}】行业子行业划分：
{subs_text}

请你基于专业判断，评估这份子行业划分是否合理、是否有遗漏。如果有遗漏，请补充。

要求：
1. 尊重用户提供的子行业，不要删除或合并
2. 如果有遗漏可以补充，但如果用户划分已经足够则不要强行添加
3. 输出严格为Markdown表格，两列
4. 表格前后不允许添加任何解释性文字
5. 不允许添加额外列

输出格式（严格两列）：
| 子行业名称 | 描述 |
"""
        result = call_llm("main", "你是行业专家，负责审核和补充子行业划分。输出严格为Markdown表格。", prompt, temperature=0.2)
        write_report(self._slug(self.industry), "phase1_sub_industry_seeded", result)
        return result

    # ── Consolidation ──

    def _consolidate(self, layer: str, context: dict, raw_data: str) -> str:
        from agents.base import call_llm

        format_rules = {
            "sub_industry": "输出严格为两列Markdown表格：| 子行业名称 | 描述 |",
            "equipment": "输出严格为三列Markdown表格：| 设备名称 | 设备类型 | 描述 |",
            "sub_equipment": "输出严格为两列Markdown表格：| 子设备名称 | 描述 |",
            "component": '输出严格为六列Markdown表格：| 部件名称 | 父部件 | 描述 | 易损标识 | 维护方法 | 报废方法 |。维护方法和报废方法仅叶节点部件需填写，非叶节点填"—"。',
            "fault": '输出严格为11列Markdown表格（含故障名称+D1-D9+D10）：| 故障名称 | D1 故障类别 | D2 故障等级 | D3 故障描述与机理 | D4 故障征兆 | D5 故障特征参数 | D6 监测与检测手段 | D7 诊断方法 | D8 检修方法 | D9 预防措施 | D10 易混淆故障 |。第一列必须是故障名称，最后一列为D10易混淆故障（无则填"—"），不允许使用###标题或列表格式。D8检修方法需按"根本处理：xxx；临时处理：xxx"组织。',
        }
        format_rule = format_rules.get(layer, "保持原有Markdown格式")

        # 构建中文上下文描述
        layer_cn = {"sub_industry": "子行业划分", "equipment": "设备清单",
                    "sub_equipment": "子设备分类", "component": "部件拆解",
                    "fault": "故障知识"}.get(layer, layer)
        ctx_parts = [context.get("industry", "")]
        if context.get("sub_industry"):
            ctx_parts.append(context["sub_industry"])
        if context.get("equipment"):
            ctx_parts.append(context["equipment"])
        if context.get("sub_equipment"):
            ctx_parts.append(context["sub_equipment"])
        if context.get("component"):
            ctx_parts.append(context["component"])
        ctx_str = " - ".join(p for p in ctx_parts if p)

        prompt = f"""请对【{ctx_str}】的{layer_cn}调研数据进行整合精炼：
1. 去除重复或表述重合的条目
2. 统一命名和分类方式
3. 确保粒度一致
4. 保留所有有效信息，不要删减内容
5. {format_rule}
6. 表格前后不允许添加任何解释性文字
7. 不允许添加额外列

原始数据：
{raw_data}

请输出整合后的结果（仅输出表格）。"""
        return call_llm("flash", "你是知识库整合智能体，负责去重、统一表述、调整粒度。仅输出表格，不加解释。", prompt, temperature=0.2)

    # ── Sub-equipment need detection ──

    def _identify_sub_equipment_needs(self, sub_industry: str, equip_data: str) -> list[str]:
        from agents.base import call_llm
        prompt = f"""以下是【{self.industry}-{sub_industry}】的设备清单：

{equip_data}

请判断哪些设备是大类设备，需要进一步拆分为子设备。

严格判断标准（必须同时满足以下所有条件才算需要拆分）：
1. 该设备是**主设备**类型（辅助设备和公用系统不需要拆分）
2. 该设备在行业中有**3种以上完全不同的技术路线或结构形式**
3. 不同技术路线之间在**故障特征、监测方式、检修方法**上有根本性差异
4. 拆分后每个子设备都能独立写出至少10个不同的故障类型

明确不需要拆分的例子：
- 磨煤机：虽然有中速磨、钢球磨等，但故障模式高度相似 → 不拆
- 送风机/引风机：只有动调/静调的区别，故障模式相同 → 不拆
- 变压器：不同容量但技术原理完全相同 → 不拆

可能需要拆分的例子：
- 锅炉：煤粉炉、CFB、余热锅炉在燃烧方式、受热面布置、故障模式上完全不同 → 拆
- 汽轮机：冲动式/反动式、凝汽式/背压式/抽汽式有显著差异 → 可拆

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"needs_split": ["设备名1"], "reason": {{"设备名1": "拆分理由（列出3+种技术路线及其核心差异）"}}}}

注意：needs_split列表通常只有0-3个设备。宁可漏判也不要过度拆分。"""
        raw = call_llm("main", "你是设备分类专家，严格判断哪些设备需要子设备拆分。宁缺毋滥。", prompt, temperature=0.1)
        cleaned = re.sub(r'```json\s*', '', raw)
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        try:
            result = json.loads(cleaned)
            needs = result.get("needs_split", [])
            if needs:
                self.log(f"    需要{len(needs)}个子设备拆分: {needs}")
            return needs
        except json.JSONDecodeError:
            self.log(f"    子设备判断解析失败，跳过")
            return []

    # ── Sub-industry extraction (for auto-researched mode) ──

    def _extract_sub_industries(self, data: str) -> tuple:
        from agents.base import call_llm
        prompt = f"""基于以下子行业调研结果，请：
1. 判断该行业是否需要子行业划分（回答"是"或"否"及理由）
2. 如果需要，列出最终确定的子行业名称列表

调研结果：
{data}

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"needs_sub_industry": true或false, "sub_industries": ["子行业1", "子行业2", ...], "reason": "判断理由"}}"""
        raw = call_llm("flash", "你是架构决策智能体。", prompt, temperature=0.1)
        cleaned = re.sub(r'```json\s*', '', raw)
        cleaned = re.sub(r'```\s*', '', cleaned).strip()
        try:
            result = json.loads(cleaned)
            return result.get("needs_sub_industry", False), result.get("sub_industries", [])
        except json.JSONDecodeError:
            return False, []
