#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单位百科补深 · 第三批（2026-10-23，有色系两家）

用户要求「按真实的来做的深一点」「业绩情况、主要人员情况不全」。
这一批是长沙有色院 + 中国瑞林，信息来自两家官网报道 + 证券日报披露的董事会决议
（瑞林是上市公司候选，半年报口径的项目清单最全）。
"""
import json

RAW = '/workspace/biz-radar-tools/raw'
d = json.load(open(RAW+'/units_encyclopedia.json', encoding='utf-8'))

ADD = {
'长沙有色冶金设计研究院有限公司': {
  'people': {
    '党委书记、董事长': '谭荣和',
    '党委副书记、总经理': '杨彪',
    '副董事长': '康国华',
    '党委副书记、纪委书记': '刘和',
    '财务总监': '张保学',
    '副总经理': '朱建国（2025-12 代表院方与五矿二十三冶签战略合作协议）',
    'src': '长沙有色院官网 cinf.com.cn 2026-02 九届八次职代会报道、2025-12 战略合作签约报道'
  },
  'projects': [
    '2025 年完成与贵阳铝镁院「两院」融合改革，生产经营业绩持续增长（中铝国际体系内重组）',
    '2025-12 与五矿二十三冶签署战略合作协议（有色冶金产业链协同，矿山开发领域共建标杆项目）'
  ],
  'signal': '2026 年工作会定调「有色行业创新型领军企业」，锚定三大市场；谭荣和在党课里明确要求「加大海外市场开拓力度」',
  'note_split': '与五矿二十三冶绑定成「设计+施工」组合，投标时它们可能以联合体形式出现——二十三冶也在我们的百科名单里'
},
'中国瑞林工程技术股份有限公司': {
  'people': {
    '党委书记、董事长、总经理': '吴润华',
    '党委委员、副总经理': '刘奕 · 何峰',
    'src': '中国瑞林官网 nerin.com 2026-05 灵宝黄金签约报道 + 证券日报 2025-08-26 第三届董事会第七次会议决议公告'
  },
  'projects': [
    '吉尔吉斯斯坦托戈洛克金矿 EPC 总承包（1.128 亿美元，24 个月，业主库姆托尔运营公司）',
    '刚果（金）卡莫阿—卡库拉 50 万吨/年一步炼铜冶炼厂（EPCM 全过程服务，2025 点火烘炉）',
    '易门铜业酸性废水无钠硫化提升改造项目 EPC 总承包（2025 投产即达产）',
    '云南红河砷业 2 万吨/年含砷物料资源化利用项目（初步设计 + 施工图设计）',
    '塞尔维亚波尔铜业扩建项目（阴极铜年产量 7 万吨→20 万吨，2025 完工）',
    '阿根廷 Mariana 赣锋锂业 2 万吨氯化锂一期（2025 全线投产）',
    '马达加斯加 MANDROSEZA 紧凑型水处理厂（2026-05 总统主持通水仪式）',
    '西芒杜铁矿项目（力拓 Simfer，提供现场技术支持 / 数字化交付 / 现场质量管理）'
  ],
  'overseas': True,
  'overseas_list': ['吉尔吉斯斯坦','刚果（金）','塞尔维亚','阿根廷','津巴布韦','尼日利亚','马达加斯加'],
  'tech': ['有色金属矿山露天与深井开采','选矿与浸出','闪速冶金','熔池冶金','铜电解','湿法炼铜',
           '再生铜回收','烟气制酸','固体废物环保处置','场地污染防治','有色冶金过程自动化智能化'],
  'signal': '2025 年获江西省优秀工程勘察设计成果奖 18 项（一等奖 7 项）+ 全国优秀工程勘察设计奖 5 项；海外 EPC 已能做到 1 亿美元级',
  'note_split': '它的「烟气制酸 + 酸性废水 + 固废处置」和我们环保辅业是同一块活，境外项目常缺能源动力岛——这是我们可以切入的位置'
}
}

n_pj = n_pp = 0
for g in d['groups']:
    for u in g.get('units', []):
        a = ADD.get(u['name'])
        if not a: continue
        if 'projects' in a:
            have = set(u.get('projects') or [])
            add = [p for p in a['projects'] if p not in have]
            u['projects'] = list(u.get('projects') or []) + add
            n_pj += len(add)
        if 'people' in a:
            p = dict(u.get('people') or {})
            for k, v in a['people'].items():
                if k == 'src': p['src'] = v
                elif k not in p: p[k] = v
            u['people'] = p
            n_pp += 1
        for k in ('signal','note_split','tech','qual'):
            if k in a and not u.get(k): u[k] = a[k]
        if a.get('overseas'):
            u['overseas'] = True
            u['overseas_list'] = a['overseas_list']
        u['confidence'] = '查证'

json.dump(d, open(RAW+'/units_encyclopedia.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print('第三批：新增业绩 %d 条，班子补 %d 家' % (n_pj, n_pp))
