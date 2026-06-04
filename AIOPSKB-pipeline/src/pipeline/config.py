import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# LLM configs
CHAT_API_KEY = os.getenv("CHAT_API_KEY", "").strip('"')
CHAT_BASE_URL = os.getenv("CHAT_BASE_URL", "").strip('"')
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip('"')
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "DeepSeek-V4-Pro")
DEEPSEEK_MODEL_FLASH = os.getenv("DEEPSEEK_MODEL_FLASH", "deepseek-v4-flash")

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "").strip('"')
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.6")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip('"')

# Agent model assignments per construct_guide
AGENT_MODELS = {
    "main": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_BASE_URL, "model": DEEPSEEK_MODEL},
    "collector": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_BASE_URL, "model": DEEPSEEK_MODEL},
    "judge_b": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_BASE_URL, "model": DEEPSEEK_MODEL},
    "reviewer": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_BASE_URL, "model": DEEPSEEK_MODEL},
    "flash": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_BASE_URL, "model": DEEPSEEK_MODEL_FLASH},
    # Kimi as second expert for D5 standard verification (Phase C)
    # Different training data from DeepSeek → complementary standard knowledge
    "kimi_expert": {"api_key": KIMI_API_KEY, "base_url": KIMI_BASE_URL, "model": KIMI_MODEL},
}

# Quality gates
MIN_PASS_SCORE = 7
MAX_CONSECUTIVE_FAILURES = 3

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
REPORTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'reports')

# Industry codes
INDUSTRY_CODES = {
    "电力": "PW", "石化": "PE", "冶金": "MT", "水泥": "CM",
    "煤炭": "CL", "轨道交通": "RT", "制造业": "MF", "航空航天与船舶": "AS",
}

# Sub-industry → classification coding anchor (used by Judge & Collector for cross-referencing)
SUB_INDUSTRY_CODING_ANCHORS = {
    "火电": {"system": "KKS", "standard": "DL/T 5448-2014", "scope": "电站设备分类标识"},
    "水电": {"system": "KKS", "standard": "DL/T 5448-2014", "scope": "电站设备分类标识"},
    "核电": {"system": "KKS", "standard": "DL/T 5448-2014", "scope": "电站设备分类标识"},
    "燃气轮机": {"system": "KKS", "standard": "DL/T 5448-2014", "scope": "电站设备分类标识"},
    "抽水蓄能": {"system": "KKS", "standard": "DL/T 5448-2014", "scope": "电站设备分类标识"},
    "风电": {"system": "RDS-PP", "standard": "IEC 81346-10", "scope": "风电场设备标识"},
    "光伏": {"system": "IEC 62548", "standard": "IEC 62548 + 国内行业实践", "scope": "光伏阵列/汇流箱/逆变器分类"},
    "输电": {"system": "IEC 61850", "standard": "GB/T 50064 + IEC 61850", "scope": "输电设备模型与命名"},
    "变电": {"system": "IEC 61850", "standard": "GB/T 50064 + IEC 61850", "scope": "变电站设备分类与命名"},
    "配电": {"system": "IEC 61850", "standard": "GB/T 50064 + IEC 61850", "scope": "配电设备分类与命名"},
    "储能": {"system": "GB/T 36558", "standard": "GB/T 36558 + IEC 62933", "scope": "储能系统分类（行业规范演化中）"},
}

# Equipment type classification criteria (主设备/辅助设备/公用系统)
EQUIP_TYPE_CRITERIA = [
    {"dimension": "服务对象",
     "主设备": "服务生产主流程本身",
     "辅助设备": "服务某台或某类主设备",
     "公用系统": "服务多个设备、多个系统或全厂"},
    {"dimension": "与能量转换核心的距离",
     "主设备": "直接参与主能量转换",
     "辅助设备": "服务于某台主设备的运行",
     "公用系统": "不绑定单一主设备，服务全厂或多台机组"},
    {"dimension": "故障的设备级影响",
     "主设备": "失效直接导致机组停运",
     "辅助设备": "失效导致对应主设备降负荷或停运",
     "公用系统": "失效影响全厂运行，但不一定停机组"},
    {"dimension": "配置粒度",
     "主设备": "通常按机组一一对应",
     "辅助设备": "通常按主设备配套（1台主设备配N台辅助）",
     "公用系统": "按全厂或集中区域配置（1套服务多机组）"},
]

