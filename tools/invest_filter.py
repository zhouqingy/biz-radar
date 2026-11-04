#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投资在线审批平台采集结果的业务过滤（2026-11-04）

为什么要有这一步
----------------
在线审批平台是「备案库」，里面绝大多数条目和都市环保的业务无关：
  · 光伏 —— 浙江一天能出上百条，其中 8 成是农户屋顶 20kW / 30kW 这种
  · 个人信息 —— 身份证、户籍、社保之类偶尔混进项目名
  · 规模太小 —— 几兆瓦的分布式光伏造价撑不到 1 亿，跟 EPC 大包不沾边

用户的判断和实测完全对得上：157 条含「光伏」里 127 条是千瓦级。
所以这里做两道筛：
  ① 硬剔除 —— 光伏/风电类，规模 < 20MW 一律不留（用户：「20、30、40、50 及以上的留」）
  ② 兜底 —— 名字里抽不出规模的，看业主是不是热电/钢铁/化工这类主业客户，
     是就留（例：「浙江巨化热电有限公司（巨化厂区三期）光伏项目」），
     否则按「分布式/户用/屋顶」关键词判小，剔除

规模抽取为什么这么写
--------------------
实际名字里的写法五花八门，实测样本：
  「...工商业分布式光伏发电项目1300千瓦」   ← 数字在尾部，千瓦
  「...680.9kw屋顶分布式光伏」              ← 小数 + 小写 kw
  「...60MW农光互补」                       ← 无空格
  「...20兆瓦渔光互补」                     ← 中文单位
  「...10000KW」                            ← 1 万 kW = 10MW
统一折算成 MW 再判断。注意「1.3MW」和「1300千瓦」要归一。
"""
import re

# ── 规模抽取 ────────────────────────────────────────────────────────────
# 数字 + 可选空格 + 单位；单位集覆盖实测出现的所有写法
_RE_SIZE = re.compile(
    r'(\d+(?:\.\d+)?)\s*'
    r'(万\s*kw|万\s*千瓦|万\s*kwh|mwp|mw|kwp|kw|kva|兆瓦|千瓦|mva|w)',
    re.I,
)

_UNIT_MW = {
    '万kw': 10.0, '万千瓦': 10.0, '万kwh': 10.0,
    'mwp': 1.0, 'mw': 1.0, 'mva': 1.0, '兆瓦': 1.0,
    'kwp': 0.001, 'kw': 0.001, 'kva': 0.001, '千瓦': 0.001,
    'w': 0.000001,
}


def grab_mw(name):
    """从项目名里抽装机容量，返回 MW；抽不出返回 None。

    只认「离光伏/风电/储能这些词最近的那个数字」—— 有的名字里既有地址号
    （147号）又有容量，全局找第一个数字会把门牌号当容量。
    """
    s = name or ''
    hits = []
    for m in _RE_SIZE.finditer(s):
        unit = re.sub(r'\s+', '', m.group(2)).lower()
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        k = _UNIT_MW.get(unit)
        if k is None:
            continue
        # 「W」单独出现极易误判（型号、功率等级），要求 ≥1000W 才算装机
        mw = val * k
        if unit == 'w' and val < 1000:
            continue
        hits.append((m.start(), mw))
    if not hits:
        return None
    # 离「光伏 / 风电 / 储能 / 发电」字样最近的优先；都没有就取最后一个
    anchors = [m.start() for m in re.finditer(r'光伏|风电|储能|发电|电站|渔光|农光', s)] or [len(s)]
    def dist(p):
        return min(abs(p - a) for a in anchors)
    hits.sort(key=lambda x: (dist(x[0]), -x[1]))
    return round(hits[0][1], 4)


# ── 业务类关键词 ────────────────────────────────────────────────────────
# 光伏、风电、纯储能 —— 这三类要看规模，规模不够不要
PV_W = ('光伏', '太阳能', '渔光', '农光', '分布式发电', '屋顶发电', '光电')
# 主业客户：这些业主顺手做的光伏，哪怕名字里没写规模也值得看一眼
CORE_OWNER_W = ('热电', '钢铁', '特钢', '不锈钢', '钢业', '冶炼', '焦化', '化工', '化纤',
                '水泥', '造纸', '玻璃', '有色', '铜业', '铝业', '冶金', '电厂',
                '能源集团', '能源科技', '控股集团')
NOISE_NAME = ('身份证', '户籍', '社保', '婚姻', '驾驶证', '营业执照登记', '税务登记',
              '发票', '公积金', '出生医学证明', '不动产登记')

# 规模门槛（MW）。用户口径：「20、30、40、50 及以上的可以尝试着留一下」
MW_KEEP = 20.0


# 「风电机组配件」「光伏组件」这类是装备制造，不是发电项目 —— 实测踩过：
# 「年产500套水利闸门…水轮机发电机组及风力风电机组配件项目」被「风电」误判成风电项目，
# 白占一条「待人工判断」。所以见到「配件/组件/设备/制造/生产线/年产」就先排除。
PV_PROD_W = ('配件', '组件', '支架', '逆变器', '生产线', '年产', '制造', '设备生产',
             '研发中心', '检测', '销售')


def is_pv(rec):
    n = (rec.get('name') or '')
    if any(w in n for w in PV_PROD_W):
        return False
    if '光伏' in n or '太阳能' in n or '渔光' in n or '农光' in n:
        return True
    if '风电' in n and '风机' not in n:
        return True
    return False


def pv_verdict(rec):
    """返回 (keep, mw, reason)。keep=True 表示保留。"""
    n = rec.get('name') or ''
    if any(w in n for w in NOISE_NAME):
        return False, None, '信息类噪声'
    if not is_pv(rec):
        return True, None, '非光伏'
    mw = grab_mw(n)
    if mw is None:
        # 抽不出规模：业主是主业客户就留，名字里有「户用/屋顶/分布式」且无业主线索则剔
        if any(w in n for w in CORE_OWNER_W):
            return True, None, '规模未知·主业客户'
        if any(w in n for w in ('户用', '屋顶', '分布式', '农户')):
            return False, None, '规模未知·分布式小项目'
        return True, None, '规模未知·待人工判断'
    if mw < 1:
        return False, mw, '千瓦级(<1MW)'
    if mw < MW_KEEP:
        return False, mw, '小兆瓦(<%gMW)' % MW_KEEP
    return True, mw, '达标(>=%gMW)' % MW_KEEP
