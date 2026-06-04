"""质量对比脚本：旧数据 vs 新数据"""
import re, glob, os

def count_confidence(pattern):
    total = tagged = standard = experience = pending = 0
    for f in glob.glob(pattern, recursive=True):
        if not f.endswith('.md'):
            continue
        try:
            content = open(f, encoding='utf-8').read()
        except:
            continue
        for line in content.split('\n'):
            if not re.search(r'\[物理\]|\[电气\]|\[化学\]|\[状态量\]', line):
                continue
            # 按分号拆分每条参数
            for seg in re.split(r'[；;]', line):
                seg = seg.strip()
                if not seg or not re.search(r'\[物理\]|\[电气\]|\[化学\]|\[状态量\]', seg):
                    continue
                total += 1
                if '置信：标准值' in seg or '置信:标准值' in seg:
                    standard += 1
                    tagged += 1
                elif '置信：经验值' in seg or '置信:经验值' in seg:
                    experience += 1
                    tagged += 1
                elif '置信：待核实' in seg or '置信:待核实' in seg:
                    pending += 1
                    tagged += 1
    return total, tagged, standard, experience, pending


def count_standards(pattern):
    """统计引用了标准号的参数条数"""
    std_count = 0
    for f in glob.glob(pattern, recursive=True):
        if not f.endswith('.md'):
            continue
        try:
            content = open(f, encoding='utf-8').read()
        except:
            continue
        std_count += len(re.findall(r'(DL[/／]T\s*\d+|GB[/／]T?\s*\d+|ISO\s*\d+|IEC\s*\d+|HAF\s*\d+)', content))
    return std_count


def count_d8_format(pattern):
    """统计D8中包含'根本处理'和'临时处理'的行数"""
    total_d8 = 0
    has_root_temp = 0
    for f in glob.glob(pattern, recursive=True):
        if not f.endswith('.md'):
            continue
        try:
            content = open(f, encoding='utf-8').read()
        except:
            continue
        for line in content.split('\n'):
            if not line.startswith('|'):
                continue
            cells = [c.strip() for c in line.split('|')[1:-1]]
            # 找D8列（通常是第9列，索引8）
            if len(cells) >= 9:
                d8 = cells[8]
                if d8 and d8 not in ('D8', '---') and not re.match(r'^[-:|]+$', d8):
                    total_d8 += 1
                    if '根本处理' in d8 and '临时处理' in d8:
                        has_root_temp += 1
    return total_d8, has_root_temp


if __name__ == '__main__':
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    datasets = [
        ('OLD_wind_turbine',    '_archive/wind_faults_20260520/风电机组/*.md'),
        ('OLD_thermal_boiler',  '_archive/thermal_faults_20260520/boiler/*.md'),
        ('OLD_thermal_main_tf', '_archive/thermal_faults_20260520/main_transformer/*.md'),
        ('NEW_wind_turbine',    'data/power/wind/风电机组/faults/*.md'),
        ('NEW_wind_box_tf',     'data/power/wind/箱式变压器/faults/*.md'),
        ('NEW_thermal_boiler',  'data/power/thermal/boiler/faults/*.md'),
        ('NEW_thermal_st',      'data/power/thermal/steam_turbine/faults/*.md'),
        ('NEW_thermal_main_tf', 'data/power/thermal/main_transformer/faults/*.md'),
    ]

    print("=" * 90)
    print("D5 Confidence Tagging Comparison (Old vs New)")
    print("=" * 90)
    print(f"{'Dataset':<24} {'Total':>6} {'Std':>6} {'Exp':>6} {'Pend':>6} {'Untag':>6} {'Rate':>7}")
    print("-" * 90)

    old_total_params = 0
    old_tagged = 0
    new_total_params = 0
    new_tagged = 0

    for name, pattern in datasets:
        full_pattern = os.path.join(base, pattern)
        t, tagged, s, e, p = count_confidence(full_pattern)
        u = t - tagged
        rate = f"{tagged*100/t:.0f}%" if t > 0 else "N/A"
        print(f"{name:<24} {t:>6} {s:>6} {e:>6} {p:>6} {u:>6} {rate:>7}")
        if name.startswith('OLD'):
            old_total_params += t
            old_tagged += tagged
        else:
            new_total_params += t
            new_tagged += tagged

    print("-" * 90)
    if old_total_params > 0:
        print(f"OLD TOTAL: {old_total_params} params, {old_tagged} tagged ({old_tagged*100//old_total_params}%)")
    if new_total_params > 0:
        print(f"NEW TOTAL: {new_total_params} params, {new_tagged} tagged ({new_tagged*100//new_total_params}%)")

    # Standard references
    print()
    print("=" * 90)
    print("Standard References in D5 (Old vs New)")
    print("=" * 90)
    for name, pattern in datasets:
        full_pattern = os.path.join(base, pattern)
        std_count = count_standards(full_pattern)
        print(f"{name:<24} {std_count:>6} standard references")

    # D8 format
    print()
    print("=" * 90)
    print("D8 Format Compliance (root+temp treatment)")
    print("=" * 90)
    for name, pattern in datasets:
        full_pattern = os.path.join(base, pattern)
        total_d8, compliant = count_d8_format(full_pattern)
        rate = f"{compliant*100//total_d8}%" if total_d8 > 0 else "N/A"
        print(f"{name:<24} {compliant:>4}/{total_d8:>4} compliant ({rate})")