# D5 Standard reference: parameter domain → applicable standards
# Organized by physical quantity type (not equipment/industry) — cross-industry applicable
D5_STANDARD_REFERENCE = {
    "振动": {
        "params": ["振动速度", "振动加速度", "振动位移", "振动烈度"],
        "standards": [
            ("ISO 10816-3", "旋转机械振动评定——工业机器"),
            ("ISO 20816-1", "旋转机械振动评定——通则（替代ISO 10816全系列）"),
            ("VDI 3834", "风电齿轮箱与主轴承振动评定"),
            ("GB/T 11348", "旋转机械转轴径向振动"),
            ("DL/T 501", "电站设备振动标准"),
        ],
    },
    "温度": {
        "params": ["绕组温度", "轴承温度", "油面温度", "冷却介质温度", "温升"],
        "standards": [
            ("IEC 60034-1", "旋转电机——定额与性能（绝缘等级温升限值）"),
            ("GB/T 7064", "隐极同步发电机技术要求"),
            ("GB/T 11024", "电力变压器温度限值"),
            ("IEC 60076-2", "变压器温升"),
            ("GB/T 1094.2", "电力变压器温升"),
        ],
    },
    "绝缘电阻": {
        "params": ["绝缘电阻", "吸收比", "极化指数", "对地绝缘", "相间绝缘"],
        "standards": [
            ("DL/T 596", "电力设备预防性试验规程（绝缘电阻判据来源）"),
            ("IEC 60076-3", "变压器绝缘水平"),
            ("GB 50150", "电气装置安装工程电气设备交接试验标准"),
            ("GB/T 5582", "高压电力设备外绝缘污秽等级"),
            ("IEEE 43", "Recommended Practice for Testing Insulation Resistance"),
        ],
    },
    "油液清洁度": {
        "params": ["颗粒度", "清洁度等级", "NAS等级", "ISO 4406代码"],
        "standards": [
            ("ISO 4406", "液压传动——油液固体颗粒污染等级代号"),
            ("NAS 1638", "液压系统清洁度等级"),
            ("GB/T 14039", "液压传动——油液固体颗粒污染等级代号"),
        ],
    },
    "油中溶解气体(DGA)": {
        "params": ["H₂", "CH₄", "C₂H₂", "C₂H₄", "C₂H₆", "CO", "CO₂", "总烃", "三比值", "Duval三角"],
        "standards": [
            ("GB/T 7252", "变压器油中溶解气体分析和判断导则"),
            ("IEC 60599", "运行中充油电气设备溶解气体分析"),
            ("DL/T 722", "变压器油中溶解气体分析和判断导则"),
        ],
    },
    "油液理化": {
        "params": ["水分", "酸值(TAN)", "击穿电压", "介质损耗因数tanδ", "界面张力",
                   "运动粘度", "闪点", "密度", "破乳化时间"],
        "standards": [
            ("GB/T 7595", "运行中变压器油质量"),
            ("IEC 60422", "运行中矿物绝缘油维护导则"),
            ("GB/T 7597", "电力用油取样及质量检验"),
            ("GB/T 7598", "运行中变压器油水溶性酸测定法"),
        ],
    },
    "齿轮磨损": {
        "params": ["齿面磨损", "点蚀面积", "胶合", "齿侧间隙", "啮合频率"],
        "standards": [
            ("ISO 1328", "圆柱齿轮——精度等级"),
            ("AGMA 2001", "渐开线圆柱齿轮强度评定"),
            ("ISO 6336", "直齿轮和斜齿轮承载能力计算"),
            ("GB/T 3480", "渐开线圆柱齿轮承载能力计算方法"),
            ("GB/T 10095", "渐开线圆柱齿轮精度"),
        ],
    },
    "滚动轴承": {
        "params": ["轴承游隙", "冲击脉冲dBm", "加速度包络", "滚动体磨损",
                   "保持架损伤", "轴承温度"],
        "standards": [
            ("ISO 281", "滚动轴承——额定动载荷和额定寿命"),
            ("ISO 15243", "滚动轴承——损伤与失效——术语、特征和原因"),
            ("GB/T 24607", "滚动轴承——寿命与可靠性试验"),
            ("GB/T 6391", "滚动轴承——额定动载荷和额定寿命"),
        ],
    },
    "螺栓连接": {
        "params": ["预紧力", "扭矩", "螺栓伸长量", "法兰面间隙", "残余夹紧力"],
        "standards": [
            ("VDI 2230", "高强度螺栓连接系统计算"),
            ("GB/T 16823.2", "螺纹紧固件紧固通则"),
            ("ISO 898-1", "Mechanical properties of fasteners - Bolts/screws/studs"),
            ("DL/T 439", "火力发电厂高温紧固件技术导则"),
            ("DL/T 5210.7", "电力建设施工质量验收规范——焊接与紧固"),
        ],
    },
    "接地": {
        "params": ["接地电阻", "接触电阻", "跨步电压", "接地引下线导通性"],
        "standards": [
            ("GB/T 50065", "交流电气装置的接地设计规范"),
            ("IEEE 80", "交流变电站接地安全导则"),
            ("DL/T 621", "交流电气装置的接地"),
            ("IEC 62305", "雷电防护"),
        ],
    },
    "避雷器": {
        "params": ["直流参考电压(U1mA)", "泄漏电流", "阻性电流", "绝缘电阻"],
        "standards": [
            ("GB/T 11032", "交流无间隙金属氧化物避雷器"),
            ("IEC 60099-4", "交流系统用无间隙金属氧化物避雷器"),
            ("DL/T 815", "交流输电线路用复合外套金属氧化物避雷器"),
        ],
    },
    "局部放电": {
        "params": ["放电量(pC)", "放电起始电压", "放电相位", "PRPD图谱",
                   "超声波局放信号"],
        "standards": [
            ("IEC 60270", "局部放电测量"),
            ("GB/T 7354", "局部放电测量"),
            ("DL/T 846", "高电压测试设备通用技术条件"),
        ],
    },
    "介电性能": {
        "params": ["介质损耗因数tanδ", "电容变化率", "绝缘电容"],
        "standards": [
            ("GB/T 7595", "运行中变压器油质量"),
            ("IEC 60247", "绝缘液体——相对介电常数、介质损耗因数和电阻率测量"),
            ("DL/T 596", "电力设备预防性试验规程"),
        ],
    },
    "直流电阻": {
        "params": ["绕组直流电阻", "触头接触电阻", "接头电阻", "电阻偏差率"],
        "standards": [
            ("DL/T 596", "电力设备预防性试验规程"),
            ("IEC 60076-1", "电力变压器——总则"),
            ("GB/T 1094.1", "电力变压器 第1部分：总则"),
        ],
    },
    "效率/性能": {
        "params": ["效率偏差", "功率因数", "出力", "流量", "扬程", "压比"],
        "standards": [
            ("IEC 60034-2-1", "旋转电机——确定损耗和效率的标准方法"),
            ("GB/T 1032", "三相异步电动机试验方法"),
            ("ISO 5167", "差压装置测量满管流体流量"),
        ],
    },
    "腐蚀/壁厚": {
        "params": ["壁厚减薄率", "腐蚀坑深度", "氧化皮厚度", "蠕变应变"],
        "standards": [
            ("DL/T 438", "火力发电厂金属技术监督规程"),
            ("GB/T 16507", "水管锅炉"),
            ("ASME B31.1", "动力管道"),
            ("DL/T 654", "火电厂超期服役机组寿命评估技术导则"),
        ],
    },
    "水化学": {
        "params": ["pH", "电导率", "溶解氧", "硅酸根", "磷酸根", "钠离子",
                   "铁含量", "铜含量", "氯离子"],
        "standards": [
            ("GB/T 12145", "火力发电机组及蒸汽动力设备水汽质量"),
            ("DL/T 889", "火力发电厂水汽试验方法"),
            ("DL/T 805", "火电厂汽水化学导则"),
            ("DL/T 912", "超临界火力发电机组水汽质量标准"),
        ],
    },
    "安全阀": {
        "params": ["整定压力", "启闭压差", "回座压力", "密封性", "排放能力"],
        "standards": [
            ("GB/T 12243", "弹簧直接载荷式安全阀"),
            ("TSG ZF001", "安全阀安全技术监察规程"),
            ("ASME BPVC Sec.I", "锅炉与压力容器规范——动力锅炉"),
        ],
    },
}

