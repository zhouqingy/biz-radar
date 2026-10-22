# -*- coding: utf-8 -*-
"""巴淡岛（Batam）数据中心集群 —— 海外情报入库（2026-10-22 用户点题）

════════════════════════════════════════════════════════════════════════
为什么单独做一份
════════════════════════════════════════════════════════════════════════
用户原话：「最近印尼巴淡岛数据中心项目很火，好多企业过去，你看看能不能找到相应情况」

查完之后判断：这不是一条「热点新闻」，是我司海外定位的一次**实证**——
我们一直说「有色用热用电 + 配套海水淡化」是海外主线，巴淡岛把这句话变成了
**监管强制条款**：新建数据中心必须自建海水反渗透（SWRO）淡化厂，不建就批不了。

所以这 10 条不是拿来「看」的，是拿来判断「谁在什么时候会招标、我们能接哪一段」的。

════════════════════════════════════════════════════════════════════════
数据来源（都是可点开的原件，别用二手转述）
════════════════════════════════════════════════════════════════════════
  中国驻棉兰总领事馆经商处   medan.mofcom.gov.cn      —— 官方口径，最权威
  印尼国家通讯社 Antara      en.antaranews.com        —— BP Batam 局长原话
  Desalination News          desalination-news.com    —— 10/5 抗议与强制令细节
  BTW Media                  btw.media                —— DayOne 18 亿盾 SWRO 承诺
  台湾经济部国贸署           trade.gov.tw             —— 511 MVA 购电协议（PJBTL）
  w.media                    w.media                  —— PLN Batam 电力余量澄清
  见道网                     seetao.com               —— 20 项目 / 73 亿美元 / 电力缺口
  Jawawa / Apex News         jawawa.id / apexnews.com —— Batam 3&4 燃气电站 PPA

════════════════════════════════════════════════════════════════════════
字段说明
════════════════════════════════════════════════════════════════════════
  name   挂到哪家客户名下（必须与 oversea_clients.py 里的 name 完全一致，
         否则前端卡片上挂不上去）
  grp    行业组（数据中心 / 电力配套 等）
  kw     检索关键词
  title  一句话标题（前 70 字会显示在卡片上，把「谁 + 干了什么 + 多大」写进去）
  date   YYYY-MM-DD
  tag    海外投资 / 海外建厂 / 政策门槛 / 电力缺口 / 竞对动向
  cut    我司切口（这一条对我们意味着什么活）
  desc   详细解读（前端展开时显示）
  url    原文链接
  rel    关联度，保留字段（build_web 会用关键词重算，这里给个合理值）

════════════════════════════════════════════════════════════════════════
维护方式
════════════════════════════════════════════════════════════════════════
  python3 seed_batam.py            # 写入 / 更新（按 title 前 40 字去重，可重复跑）
  python3 seed_batam.py --dry      # 只看会写什么，不落盘
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'raw', 'oversea_extra.json')

# ══════════════════════════════════════════════════════════════════════
# 一、政策门槛类：这是全批里最重要的一条
# ══════════════════════════════════════════════════════════════════════
# 逻辑链要讲清楚，否则用户会觉得「不就是个水厂吗」：
#   巴淡岛没有天然河流湖泊 → 130 万人全靠 6 座人工水库蓄雨
#   → 2026 年旱季部分居民区断水 3-6 个月
#   → 10/5 数十名 Nongsa 居民堵了 Nongsa 数字园大门
#   → BP Batam 局长被迫表态：高耗水行业必须自备水源，数据中心首当其冲
#   → 结果：新建数据中心**必须自建 SWRO**，批文与 SWRO 承诺绑定
# 这不是环保倡议，是**核准前置条件**。对我们意味着：做数据中心供能的，
# 不打包海水淡化就拿不到整包。
BATAM = [
    # ────────── 1. 强制令（政策门槛）──────────
    dict(
        name='PT Equator Gate System Batam',
        grp='数据中心', kw='巴淡岛',
        title='巴淡岛监管强制新建数据中心自建海水淡化厂（SWRO），不建不批文',
        date='2026-10-16', tag='政策门槛',
        cut='海水淡化（SWRO）——监管前置条件，不是可选项',
        desc='巴淡岛无天然河流湖泊，130 万人口全靠 6 座人工水库蓄雨。2026 年旱季部分居民区断水 3–6 个月，'
             '10 月 5 日数十名 Nongsa 居民封堵 Nongsa 数字园大门，军警到场。'
             'BP Batam 局长 Amsakar Achmad 随后明确：高耗水行业（数据中心首当其冲）必须自备水源，'
             '新建数据中心须自建海水反渗透（SWRO）淡化设施，且作为开发核准的前置条件。'
             '【对我司含义】数据中心供能项目若不含海水淡化，基本拿不到整包——'
             '这正好是我司「有色用热用电 + 配套海水淡化」海外定位的直接延伸，而且是刚需而非可选项。',
        url='https://www.desalination-news.com/2026/10/16/indonesias-batam-orders-data-centers-to-build-seawater-desalination-plants-after-water-cut-protests/',
    ),
    dict(
        name='DayOne（原万国数据海外）',
        grp='数据中心', kw='DayOne',
        title='DayOne 承诺投 1800 亿印尼盾（约 1100 万美元）建 Kabil SWRO，建成移交 BP Batam',
        date='2026-09-10', tag='政策门槛',
        cut='海水淡化 EPC + O&M（建成后移交，含运维培训）',
        desc='BP Batam 局长 Amsakar Achmad 9 月 10 日确认：批准 DayOne 数据中心建设的前提，'
             '是它必须先建海水淡化厂。DayOne 同意出资约 1800 亿印尼盾（约 1026 万美元 / 1400 万新元），'
             '在 Kabil 工业园建 SWRO，建成后**移交 BP Batam 运营**，富余水量可供周边社区。'
             '局长原话：BP Batam 自己拿 1800 亿盾做不下来，希望私人投资把 SWRO 变成新的市政水源。'
             '【对我司含义】这是「企业出资建设 + 政府接管运营」的模式，'
             '适合做 EPC + 移交 + 运维培训包，也适合作为进入巴淡水务市场的第一个样板工程。'
             '目前未披露产能、开工时间、投产时间——这是最值得盯的下一步信息。',
        url='https://medan.mofcom.gov.cn/jmxw/art/2026/art_5e97b4f06d234d8398140094ee6db653.html',
    ),
    dict(
        name='PT Equator Gate System Batam',
        grp='数据中心', kw='Equator Gate',
        title='润泽科技巴淡项目公司 EGSB 已在 Nongsa 鱼眼湾规划 SWRO，两厂合计目标 750 升/秒',
        date='2026-09-10', tag='海外建厂',
        cut='海水淡化 + 供配电（数据中心侧配套）',
        desc='润泽科技在巴淡的数据中心由当地项目公司 PT Equator Gate System Batam（EGSB）实施，'
             '选址 Nongsa 镇鱼眼湾（Teluk Mata Ikan）。EGSB 已开始规划配套 SWRO，'
             '与 DayOne 的 Kabil 厂合计，两座厂预计 2–3 年内产出约 750 升/秒淡化水，'
             '长期目标约 1000 升/秒（约 8640 万升/日）。'
             '【对我司含义】润泽是国内客户，EGSB 是它的印尼落地主体——'
             '要走通这条线，需要同时接触润泽总部（河北廊坊）和 EGSB 现场团队。',
        url='https://batamnewsasia.com/2026/09/11/batam-data-center-expansion-rp180-billion-desalination-plant-planned-to-protect-freshwater-supply',
    ),

    # ────────── 2. 电力侧：缺口是真实的，但口径要说准 ──────────
    dict(
        name='PT PLN Batam（巴淡国家电力）',
        grp='电力配套', kw='PLN Batam',
        title='巴淡峰值负荷将从 841 MW 涨到 2035 年 2540 MW，接近三倍；岛上电网与国网不互联',
        date='2026-10-20', tag='电力缺口',
        cut='自备电站 / 园区直供电 / 燃气发电 + 余热',
        desc='两个数字要分清，别混用：'
             '① PLN 规划口径：峰值负荷 2026 年 841 MW → 2035 年 2540 MW（见道网引 PLN 规划）；'
             '② 现状口径：系统供电能力 930 MW、负荷约 780 MW、备用率约 20%（PLN Batam 总裁 Kwin Fo 10 月原话）。'
             '注意备用率 20% 是**全岛平均**，对 24 小时不间断的 AIDC 而言容错空间远小于此。'
             '更关键的是结构问题：巴淡电网由 PLN Batam 独立运营，与印尼国网**不互联**，'
             '缺电时无法从主网调电（Fitch Solutions/BMI 观点）。'
             'PLN 应对：Batam #1 联合循环 120 MW（2028 投产）、Batam 3&4 燃气蒸汽联合循环 2×150 MW'
             '（Dalle Energy 投资，2026-07-16 签 PPA）、150 MW 移动燃气机组租赁专供数据中心。',
        url='https://www.seetao.com/details/281028.html',
    ),
    dict(
        name='PT PLN Batam（巴淡国家电力）',
        grp='电力配套', kw='PLN Batam',
        title='2026-10-12 巴淡-民丹大停电 16 小时，41 万户断电，PLN 总裁因此下台',
        date='2026-10-13', tag='电力缺口',
        cut='园区自备电源 + 孤网稳定（这是最有说服力的销售素材）',
        desc='10 月 12 日巴淡与民丹岛大面积停电，波及约 41 万户，民丹岛一度只能靠两座共 32 MW 的柴油机'
             '维持（当地正常需求 80–100 MW），被迫实行 6 小时轮供。'
             '事件后 PLN 总裁被撤换，成为印尼电力体制改革的导火索。'
             'PLN Batam 总裁 Kwin Fo 公开否认停电与某数据中心测试有关，并强调「我们没有缺电、备用率近 20%」——'
             '但市场普遍认为数据中心集中投产是重要背景。'
             '【对我司含义】这类事件是海外推介最有力的素材：'
             '孤网 + 高密度负荷 + 无外援，正是「园区自备电站 + 孤网稳定控制」的价值证明。',
        url='https://w.media/batam-outage-not-linked-to-data-center-testing-pln-batam',
    ),

    # ────────── 3. 项目侧：谁在建、多大、给谁做 ──────────
    dict(
        name='DayOne（原万国数据海外）',
        grp='数据中心', kw='DayOne',
        title='DayOne 与 PLN 签 511 MVA 购电协议（印尼最大），BP Batam 配套 200 MWp 光伏',
        date='2026-04-17', tag='海外建厂',
        cut='配套电源 + 光伏 + 园区供配电',
        desc='2026 年 4 月 17 日，BP Batam、DayOne 项目公司 PT Digitalland Service One 与 PLN 三方签署'
             'Kabil 超大规模数据中心购电协议（PJBTL），供电容量 511 MVA，为印尼迄今最大的数据中心供电合同'
             '（约合 450 MW）。合作范围还包括光纤网络、基础设施运维，并延伸至绿电：'
             'BP Batam 将与 PLN Batam 合建 >200 MWp 光伏电站，有望成为印尼及东南亚最大光伏项目之一。'
             'DayOne 在巴淡已有两个基地：Nongsa 数字园（与印尼主权基金 INA 合作，'
             '星展 + 大华银团融资 6.7 万亿盾 / 约 4.11 亿美元）、Kabil 工业园（本次）。'
             '【对我司含义】511 MVA 是硬指标——这么大负荷的接入、变电、可靠性设计，'
             '通常要拆成多个 EPC 包，供配电和调相机/储能都是可切入的段。',
        url='https://www.trade.gov.tw/Pages/Detail.aspx?nodeID=45&pid=815412',
    ),
    dict(
        name='润泽智算科技集团股份有限公司',
        grp='数据中心', kw='润泽科技',
        title='润泽科技巴淡岛 Nongsa 圈地 30 公顷，投资 50 亿美元，一期 160 MW 高密液冷',
        date='2026-05-01', tag='海外投资',
        cut='燃机自备电源 + 液冷余热回收 + 海水淡化（三件套）',
        desc='润泽科技巴淡项目为其首个海外算力基地，总投资 50 亿美元，'
             '选址 Nongsa 数字园，占地约 30 公顷，一期规划 160 MW 高密液冷机柜，'
             '原计划 2026 年底交付（实际进度需核）。'
             '【对我司含义】这是三条业务线一次对齐的项目：'
             '① 160 MW 高密负荷 → 燃气发电/燃机联合循环自备电站；'
             '② 液冷 → 冷却水系统与余热回收（余热可供区域制冷或生活热水）；'
             '③ 巴淡无水 → SWRO 海水淡化强制配套。'
             '润泽是河北廊坊企业，不在江浙沪皖，但按用户口径「外地大厂也算」。',
        url='https://ysln.ycwb.com/content/2026-10/14/content_54319902.html',
    ),
    dict(
        name='BW Digital',
        grp='数据中心', kw='BW Digital',
        title='BW Digital 巴淡 144 MW 数据中心（NDP1）采用直接液冷，2026 年中投运',
        date='2026-06-01', tag='海外建厂',
        cut='液冷配套水系统 + 余热利用 + 供配电',
        desc='BW Digital 的 NDP1 设施 2026 年中达到 144 MW 运营容量，采用直接液冷（DLC）。'
             'CEO Ludovic Hutier 明确表示，选液冷是为了「提高效率、降低整体资源消耗」，'
             '并在评估水回收与节水策略。同时其在探索屋顶光伏与先进能源管理系统，'
             '以回应微软/谷歌/亚马逊/Meta 等超大规模客户的净零要求。'
             '【对我司含义】液冷意味着没有传统冷冻水塔的大蒸发损失，但换来的是'
             '**更高品位余热集中排放**——这正是余热回收（供热/制冷）的最佳场景，比风冷机房好做得多。',
        url='https://www.gate.com/news/detail/batam-data-center-boom-accelerates-amid-water-and-energy-constraints-20360167',
    ),
    dict(
        name='巴淡自贸区管理局（BP Batam）',
        grp='电力配套', kw='BP Batam',
        title='巴淡落地 20 个数据中心项目，承诺投资超 73 亿美元，装机占印尼全国约 15%',
        date='2026-10-14', tag='海外投资',
        cut='园区级能源岛总承包（发电 + 配电 + 水）',
        desc='巴淡已落地 20 个数据中心项目，承诺投资超 73 亿美元；另有口径称 2026 年年中'
             '为 9 个项目、120 万亿印尼盾。两个数字差异来自「已签约」与「已开工」口径不同，'
             '对外引用时建议写「20 个签约 / 73 亿美元」。'
             '巴淡数据中心装机约占印尼全国 15%，行业年增速约 22%。'
             '中资已落地：润泽科技（50 亿美元 AI 数据中心）、'
             '中国能建（东南亚首个绿电-氢-氨醇一体化，240 MW 光伏 + 3.75 万吨/年绿氨，绿氨供新加坡）、'
             '海泰新能（2 GW 电池 + 1 GW 组件）、苹果 AirTag 工厂、恒通智能物流园。'
             '【对我司含义】20 个项目 = 20 个潜在能源岛机会，且集中在 Nongsa、Kabil、'
             'Tanjung Uncang 三个片区，可以按片区打包做集中供能，摊薄单位投资。',
        url='https://www.seetao.com/details/281028.html',
    ),
    dict(
        name='巴淡自贸区管理局（BP Batam）',
        grp='电力配套', kw='BP Batam',
        title='巴淡市政供水产能仅 3487 升/秒，2030 年将出现缺口；淡化总投资需求约 3 万亿盾',
        date='2026-10-01', tag='电力缺口',
        cut='海水淡化（RO 膜法）+ 工业园区供水',
        desc='巴淡现有自来水产能 3487 升/秒，来自 6 座水库，2026 年 2 月已有约 18 处报告缺水。'
             'BP Batam《2025–2029 战略规划》明确：若不采取措施，'
             '巴淡及邻近的伦庞岛（Rempang）、加朗岛（Galang）到 2030 年将出现供水缺口。'
             'BP Batam 自 2025 年 3 月起启动海水淡化研究，'
             '估算淡化设施总投资约 3 万亿印尼盾（约 1.75 亿美元），目标产能约 2600 升/秒。'
             'Fitch Solutions/BMI 分析师 Alexander Kheder：'
             '「水可以说是最严重的长期制约，当地居民本来就在经历缺水和配给。」'
             '【对我司含义】这是市政侧的水厂，规模大（1.75 亿美元）、周期长、需政府预算；'
             '相比之下企业自建（DayOne 1100 万美元级）更快落地，建议先做企业侧再谈市政侧。',
        url='https://www.gate.com/news/detail/batam-data-center-boom-accelerates-amid-water-and-energy-constraints-20360167',
    ),
]

# ── 幂等写入：按 title 前 40 字去重，重复跑不会产生重复条目 ──
def key(x):
    return (x.get('title') or x.get('t') or '')[:40]

def main():
    dry = '--dry' in sys.argv
    old = json.load(open(OUT, encoding='utf-8'))
    old = old.get('items', old) if isinstance(old, dict) else old
    seen = {key(x) for x in old}

    added, skipped = [], 0
    for x in BATAM:
        if key(x) in seen:
            skipped += 1
            continue
        # 历史条目没有 cut 字段，新条目统一补上，前端按 cut 是否为空决定显不显示切口标签
        x.setdefault('rel', 8)
        old.append(x)
        seen.add(key(x))
        added.append(x)

    old.sort(key=lambda x: x.get('date') or '', reverse=True)

    print('原有 %d 条 / 新增 %d 条 / 跳过重复 %d 条 / 合计 %d 条'
          % (len(old) - len(added), len(added), skipped, len(old)))
    for x in added:
        print('  + %s  %-14s %s' % (x['date'], x['grp'], x['title'][:52]))

    if dry:
        print('（--dry，未落盘）')
        return

    json.dump(old, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已写入 %s' % OUT)


if __name__ == '__main__':
    main()
