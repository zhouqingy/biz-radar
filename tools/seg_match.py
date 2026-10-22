# -*- coding: utf-8 -*-
"""业务匹配引擎：把一条记录判到具体层级，并给「关联度」判定。

配套 seg_biz.py 使用。这里只做判定，不改词表。

设计原则：
1. 规则顺序 = 优先级，先命中先返回。有色冶炼排最前，因为「镍铁矿热炉余热发电」
   同时能命中 youse 和 wasteheat，必须先被 youse 接住，否则有色业绩统计不到。
2. 数据中心要「共现」判定：单说「数据中心」但招的是服务器，不算我们业务。
3. 关联度分三档：high（核心工艺词+总承包）/ mid（一级业务）/ low（其他）
"""

import re
import seg_biz as SB


def _hit(text, kws):
    """返回命中的第一个关键词，没命中返回 None"""
    for k in kws:
        if k in text:
            return k
    return None


def classify(text, title_only=None):
    """判层级。

    返回 dict:
      seg    层级 code（youse/steelgas/.../wte/other）
      segname 显示名
      rank   层级序号（越小越靠前）
      kw     命中的关键词
      is_dc  是否数据中心（需要额外过滤）
    """
    s = text or ''
    t = title_only if title_only is not None else s

    for code, kws in SB.RULES:
        # 数据中心特殊处理：必须能源词共现
        if code == 'datactr':
            dc_kw = _hit(s, kws)
            if dc_kw:
                en_kw = _hit(s, SB.DC_ENERGY)
                if en_kw:
                    return {'seg': code, 'segname': SB.LEVELS[code][0],
                            'rank': SB.LEVELS[code][1], 'kw': dc_kw + '/' + en_kw,
                            'is_dc': True}
                # 只有数据中心词、没有能源词 → 是 IT 采购，不算
                continue
            continue

        kw = _hit(t, kws)
        if kw:
            return {'seg': code, 'segname': SB.LEVELS[code][0],
                    'rank': SB.LEVELS[code][1], 'kw': kw, 'is_dc': False}

    return {'seg': 'other', 'segname': '其他', 'rank': 50, 'kw': '', 'is_dc': False}


def is_excluded(text):
    """是否属于「服务/货物采购」，不该进主列表

    ⚠ 2026-10-22 修了一个把大项目整条踢飞的 bug：
      老实现是 `只要正文里出现任何一个排除词就排除`。但排除词表里有一批
      **在项目描述里也会正常出现**的词，最典型的是「规划」：
        「连云港经开区热电联产项目一期工程总承包
          总规划 3×150t/h 高温超高压循环流化床锅炉 + 2×15MW 级背压机组…」
      这里「总规划」是在描述建设规模，不是在买"规划编制服务"，
      结果这条 4.46 亿的热电联产 EPC 被判成"服务采购"，直接从对手榜里消失。
      同类危险的词还有：土建、安装施工、调试工程、输煤、钢结构——
      它们大量出现在 EPC 总承包的**建设内容**里。

      现在的判断顺序：
        ① 先看是不是 EPC/工程总承包 标的（EPC_MARK 命中）→ 是的话，
           只有那些**明确只做服务**的词（监理/可研/招标代理/环评…）才排除；
           建设内容类的词（规划/土建/安装/输煤…）一律不算排除。
        ② 不是 EPC 标的，才用完整词表判断。
    """
    s = text or ''
    if not s:
        return False
    hit = _hit(s, SB.EXCLUDE)
    if hit is None:
        return False
    # 这些词无论上下文都是"服务/咨询"，见到就排除
    if hit in _HARD_SERVICE:
        return True
    # 其余的（规划/土建/安装/输煤/调试…）只在本条**不是总承包**时才当排除理由
    if is_epc(s):
        return False
    return True


def is_epc(text):
    """是否总承包标的"""
    return _hit(text or '', SB.EPC_MARK) is not None


