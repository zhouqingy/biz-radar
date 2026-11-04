#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按项目名反查商机库里「这个项目现在到哪一步了」（2026-11-04）

用户的原话：
    过滤完之后还是需要根据项目名称去搜一下它当前的一些状态金额呀，以及什么情况的。
    它有可能是就是初始阶段嘛，也有可能是确实是做完了或者什么的。
    不然的话我感觉从在线审批平台上拿到的数据都是比较初始的数据。

为什么必须做这一步
------------------
投资在线审批平台拿到的是**备案/核准那一刻**的数据，只有名字、事项、受理部门、办结日期。
备案之后这个项目可能：
  · 已经招标了 → 商机库里有「招标公告」+ 招标控制价
  · 已经中标了 → 有中标金额、中标单位
  · 还在纸面上 → 商机库里搜不到，说明确实是早期线索

匹配怎么做（宁可漏，不可错）
--------------------------
备案项目名和交易平台公告名对不上是常态，公告常带「(第二次)」「施工」「监理」等后缀，
备案名常带「（basic建设）」括号说明。所以：
  ① 归一化：去括号内容、去省市县前缀、去「项目/工程/建设」这类虚词、去空白符号
  ② 用归一化后的**核心串**做双向包含；核心串短于 8 字不做包含匹配（太容易撞车）
  ③ 再退一步用「业主名 + 关键词」—— 只用于提示，不当成确定匹配
只输出匹配等级，不下最终结论；等级 A 才算真匹配，B 要人工看。
"""
import re
import json
import os
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))

# 项目名里不影响识别的装饰词
FILL = ('建设项目', '项目', '工程', '建设', '一期', '二期', '三期', '四期',
        '（', '）', '(', ')', '【', '】', '、', '，', ',', '·', ' ', '　', '-', '_')
GEO = ('浙江省', '江苏省', '安徽省', '上海市', '浙江', '江苏', '安徽', '上海',
       '杭州市', '宁波市', '温州市', '嘉兴市', '湖州市', '绍兴市', '金华市', '衢州市',
       '舟山市', '台州市', '丽水市', '南京市', '无锡市', '徐州市', '常州市', '苏州市',
       '南通市', '连云港市', '淮安市', '盐城市', '扬州市', '镇江市', '泰州市', '宿迁市')
# 公告标题后缀 —— 去掉后才好跟备案名比
SUFFIX = ('招标公告', '招标计划', '中标候选人公示', '中标结果公示', '中标结果', '结果公示',
          '候选人公示', '招标文件', '澄清', '变更', '终止', '流标', '重新招标',
          '施工', '监理', '总承包', 'EPC', 'epc', '勘察', '设计', '采购', '服务')


def norm(s):
    v = str(s or '')
    v = re.sub(r'[（(][^）)]{0,40}[）)]', '', v)   # 去括号注释
    for w in GEO:
        v = v.replace(w, '')
    for w in SUFFIX:
        v = v.replace(w, '')
    for w in FILL:
        v = v.replace(w, '')
    v = re.sub(r'[\s\-_·、，,。.：:；;"\'`]', '', v)
    return v


def load_db():
    """读站点上的列式数据，还原成行。多分片合并。"""
    rows = []
    for f in ('data.chunk-lead.js', 'data.chunk-rest.js', 'data.items.js'):
        p = os.path.join('/workspace/biz-radar', f)
        if not os.path.exists(p):
            continue
        s = open(p, encoding='utf-8').read()
        try:
            d = json.loads(s[s.index('{'):s.rindex('}') + 1])
        except Exception:
            continue
        c = d.get('cols') or {}
        if 't' not in c:
            continue
        n = len(c['t'])
        for i in range(n):
            rows.append({k: v[i] for k, v in c.items() if i < len(v)})
    return rows


def lookup(name, db_idx, db):
    """返回 (grade, row)。grade: A 真匹配 / B 疑似 / '' 无。"""
    n = norm(name)
    if len(n) < 6:
        return '', None
    # ① 完全一致
    if n in db_idx['exact']:
        return 'A', db[db_idx['exact'][n][0]]
    # ② 双向包含：>=10 字才敢做
    #    实测踩过的坑：光有「生活垃圾焚烧飞灰资源化综合利用技改项目」这串核心词重合，
    #    就把「龙游超峰环保…飞灰…项目」匹到了「湖州市生活垃圾焚烧飞灰…项目」——
    #    两个不同业主、不同城市的项目。所以包含匹配还要加一道：地名必须对得上，
    #    或者一方是另一方的真子串（ratio 高）。
    if len(n) >= 10:
        for i, other in db_idx['norm']:
            if len(other) < 10:
                continue
            if other not in n and n not in other:
                continue
            # 子串关系下，短串占比太低就是「核心词撞车」，不是同一个项目
            short, long_ = (n, other) if len(n) <= len(other) else (other, n)
            if len(short) / max(1, len(long_)) < 0.72:
                continue
            return 'B', db[i]
    return '', None


def build_index(db):
    idx = {'exact': {}, 'norm': []}
    for i, r in enumerate(db):
        k = norm(r.get('t'))
        if not k:
            continue
        idx['exact'].setdefault(k, []).append(i)
        idx['norm'].append((i, k))
    return idx
