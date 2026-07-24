"""
将数据库 devicetype 按知识库定义分类为: 设备 / 子设备 / 子系统 / 部件 / 零件 / 其他
=========================================================================
分类依据 (优先级从高到低):
  1. 特殊技术路线代码 (如风电 139553/139554/139552) -> 子设备
  2. 知识库白名单精确/包含匹配 (equipment_registry.md 设备, components.md 部件)
  3. 工程常识关键词规则 (设备级整机词 vs 部件级总成词)
  4. 兜底 -> 其他/待复核

输出:
  - devicetype_kb_classification.csv   devicetype -> 层级 映射 (供复核)
  - industry_devicetype_topN.csv       追加 kb_level 列 (回写主表)
"""
import sys, io, os, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_export')

# === 知识库白名单 ===
wl = json.load(open(os.path.join(EXPORT, '_kb_whitelist.json'), encoding='utf-8'))
EQ_SET = set(wl['equipment'])      # 697 设备名
COMP_SET = set(wl['component'])    # 1793 部件名

# === 1. 特殊子设备代码 (技术路线, 对应风电机组子设备) ===
SUBEQUIP_CODES = {'139553': '子设备', '139554': '子设备', '139552': '子设备'}

# === 2. 关键词规则 (有序, 长词/具体词优先; 先设备整机词, 再部件总成词) ===
# 设备级: 能独立采购/运维/完成独立功能的整机
EQUIP_KW = [
    '压缩机', '破碎机', '提升机', '输送机', '给料机', '喂料机', '给料机',
    '辊压机', '压滤机', '过滤机', '分离机', '离心机', '选粉机', '分级机',
    '反应釜', '反应器', '搅拌机', '搅拌器', '混合机', '捏合机', '造粒机',
    '轧机', '卷取机', '开卷机', '切断机', '飞剪', '剪切机', '矫直机',
    '换热器', '蒸发器', '冷凝器', '结晶器', '干燥机', '烘干机', '冷却机', '烧结机',
    '冷却塔', '吸收塔', '蒸馏塔', '解析塔', '洗涤塔', '提氢塔', '反应塔',
    '变压器', '断路器', '开关柜', '配电柜', '变频器', '逆变器', '整流器', '软启动',
    '发电机', '电动机', '汽轮机', '水轮机', '燃气轮机', '透平',
    '取料机', '堆取料机', '翻车机', '卸船机', '装船机', '堆料机',
    '行车', '天车', '起重机', '吊车', '卷扬机', '电梯', '升降机',
    '高炉', '加热炉', '热油炉', '锅炉', '回转窑', '窑', '烧结',
    '回转台', '转台', '活套', '减定径', '减径', '定径', '开卷', '卷取',
    '扶梯', 'TRT', 'Robot', '电铲', '氧枪', '定量秤', '秤', '枪', '铲',
    '剪', '锯', '磨',
    '风机', '泵', '磨机', '筛', '机', '床', '车', '炉', '塔', '器',
]
# 部件级: 设备的组成部分, 可独立更换/检修的总成
COMPONENT_KW = [
    '齿轮箱', '减速机', '减速箱', '锥箱', '变速箱', '箱体', '箱',
    '轴承座', '轴承', '座', '支架', '支座',
    '辊', '轴', '轮', '叶片', '法兰', '螺栓', '螺母', '销',
    '油缸', '气缸', '液压缸', '缸', '联轴器', '密封',
    '链条', '胶带', '皮带', '滤芯', '滤网', '制动器', '制动盘',
    '轴瓦', '衬套', '齿条', '齿圈', '丝杠', '导轨', '滑轨', '机架', '底座',
    '头轮', '尾轮', '链轮', '叶轮', '飞轮', '托辊', '滚筒', '改向滚筒', '卷筒',
    '变桨', '摇臂', '臂',
    '斗', '槽', '门', '罩', '壳', '盘', '管', '阀', '罐', '箱',
]
# 零件级
PART_KW = ['小齿轮', '太阳轮', '行星轮', '齿轮副', '摩擦片', '膜片', '弹簧', '销轴', '滚子', '钢球', '阀芯', '阀座', '键']
# 子系统级 (功能域)
SUBSYSTEM_KW = ['系统', '站', '装置']  # 冷却系统/润滑系统/供油站 等
# 其他: 仪表/区域/杂项
INSTRUMENT_KW = ['压力表', '温度计', '传感器', '变送器', '控制盘', '配电盘', '仪表', '继电器', '互感器', '表', '计']
AREA_KW = ['机舱', '塔基', '塔顶', '塔中', '机头', '机尾', '头部', '尾部', '区域', '环境', '部位', '位置', '口']
MISC_KW = ['非标', '通用', '算法', '场景', '其他', '未分类', '空', '杂', '电气设备', '润滑设备']