# 「无论上下文都是服务/咨询」的硬排除词。
# 和 EXCLUDE 的区别：EXCLUDE 里混着「规划/土建/安装/输煤」这类
# **在 EPC 建设内容里也很正常**的词，不能一律当排除。
_HARD_SERVICE = {
    '监理', '可行性研究', '可研', '评估咨询', '招标代理', '造价咨询',
    '中期评估', '评估方案', '专题研究', '课题', '咨询服务',
    '环评', '环境影响评价', '社会稳定风险', '节能评估', '水土保持',
    '备品备件', '备件', '检修', '维修', '保养', '运维服务',
    '检测', '检验', '运输', '租赁', '询价', '竞价', '谈判采购',
    '单一来源', '定点采购', '保安', '保洁', '劳务', '培训',
    '软件开发', '系统集成', '服务器采购', '机柜采购', '交换机', '存储设备',
    '设备采购', '系统采购', '集中采购', '采购招标', '物资采购',
    '采购项目', '设备供货', '供货项目',
}


def core_hit(text):
    """命中的核心工艺词（用于「关联度特别大」判定）"""
    s = text or ''
    for k in SB.CORE_TECH:
        if k in s:
            return k
    return None


def parse_amt_yuan(s, amt=None):
    """从金额文本里扒出「亿元」。amt 是已经解析好的元数值（优先用）。

    支持：3.2亿 / 32000万元 / 3,2000万 / 12800.5万元 / 1.2亿元
    """
    if amt:
        try:
            v = float(amt)
            if v > 0:
                return v / 1e8
        except (TypeError, ValueError):
            pass
    if not s:
        return None
    txt = str(s).replace(',', '').replace('，', '').replace(' ', '')
    m = re.search(r'([\d.]+)\s*亿', txt)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    m = re.search(r'([\d.]+)\s*万', txt)
    if m:
        try:
            return float(m.group(1)) / 1e4
        except ValueError:
            return None
    return None


# ══════════════════════════════════════════════════════════════════════
# 门槛判定（用户 2026-10-21 确认）
#   ≥1 亿                        → 进
#   0.3 ~ 1 亿 且 核心工艺词+EPC  → 进，标「关联度极高」
#   0.3 ~ 1 亿 但 不满足上面两条  → 不进
#   <0.3 亿                      → 不进
#   金额未知：一级业务 + 核心工艺词 → 进（标「金额待核」）
#            其余未知额 → 不进
# ══════════════════════════════════════════════════════════════════════
AMT_MAIN = 1.0      # 主门槛：1 亿
AMT_RELAX = 0.3     # 放宽门槛：3000 万


def is_home(seg):
    """是否「主场业务」：一级、二级都算主场。
    三级（土壤/废水零排/市政污水）是分公司业务，用户原话
    「也能做，但是这是我们分公司的业务，不作为最主要的去关注」
    ——所以不算主场，主列表里单独折到「兼营」区，不跟主业抢位置。
    """
    return SB.level_rank(seg) <= 2


def judge(rec, text=None):
    """判定一条记录该不该进「能投的标」主列表。

    rec 需要：amtY(亿元) 或 amtYuan(元) 或 amtTxt
    返回 (是否进, 理由code, 说明)
    """
    text = text if text is not None else _rec_text(rec)

    if is_excluded(text):
        return False, 'excluded', '服务/货物采购，非总承包标的'

    info = classify(text)
    rank = info['rank']
    if rank > 3:
        return False, 'other', '不在主营业务分层内'

    amt = rec.get('amtY')
    if amt is None:
        amt = parse_amt_yuan(rec.get('amtTxt'), rec.get('amt'))

    core = core_hit(text)
    epc = is_epc(text)

    if amt is not None:
        if amt >= AMT_MAIN:
            return True, 'main', '金额 %.2f 亿 ≥ 1 亿' % amt
        if amt >= AMT_RELAX:
            if core and epc:
                return True, 'relax', '金额 %.2f 亿但命中核心工艺「%s」+总承包' % (amt, core)
            return False, 'small', '金额 %.2f 亿，未达 1 亿且关联度不足' % amt
        return False, 'small', '金额 %.2f 亿 < 3000 万' % amt

    # 金额未知
    if rank == 1 and core:
        return True, 'noamt', '金额未公开，但命中一级业务核心工艺「%s」' % core
    return False, 'noamt', '金额未知且关联度不足'


def _rec_text(r):
    parts = [str(r.get(k) or '') for k in ('t', 'snip', 'buyer', 'win', 'subname')]
    return ' '.join(parts)
