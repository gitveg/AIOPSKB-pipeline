import os
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import DATA_DIR, REPORTS_DIR, MIN_PASS_SCORE, MAX_CONSECUTIVE_FAILURES, INDUSTRY_CODES, ENABLE_PHASE_C
from agents.collector import collect_layer
from agents.judge import judge_layer, judge_single
from reports import write_report, write_judge_report
from file_manager import write_kb_file, read_kb_file, ensure_data_dir
from slug_utils import slug_industry, slug_sub, slug_eq


# ── Format detection utility (shared by scripts) ──

def is_new_format(directory: str) -> bool:
    """检测目录是否使用新的三层结构（子系统→部件→零件）。

    判据：该目录下存在 sub_system.md 文件。
    此函数供 orchestrator、validate_kb、md_to_json、json_to_csv、
    track_progress、rerun_d5 等模块共同导入使用。
    """
    return os.path.exists(os.path.join(directory, "sub_system.md"))


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
        return slug_industry(name)

    def _slug_sub(self, name: str) -> str:
        return slug_sub(name)

    def _slug_eq(self, name: str) -> str:
        return slug_eq(name)

    def _sub_dir(self, sub: str) -> str:
        """子行业目录路径。sub=None（无子行业，如石化）时返回 data_dir 本身。"""
        if sub is None:
            return self.data_dir
        return os.path.join(self.data_dir, self._slug_sub(sub))

    def _sub_report_slug(self, sub: str) -> str:
        """report 文件名用的子行业 slug。sub=None 时用行业 slug，避免渲染 None。"""
        return self._slug(self.industry) if sub is None else self._slug_sub(sub)

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
                if name and name not in ("设备类型名称", "设备名称", "设备代码", ":---"):
                    if with_types and len(cells) >= 2:
                        etype = cells[1].strip()
                        equips.append((name, etype))
                    else:
                        equips.append(name)
        return equips

    def _read_component_list(self, equip_dir: str) -> list[str]:
        """从 components.md 读取全部部件/零件列表。
        新格式：返回所有部件名 + 零件名（去重）。
        旧格式：叶节点优先，父节点在后。"""
        path = os.path.join(equip_dir, "components.md")
        content = read_kb_file(path)
        if not content:
            return []

        # 检测格式：新格式第二列为"零件"，旧格式第二列为"父部件"
        is_new = False
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 2 and cells[0].strip("*").strip() == "部件":
                    is_new = True
                break

        if is_new:
            return self._read_component_list_new(content)
        else:
            return self._read_component_list_old(content)

    def _read_component_list_old(self, content: str) -> list[str]:
        """旧格式：| 部件名称 | 父部件 | ... （叶节点优先，父节点在后）"""
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

        leaves = [n for n in all_names if n not in parent_names]
        parents = [n for n in all_names if n in parent_names]
        return leaves + parents

    def _read_component_list_new(self, content: str) -> list[str]:
        """新格式：| 部件 | 零件 | ... （返回所有唯一的部件名+零件名）"""
        names = []
        seen = set()
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|") or re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                comp = cells[0].strip("*").strip()
                part = cells[1].strip()
                if comp and comp not in ("部件",) and comp not in seen:
                    names.append(comp)
                    seen.add(comp)
                if part and part not in ("—", "-", "") and part not in seen:
                    names.append(part)
                    seen.add(part)
        return names

    def _get_children(self, equip_dir: str, comp_name: str) -> list[str]:
        """获取某部件的子项列表。
        新格式：查找零件列中属于该部件的所有零件。
        旧格式：查找父部件列中等于该部件名的所有子部件。"""
        path = os.path.join(equip_dir, "components.md")
        content = read_kb_file(path)
        if not content:
            return []

        # 检测格式
        is_new = False
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', line):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 2 and cells[0].strip("*").strip() == "部件":
                    is_new = True
                break

        children = []
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|") or re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                name = cells[0].strip("*").strip()
                second = cells[1].strip()
                if name in ("部件名称", "部件"):
                    continue
                if is_new:
                    # 新格式：部件=comp_name 且 零件≠"—"
                    if name == comp_name and second not in ("—", "-", ""):
                        children.append(second)
                else:
                    # 旧格式：父部件=comp_name
                    if second == comp_name:
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

    # ── Sub-system helpers (new format) ──

    def _read_sub_system_list(self, base_dir: str) -> list[tuple[str, str]]:
        """读取 sub_system.md，返回 [(子系统名称, 描述), ...]。
        无 sub_system.md 时返回空列表。"""
        path = os.path.join(base_dir, "sub_system.md")
        if not os.path.exists(path):
            return []
        content = read_kb_file(path)
        if not content:
            return []
        result = []
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
            if cells and cells[0] not in ("子系统名称", ""):
                name = cells[0]
                desc = cells[1] if len(cells) > 1 else ""
                result.append((name, desc))
        return result

    def _parse_new_components(self, comp_path: str) -> dict:
        """解析新格式 components.md (| 部件 | 零件 | ...)，返回结构化数据。
        返回: {comp_name: {"desc", "consumable", "maint", "disposal", "parts": [str]}}
        """
        content = read_kb_file(comp_path)
        if not content:
            return {}
        components = {}
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                continue
            if re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 6:
                continue
            comp_name = cells[0].strip("*").strip()
            part_name = cells[1].strip()
            if comp_name in ("部件", ""):
                continue
            desc = cells[2] if len(cells) > 2 else ""
            consumable = cells[3] if len(cells) > 3 else "否"
            maint = cells[4] if len(cells) > 4 else "—"
            disposal = cells[5] if len(cells) > 5 else "—"
            if comp_name not in components:
                components[comp_name] = {
                    "desc": "", "consumable": "否",
                    "maint": "—", "disposal": "—", "parts": [],
                }
            if part_name in ("—", "-", ""):
                # Component standalone row
                components[comp_name]["desc"] = desc
                components[comp_name]["consumable"] = consumable
                components[comp_name]["maint"] = maint
                components[comp_name]["disposal"] = disposal
            else:
                # Part row
                components[comp_name]["parts"].append(part_name)
        return components

    @staticmethod
    def _extract_part_names(content: str) -> list[str]:
        """从新格式 components.md 内容中提取所有部件名+零件名（去重，保持顺序）。
        跳过表头行（第一列="部件"）和分隔行。"""
        _HEADER_NAMES = {"部件", "零件", "描述", "易损标识", "维护方法", "报废方法"}
        names = []
        seen = set()
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|") or re.match(r'^\|[\s\-:|]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 2:
                continue
            comp = cells[0].strip("*").strip()
            # 跳过表头行（第一列为"部件"）
            if comp in _HEADER_NAMES:
                continue
            part = cells[1].strip()
            if comp and comp not in seen:
                names.append(comp)
                seen.add(comp)
            if part and part not in ("—", "-", "") and part not in _HEADER_NAMES and part not in seen:
                names.append(part)
                seen.add(part)
        return names

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
            self.log(f"  处理子行业: {sub or self.industry}")
            sub_dir = self._sub_dir(sub)
            ensure_data_dir(sub_dir)

            equip_result = self._run_layer(
                layer="equipment",
                context={"industry": self.industry, "sub_industry": sub or ""},
                output_path=os.path.join(sub_dir, "equipment_registry.md"),
            )
            equip_data = equip_result[0]
            write_kb_file(os.path.join(sub_dir, "equipment_registry.md"), equip_data)
            write_report(self._slug(self.industry), f"phase2_{self._sub_report_slug(sub)}_equipment", equip_data)

            # Phase 2.5: Sub-equipment split
            sub_equips = self._identify_sub_equipment_needs(sub, equip_data)
            for eq_name in sub_equips:
                self.log(f"  阶段2.5: 子设备拆分 - {eq_name}")
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                ensure_data_dir(eq_dir)

                sub_eq_result = self._run_layer(
                    layer="sub_equipment",
                    context={"industry": self.industry, "sub_industry": sub or "", "equipment": eq_name},
                    output_path=os.path.join(eq_dir, "sub_equipment.md"),
                )
                sub_eq_data = sub_eq_result[0]
                write_kb_file(os.path.join(eq_dir, "sub_equipment.md"), sub_eq_data)
                write_report(self._slug(self.industry),
                             f"phase2.5_{self._sub_report_slug(sub)}_{self._slug_eq(eq_name)}_sub_equip", sub_eq_data)

        self.log(f"===== 阶段2 完成 =====")
        self._write_run_log()

    # ── Phase 3: Component（子系统→部件→零件 三级结构）──

    def run_component(self, sub_filter: str = None, equip_filter: str = None,
                      equip_type: str = None, sub_eq_filter: str = None):
        self.log(f"===== 阶段3: 部件拆解 - {self.industry} =====")
        if equip_type:
            self.log(f"  设备属性筛选: {equip_type}")

        sub_list = self._get_sub_list(sub_filter)
        for sub in sub_list:
            sub_dir = self._sub_dir(sub)
            equip_list = self._get_equip_list(sub_dir, equip_filter, equip_type)

            for eq_name in equip_list:
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                ensure_data_dir(eq_dir)

                sub_eq_names = self._read_sub_equipment_names(eq_dir)
                if sub_eq_filter:
                    sub_eq_names = [n for n in sub_eq_names if n == sub_eq_filter]

                if sub_eq_names:
                    # 有子设备：逐个子设备处理
                    for sub_eq_name in sub_eq_names:
                        sub_eq_dirname = self._sanitize_sub_eq_name(sub_eq_name)
                        sub_eq_dir = os.path.join(eq_dir, sub_eq_dirname)
                        ensure_data_dir(sub_eq_dir)
                        self._run_component_three_level(sub_eq_dir, sub, eq_name, sub_eq_name)
                else:
                    # 无子设备：直接在设备目录下
                    self._run_component_three_level(eq_dir, sub, eq_name, "")

        self.log(f"===== 阶段3 完成 =====")
        self._write_run_log()

    def _run_component_three_level(self, base_dir: str, sub: str,
                                    eq_name: str, sub_eq_name: str):
        """Phase 3.1 生成 sub_system.md + Phase 3.2 逐子系统生成 components.md"""
        """新格式：Phase 3.1 生成 sub_system.md + Phase 3.2 逐子系统生成 components.md"""
        context_base = {"industry": self.industry, "sub_industry": sub or "",
                        "equipment": eq_name}
        if sub_eq_name:
            context_base["sub_equipment"] = sub_eq_name

        # ── Phase 3.1: 生成 sub_system.md ──
        ss_path = os.path.join(base_dir, "sub_system.md")
        if os.path.exists(ss_path):
            existing = read_kb_file(ss_path)
            if existing and existing.strip():
                self.log(f"  Phase 3.1 跳过(已有数据): {sub or self.industry} - {eq_name}"
                         + (f" - {sub_eq_name}" if sub_eq_name else ""))
            else:
                self._generate_sub_system(ss_path, context_base, sub, eq_name, sub_eq_name)
        else:
            self._generate_sub_system(ss_path, context_base, sub, eq_name, sub_eq_name)

        # ── Phase 3.2: 逐子系统生成 components.md（带MECE去重）──
        sub_systems = self._read_sub_system_list(base_dir)
        if not sub_systems:
            self.log(f"  Phase 3.2: 无子系统数据，跳过")
            return

        claimed = []  # 累积已认领的部件/零件名称
        for ss_name, ss_desc in sub_systems:
            ss_dir = os.path.join(base_dir, ss_name)
            comp_path = os.path.join(ss_dir, "components.md")

            # 断点续跑：已有 components.md 的子系统跳过生成，但仍需解析并入 claimed
            if os.path.exists(comp_path):
                existing = read_kb_file(comp_path)
                if existing and existing.strip():
                    existing_names = self._extract_part_names(existing)
                    claimed.extend(existing_names)
                    self.log(f"  Phase 3.2 跳过(已有数据): {ss_name} (已提取 {len(existing_names)} 个已认领名称)")
                    continue

            self.log(f"  Phase 3.2: 生成子系统 [{ss_name}] 的部件+零件 (已避让 {len(claimed)} 个已认领名称)")
            ensure_data_dir(ss_dir)

            comp_result = self._run_layer(
                layer="component",
                context={**context_base,
                         "sub_system": ss_name, "sub_system_desc": ss_desc,
                         "all_sub_systems": sub_systems,
                         "claimed_parts": claimed},
                output_path=comp_path,
            )
            comp_data = comp_result[0]
            write_kb_file(comp_path, comp_data)
            write_report(self._slug(self.industry),
                         f"phase3.2_{self._sub_report_slug(sub)}_{self._slug_eq(eq_name)}_{ss_name}_components",
                         comp_data)

            # 累积本子系统认领的名称
            new_names = self._extract_part_names(comp_data)
            claimed.extend(new_names)

        # ── Phase 3.2 去重仲裁：跨子系统撞名件归属判定 ──
        self._dedup_cross_subsystem(base_dir, sub_systems, sub, eq_name, sub_eq_name)

    def _generate_sub_system(self, ss_path: str, context: dict,
                              sub: str, eq_name: str, sub_eq_name: str):
        """生成 sub_system.md 文件"""
        label = sub_eq_name or eq_name
        self.log(f"  Phase 3.1: 生成子系统清单 - {sub or self.industry} - {label}")
        ss_result = self._run_layer(
            layer="sub_system",
            context=context,
            output_path=ss_path,
        )
        ss_data = ss_result[0]
        write_kb_file(ss_path, ss_data)
        write_report(self._slug(self.industry),
                     f"phase3.1_{self._sub_report_slug(sub)}_{self._slug_eq(eq_name)}"
                     + (f"_{self._sanitize_sub_eq_name(sub_eq_name)}" if sub_eq_name else "")
                     + "_sub_system",
                     ss_data)

    def _dedup_cross_subsystem(self, base_dir: str, sub_systems: list[tuple[str, str]],
                                sub: str, eq_name: str, sub_eq_name: str):
        """Phase 3.2 后处理：跨子系统撞名件归属仲裁。
        扫描所有子系统的 components.md，找出出现在≥2个子系统的部件/零件名，
        调用 LLM 做归属判定，从非 owner 子系统中删除撞名行，输出审计日志。
        """
        from agents.base import call_llm

        # 1. 收集所有子系统中的名称→出现位置映射
        name_locations: dict[str, list[tuple[str, str]]] = {}  # name -> [(ss_name, 层级)]
        ss_contents: dict[str, str] = {}  # ss_name -> components.md raw content
        for ss_name, _ss_desc in sub_systems:
            comp_path = os.path.join(base_dir, ss_name, "components.md")
            content = read_kb_file(comp_path)
            if not content:
                continue
            ss_contents[ss_name] = content
            names_in_ss = self._extract_part_names(content)
            for name in names_in_ss:
                if name not in name_locations:
                    name_locations[name] = []
                name_locations[name].append(ss_name)

        # 2. 找出撞名件（出现在>1个子系统）
        collisions = {name: locs for name, locs in name_locations.items() if len(locs) > 1}
        if not collisions:
            self.log(f"  Phase 3.2 去重仲裁: 无跨子系统撞名，跳过")
            return

        self.log(f"  Phase 3.2 去重仲裁: 发现 {len(collisions)} 个跨子系统撞名件: {list(collisions.keys())}")

        # 3. 逐个撞名件做 LLM 归属判定
        ss_desc_map = dict(sub_systems)
        arbitration_log = []
        for dup_name, dup_ss_list in collisions.items():
            # 收集该件在各子系统的描述（用于判定）
            descs = []
            for ss_name in dup_ss_list:
                content = ss_contents.get(ss_name, "")
                # 找到该名称所在的行，提取描述
                for line in content.split("\n"):
                    line = line.strip()
                    if not line.startswith("|") or re.match(r'^\|[\s\-:|]+\|$', line):
                        continue
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if len(cells) >= 3 and cells[0].strip("*").strip() == dup_name:
                        descs.append(f"子系统「{ss_name}」({ss_desc_map.get(ss_name, '')[:40]}): {cells[2][:60]}")
                        break
                    if len(cells) >= 3 and cells[1].strip() == dup_name:
                        descs.append(f"子系统「{ss_name}」({ss_desc_map.get(ss_name, '')[:40]}): 零件-{cells[2][:40]}")
                        break

            descs_text = "\n".join(descs)
            prompt = f"""以下是设备「{eq_name}」的部件/零件「{dup_name}」在多个子系统中出现的情况：

{descs_text}

请判断该件应归属哪个子系统（依据：该件「主要服务的功能」所在的子系统）。
只需返回一个子系统名称，不要解释。

选项：{', '.join(dup_ss_list)}"""

            owner = call_llm("flash", "你是设备功能分解专家。", prompt, temperature=0.0).strip()
            # 清理可能的引号/多余文字
            owner = owner.strip('"\'""''')
            # 如果返回的不在候选列表中，默认取第一个
            if owner not in dup_ss_list:
                owner = dup_ss_list[0]

            arbitration_log.append(f"- 「{dup_name}」: 出现在 {', '.join(dup_ss_list)} → 归属「{owner}」")
            self.log(f"    撞名仲裁: 「{dup_name}」→ 归属「{owner}」")

            # 4. 从非 owner 子系统删除该撞名件对应行
            _HEADER_NAMES = {"部件", "零件", "描述", "易损标识", "维护方法", "报废方法",
                             "部件名称", "父部件"}
            for ss_name in dup_ss_list:
                if ss_name == owner:
                    continue
                comp_path = os.path.join(base_dir, ss_name, "components.md")
                content = read_kb_file(comp_path)
                if not content:
                    continue
                new_lines = []
                removed = 0
                for line in content.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("|") and not re.match(r'^\|[\s\-:|]+\|$', stripped):
                        cells = [c.strip() for c in stripped.split("|")[1:-1]]
                        if len(cells) >= 2:
                            # 跳过表头行
                            if cells[0].strip("*").strip() in _HEADER_NAMES:
                                new_lines.append(line)
                                continue
                            comp = cells[0].strip("*").strip()
                            part = cells[1].strip()
                            if comp == dup_name or part == dup_name:
                                removed += 1
                                continue
                    new_lines.append(line)
                if removed > 0:
                    write_kb_file(comp_path, "\n".join(new_lines))
                    self.log(f"    从「{ss_name}」移除 {removed} 行含「{dup_name}」")

        # 5. 输出审计日志
        log_path = os.path.join(REPORTS_DIR, self._slug(self.industry),
                                f"phase3.2_dedup_{self._slug_eq(eq_name)}"
                                + (f"_{self._sanitize_sub_eq_name(sub_eq_name)}" if sub_eq_name else "")
                                + ".md")
        ensure_data_dir(os.path.dirname(log_path))
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Phase 3.2 跨子系统去重仲裁日志\n")
            f.write(f"> 设备: {eq_name}")
            if sub_eq_name:
                f.write(f" / 子设备: {sub_eq_name}")
            f.write(f"\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"## 撞名件 ({len(collisions)}个)\n\n")
            for entry in arbitration_log:
                f.write(entry + "\n")
        self.log(f"  去重仲裁日志已保存: {log_path}")

    # ── Phase 4: Fault ──

    def run_fault(self, sub_filter: str = None, equip_filter: str = None,
                  comp_filter: str = None, equip_type: str = None,
                  force: bool = False, workers: int = 1, sub_eq_filter: str = None):
        self.log(f"===== 阶段4: 故障知识 - {self.industry} (workers={workers}) =====")

        # Phase 1: Collect all tasks
        tasks = []
        sub_list = self._get_sub_list(sub_filter)
        for sub in sub_list:
            sub_dir = self._sub_dir(sub)
            equip_list = self._get_equip_list(sub_dir, equip_filter, equip_type)

            for eq_name in equip_list:
                eq_dir = os.path.join(sub_dir, self._slug_eq(eq_name))
                sub_eq_names = self._read_sub_equipment_names(eq_dir)
                if sub_eq_filter:
                    sub_eq_names = [n for n in sub_eq_names if n == sub_eq_filter]

                if sub_eq_names:
                    for sub_eq_name in sub_eq_names:
                        sub_eq_dirname = self._sanitize_sub_eq_name(sub_eq_name)
                        sub_eq_dir = os.path.join(eq_dir, sub_eq_dirname)
                        if not os.path.isdir(sub_eq_dir):
                            continue
                        self._collect_fault_tasks(tasks, sub_eq_dir, sub,
                                                  eq_name, sub_eq_name, force)
                else:
                    self._collect_fault_tasks(tasks, eq_dir, sub,
                                              eq_name, "", force)

        # 应用 comp_filter（部件/零件名过滤，支持 fault 阶段单部件/零件生成）
        if comp_filter:
            before = len(tasks)
            tasks = [t for t in tasks if t["comp_name"] == comp_filter]
            self.log(f"  comp_filter='{comp_filter}'：{before} → {len(tasks)} 个任务")

        total = len(tasks)
        self.log(f"  共 {total} 个部件/零件待处理")
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

    def _collect_fault_tasks(self, tasks: list, base_dir: str, sub: str,
                              eq_name: str, sub_eq_name: str, force: bool):
        """从子系统目录遍历 部件/零件 的 faults/ 收集故障生成任务"""
        sub_systems = self._read_sub_system_list(base_dir)
        for ss_name, _ss_desc in sub_systems:
            ss_dir = os.path.join(base_dir, ss_name)
            comp_path = os.path.join(ss_dir, "components.md")
            if not os.path.exists(comp_path):
                continue

            components = self._parse_new_components(comp_path)
            for comp_name, comp_info in components.items():
                parts = comp_info.get("parts", [])

                # 部件级故障（总成级失效）
                comp_dir = os.path.join(ss_dir, comp_name)
                faults_dir = os.path.join(comp_dir, "faults")
                ensure_data_dir(faults_dir)
                safe_comp = comp_name.replace("/", "／")
                fault_path = os.path.join(faults_dir, f"{safe_comp}.md")

                if not (not force and os.path.exists(fault_path) and read_kb_file(fault_path).strip()):
                    tasks.append({
                        "sub": sub, "eq_name": eq_name,
                        "sub_equipment": sub_eq_name,
                        "comp_name": comp_name,
                        "safe_comp": safe_comp, "fault_path": fault_path,
                        "context": {"industry": self.industry, "sub_industry": sub or "",
                                    "equipment": eq_name, "component": comp_name,
                                    "children": parts, "sub_equipment": sub_eq_name,
                                    "sub_system": ss_name},
                    })

                # 零件级故障（具体失效）
                for part_name in parts:
                    part_dir = os.path.join(ss_dir, part_name)
                    faults_dir = os.path.join(part_dir, "faults")
                    ensure_data_dir(faults_dir)
                    safe_part = part_name.replace("/", "／")
                    fault_path = os.path.join(faults_dir, f"{safe_part}.md")

                    if not (not force and os.path.exists(fault_path) and read_kb_file(fault_path).strip()):
                        tasks.append({
                            "sub": sub, "eq_name": eq_name,
                            "sub_equipment": sub_eq_name,
                            "comp_name": part_name,
                            "safe_comp": safe_part, "fault_path": fault_path,
                            "context": {"industry": self.industry, "sub_industry": sub or "",
                                        "equipment": eq_name, "component": part_name,
                                        "children": [], "sub_equipment": sub_eq_name,
                                        "sub_system": ss_name,
                                        "parent_component": comp_name},
                        })

    def _process_fault_component(self, task: dict, idx: int, total: int):
        """Process a single fault component through Phase A→B→C. Thread-safe."""
        sub = task["sub"]
        eq_name = task["eq_name"]
        comp_name = task["comp_name"]
        fault_path = task["fault_path"]
        ctx = task["context"]
        safe_comp = task["safe_comp"]

        self.log(f"  [{idx}/{total}] 处理部件: {sub or self.industry} - {eq_name} - {comp_name}")

        fault_result = self._run_layer(layer="fault", context=ctx, output_path=fault_path)
        fault_data = fault_result[0]
        write_kb_file(fault_path, fault_data)
        write_report(self._slug(self.industry),
                     f"phase4_{self._sub_report_slug(sub)}_{self._slug_eq(eq_name)}_{safe_comp}_faults",
                     fault_data)

        with self._progress_lock:
            self._progress_done += 1
            done = self._progress_done
        self.log(f"  [{done}/{total}] 完成: {sub or self.industry} - {eq_name} - {comp_name}")

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
            "D1 物理属性": "D1",
            "D1 故障类别": "D1",  # backward compat
            "故障类别": "故障类别", "D2 故障等级": "D2",
            "D3 故障描述与机理": "D3", "D4 故障征兆": "D4",
            "D5 故障特征参数": "D5", "D6 监测与检测手段": "D6",
            "D7 诊断方法": "D7", "D8 检修方法": "D8",
            "D9 预防措施": "D9", "D10 易混淆故障": "D10",
            # 改造6新增检维修5列（表头列名→短key D11-D15）
            "D11 用工需求": "D11", "D12 工机具": "D12",
            "D13 备件用料": "D13", "D14 安全注意事项": "D14",
            "D15 验收标准": "D15",
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
            ("故障类别", "故障类别"),
            ("D1", "D1 物理属性"),
            ("D2", "D2 故障等级"),
            ("D3", "D3 故障描述与机理"),
            ("D4", "D4 故障征兆"),
            ("D5", "D5 故障特征参数"),
            ("D6", "D6 监测与检测手段"),
            ("D7", "D7 诊断方法"),
            ("D8", "D8 检修方法"),
            ("D9", "D9 预防措施"),
            ("D10", "D10 易混淆故障"),
            # 改造6新增检维修5列（D11-D15）
            ("D11", "D11 用工需求"),
            ("D12", "D12 工机具"),
            ("D13", "D13 备件用料"),
            ("D14", "D14 安全注意事项"),
            ("D15", "D15 验收标准"),
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
            # 无子行业行业（如石化）：registry 直接在行业目录，设备展开在 data_dir 下
            if os.path.exists(os.path.join(self.data_dir, "equipment_registry.md")):
                self.log(f"  {self.industry} 无子行业，设备直接展开在行业目录")
                return [None]
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
                self.log(f"  设备属性 '{equip_type}' 下无匹配设备")
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
                _hdrs = {"sub_industry": {"子行业名称"}, "equipment": {"设备类型名称", "设备名称"},
                         "sub_equipment": {"子设备名称"}, "sub_system": {"子系统名称"},
                         "component": {"部件名称", "部件"},
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

        # Phase C: 标准核查（异模型对D5置信二次核查），受 ENABLE_PHASE_C 开关控制
        if layer == "fault" and ENABLE_PHASE_C:
            self.log(f"  阶段C: 标准核查 - D5置信升级")
            from agents.standard_checker import run_standard_checker
            final, checker_stats = run_standard_checker(context, final)
            if checker_stats["status"] == "parse_error":
                self.log(f"    核查响应解析失败，跳过本次核查")
            elif checker_stats["applied"] > 0:
                self.log(f"    核查完成: {checker_stats['summary']}")
            else:
                self.log(f"    核查完成: D5标注无需修改")

        if layer == "fault":
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

        # 根据格式选择 component 规则
        has_sub_system = context.get("sub_system", "")
        if layer == "component" and has_sub_system:
            comp_rule = ('输出严格为六列Markdown表格：| 部件 | 零件 | 描述 | 易损标识 | 维护方法 | 报废方法 |。'
                         '维护方法和报废方法仅在部件行（零件列="—"）填写，零件行这两列填"—"（维护/报废上挂部件层）。'
                         '每个部件必须有一行零件列="—"的独立行。')
        else:
            comp_rule = '输出严格为六列Markdown表格：| 部件名称 | 父部件 | 描述 | 易损标识 | 维护方法 | 报废方法 |。维护方法和报废方法仅叶节点部件需填写，非叶节点填"—"。'

        format_rules = {
            "sub_industry": "输出严格为两列Markdown表格：| 子行业名称 | 描述 |",
            "equipment": "输出严格为三列Markdown表格：| 设备类型名称 | 设备属性 | 描述 |",
            "sub_equipment": "输出严格为两列Markdown表格：| 子设备名称 | 描述 |",
            "sub_system": "输出严格为两列Markdown表格：| 子系统名称 | 描述 |。每个子系统描述50-100字，说明功能范围和覆盖边界。",
            "component": comp_rule,
            "fault": '输出严格为17列Markdown表格（含故障名称+故障类别+D1-D15）：| 故障名称 | 故障类别 | D1 物理属性 | D2 故障等级 | D3 故障描述与机理 | D4 故障征兆 | D5 故障特征参数 | D6 监测与检测手段 | D7 诊断方法 | D8 检修方法 | D9 预防措施 | D10 易混淆故障 | D11 用工需求 | D12 工机具 | D13 备件用料 | D14 安全注意事项 | D15 验收标准 |。故障类别列的值必须从注入的枚举中选择，禁止自创。检维修5列（D11用工需求/D12工机具/D13备件用料/D14安全注意事项/D15验收标准）每列内容末尾必须标注置信级别（标准值/经验值/待核实），安全注意事项、验收标准鼓励标"标准值"并带标准号。第一列必须是故障名称，最后一列为D15验收标准，不允许使用###标题或列表格式。D8检修方法需按"根本处理：xxx；临时处理：xxx"组织。',
        }
        format_rule = format_rules.get(layer, "保持原有Markdown格式")

        # 构建中文上下文描述
        layer_cn = {"sub_industry": "子行业划分", "equipment": "设备清单",
                    "sub_equipment": "子设备分类", "sub_system": "子系统拆分",
                    "component": "部件拆解",
                    "fault": "故障知识"}.get(layer, layer)
        ctx_parts = [context.get("industry", "")]
        if context.get("sub_industry"):
            ctx_parts.append(context["sub_industry"])
        if context.get("equipment"):
            ctx_parts.append(context["equipment"])
        if context.get("sub_equipment"):
            ctx_parts.append(context["sub_equipment"])
        if context.get("sub_system"):
            ctx_parts.append(context["sub_system"])
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