def classify(code, name):
    code = str(code)
    name = str(name)
    # 1. 特殊子设备代码
    if code in SUBEQUIP_CODES:
        return SUBEQUIP_CODES[code], '高(技术路线代码)', '风电机组子设备'
    if name in ('(未分类)', '(空devicetype)'):
        return '其他', '高', '脏数据/未分类'
    # 2. 白名单精确匹配
    if name in EQ_SET:
        return '设备', '高(白名单)', '知识库equipment_registry命中'
    if name in COMP_SET:
        return '部件', '高(白名单)', '知识库components命中'
    # 3. 白名单包含匹配 (name 被某白名单项包含, 或包含某白名单项)
    for e in EQ_SET:
        if name in e and len(name) >= 2:
            return '设备', '中(白名单包含)', f'近似知识库设备: {e}'
    for c in COMP_SET:
        if name in c and len(name) >= 2:
            return '部件', '中(白名单包含)', f'近似知识库部件: {c}'
    # 4. 关键词规则 (先零件, 再部件, 再设备, 再子系统, 再其他)
    for kw in PART_KW:
        if kw in name:
            return '零件', '中(关键词)', f'含零件词「{kw}」'
    for kw in COMPONENT_KW:
        if kw in name:
            return '部件', '中(关键词)', f'含部件词「{kw}」'
    for kw in EQUIP_KW:
        if kw in name:
            return '设备', '中(关键词)', f'含设备词「{kw}」'
    for kw in INSTRUMENT_KW:
        if kw in name:
            return '其他', '中(关键词)', f'仪表「{kw}」'
    for kw in AREA_KW:
        if kw in name:
            return '其他', '中(关键词)', f'部位/区域「{kw}」'
    for kw in SUBSYSTEM_KW:
        if kw in name:
            return '子系统', '中(关键词)', f'功能域「{kw}」'
    for kw in MISC_KW:
        if kw in name:
            return '其他', '低', f'杂项「{kw}」'
    return '待复核', '低', '未命中规则'


# === 应用分类 ===
df = pd.read_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'),
                 encoding='utf-8-sig', dtype={'devicetype': str})
df = df.drop(columns=[c for c in df.columns if str(c).startswith('kb_level')], errors='ignore')

# 对唯一 (devicetype, devicetype_cn) 分类, 避免重复计算
uniq = df[['devicetype', 'devicetype_cn']].drop_duplicates()
rows = []
for _, r in uniq.iterrows():
    lvl, conf, reason = classify(r['devicetype'], r['devicetype_cn'])
    rows.append({'devicetype': r['devicetype'], 'devicetype_cn': r['devicetype_cn'],
                 'kb_level': lvl, 'confidence': conf, 'reason': reason})
cls = pd.DataFrame(rows)

# 回写主表
df = df.merge(cls[['devicetype', 'kb_level']], on='devicetype', how='left')
df.to_csv(os.path.join(EXPORT, 'industry_devicetype_topN.csv'), index=False, encoding='utf-8-sig')

# 保存分类映射
cls.to_csv(os.path.join(EXPORT, 'devicetype_kb_classification.csv'), index=False, encoding='utf-8-sig')

# === 统计 ===
print("=" * 70)
print("devicetype 知识库层级分类结果 (按层级)")
print("=" * 70)
# 用 TopN 内的 (避免长尾重复计数), 按层级统计设备数
topn = df[df['in_topn'] == True].copy()
stat = topn.groupby('kb_level').agg(
    型号数=('devicetype', 'nunique'),
    设备实例数=('device_count', 'sum'),
).reset_index().sort_values('设备实例数', ascending=False)
print(stat.to_string(index=False))

print("\n" + "=" * 70)
print("待复核 / 低置信度项 (需人工确认)")
print("=" * 70)
review = cls[cls['kb_level'] == '待复核']
print(f"待复核: {len(review)} 个")
if len(review):
    print(review[['devicetype', 'devicetype_cn']].to_string(index=False))

print("\n分类映射已保存 -> devicetype_kb_classification.csv")
print("主表已追加 kb_level 列 -> industry_devicetype_topN.csv")

# === 行业 x 层级 交叉统计 (基于 TopN 内, 回答"每行业各层有多少") ===
LEVELS = ['设备', '子设备', '子系统', '部件', '零件', '其他']
cross = (df[df['in_topn']]
         .groupby(['industry_cn', 'kb_level'])['device_count'].sum()
         .unstack(fill_value=0))
for lv in LEVELS:
    if lv not in cross.columns:
        cross[lv] = 0
cross = cross[LEVELS]
# 按设备总数降序
cross = cross.loc[cross.sum(axis=1).sort_values(ascending=False).index]
cross.to_csv(os.path.join(EXPORT, 'industry_x_level.csv'), encoding='utf-8-sig')

print("\n" + "=" * 70)
print("行业 x 知识库层级 设备数交叉 (TopN 内)")
print("=" * 70)
print(cross.to_string())
print("\n已保存 -> industry_x_level.csv")