# Keyword triggers for parameter domain pre-filtering
D5_DOMAIN_TRIGGERS = {
    "振动": ["振动", "vibration", "齿轮", "轴承", "转子", "主轴"],
    "温度": ["温度", "温升", "thermal", "绕组", "轴瓦", "油温"],
    "绝缘电阻": ["绝缘", "对地", "相间", "兆欧"],
    "油液清洁度": ["油液", "颗粒度", "NAS", "清洁度", "液压"],
    "油中溶解气体(DGA)": ["DGA", "溶解气体", "色谱", "H2", "C2H2", "总烃"],
    "油液理化": ["油质", "酸值", "击穿电压", "tanδ", "介损"],
    "齿轮磨损": ["齿轮", "啮合", "齿面", "gearbox"],
    "滚动轴承": ["轴承", "滚珠", "滚柱", "包络", "冲击脉冲", "bearing"],
    "螺栓连接": ["螺栓", "紧固", "扭矩", "预紧", "法兰"],
    "接地": ["接地", "跨步电压", "接地电阻"],
    "避雷器": ["避雷器", "MOA", "金属氧化物"],
    "局部放电": ["局放", "局部放电", "PD", "PRPD"],
    "介电性能": ["介损", "tanδ", "介电", "电容"],
    "直流电阻": ["直流电阻", "DC resistance", "触头", "接触电阻"],
    "效率/性能": ["效率", "出力", "扬程", "流量", "功率因数"],
    "腐蚀/壁厚": ["腐蚀", "壁厚", "减薄", "氧化皮", "蠕变"],
    "水化学": ["水质", "pH", "溶解氧", "电导率", "硅酸根"],
    "安全阀": ["安全阀", "整定压力", "回座"],
}


def select_relevant_domains(comp_cn: str, equip_cn: str, search_text: str, max_n: int = 5) -> list[str]:
    """Pre-filter 18 parameter domains to the most relevant 3-5 for a given component."""
    text = f"{comp_cn} {equip_cn} {search_text[:3000]}".lower()
    scored = []
    for domain, triggers in D5_DOMAIN_TRIGGERS.items():
        score = sum(1 for kw in triggers if kw.lower() in text)
        if score > 0:
            scored.append((score, domain))
    scored.sort(reverse=True)
    selected = [d for _, d in scored[:max_n]]
    return selected if selected else list(D5_STANDARD_REFERENCE.keys())[:max_n]
