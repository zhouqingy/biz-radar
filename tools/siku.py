#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四库一平台 · 企业信用代码查询 · siku.py
=======================================
用户问：「证书不是有企查查或者四库一平台吗？能接入数据就接入，接不了直接跳转过去」

实测结论（2026-10-22）：

  ✅ 能接入 —— 企业列表查询接口，**免 token**：
     https://jzsc.mohurd.gov.cn/APi/webApi/dataservice/query/comp/list
       ?complexname=<企业名>&pg=0&pgsz=15&total=0
     返回 QY_ID / QY_NAME / QY_ORG_CODE（统一社会信用代码）/ QY_REGION_NAME。
     注意路径是 `/APi/webApi/...`（APi 大小写就是这个），前面的
     `/dataservice/...` 是错的，会返回 SPA 外壳 HTML，看着 200 其实是空。

  ❌ 接不了 —— 详情类接口全部要 token：
     compDetail / caDetailList（资质证书）/ regStaffList 都返回
     {"code":408,"message":"token失效"}，而拿 token 要先过人机验证。
     所以「资质证书号」这一项不抓，页面直接给跳转链接。

  ⚠️ 覆盖有限 —— 四库只收录**有建筑/设计/监理资质**的企业。纯设备商、贸易商查不到，
     这类返回 found=False 是正常的，不是接口坏了。

用法：
  python3.11 siku.py                 # 给业主榜 + 供应商榜 + 同业榜补信用代码
  python3.11 siku.py --limit 50      # 只查前 N 家（调试用）
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'raw', 'siku.json')
API = 'https://jzsc.mohurd.gov.cn/APi/webApi/dataservice/query/comp/list'

HDR = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Referer': 'https://jzsc.mohurd.gov.cn/data/company',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'v': '231012',
}


def _norm(name):
    """四库自己的前端会把半角括号转全角，我们也跟着转，否则查不到。"""
    return (name or '').replace('(', '（').replace(')', '）')


def _clean(name):
    """
    洗掉从公告标题里误抽出来的脏名字。实测见过的：
      '&nbsp;江苏省溧阳高新技术产业开发区管理委员会'   ← HTML 实体没解码
      '2026-2027年海宁市江湾能源有限公司'             ← 前面粘了年份范围
      '一、中标人信息无中标人二、联系方式招标人：宁波宝新不锈钢有限公司地址'  ← 整段标题
      '上海临港上电新能源有限公司（拟定单一来源供应商）' ← 括号里是说明不是名字
    这类查四库纯属浪费请求，还会因为超时拖慢整批。
    """
    import html as _html
    import re as _re
    n = _html.unescape(name or '')
    n = n.replace('&nbsp;', ' ').replace('\u3000', ' ').strip()
    # 去掉开头的年份区间、序号
    n = _re.sub(r'^\d{4}\s*[-—~]\s*\d{4}\s*年?', '', n)
    n = _re.sub(r'^[一二三四五六七八九十]+[、.．]', '', n)
    n = _re.sub(r'^\d+[、.．]\s*', '', n)
    # 括号里的「拟定单一来源供应商」「联合体」等说明去掉
    n = _re.sub(r'[（(](拟定|含|联合体|牵头|成员|第[一二三]|中标|成交)[^）)]*[）)]', '', n)
    # 整段标题带「招标人：」的，只取冒号后面到「地址/联系人」之前
    m = _re.search(r'招标人[：:]\s*([^，,。；;\s]{4,40})', n)
    if m and len(n) > 40:
        n = m.group(1)
    # 联合体用顿号并列（'A公司、B公司'）：拆开，全部一起查
    if '、' in n:
        return n   # 交给上层拆
    # 还太长或者含标点，判为无效
    if len(n) > 40 or any(c in n for c in '，,。；;：:'):
        return ''
    return n.strip()


def query(name, timeout=20):
    q = {'complexname': _norm(name), 'pg': '0', 'pgsz': '15', 'total': '0'}
    url = API + '?' + urllib.parse.urlencode(q)
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, headers=HDR)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode('utf-8'))
            break
        except Exception as e:
            last = '%s: %s' % (type(e).__name__, e)
            time.sleep(1.2 * (attempt + 1))
    else:
        return {'found': False, 'err': last}
    if d.get('code') != 200:
        return {'found': False, 'err': 'code=%s' % d.get('code')}
    lst = (d.get('data') or {}).get('list') or []
    if not lst:
        return {'found': False}
    # 取名字最接近的一条：优先完全一致，其次包含关系
    exact = [x for x in lst if x.get('QY_NAME') == _norm(name)]
    pick = exact[0] if exact else lst[0]
    # ⚠ 列表接口只返回这些字段：QY_ID / QY_NAME / QY_ORG_CODE / QY_REGION_NAME / OLD_CODE。
    #   没有法定代表人（QY_FR_NAME 是我一开始猜的，实测全是 None），
    #   法人、注册资本、资质证书号都要调 compDetail 且要 token —— 拿不到就不显示，
    #   页面上宁可少一行，也不要显示一个空壳字段让人以为数据坏了。
    return {
        'found': True,
        'name': pick.get('QY_NAME'),
        'credit': pick.get('QY_ORG_CODE'),      # 统一社会信用代码
        'region': pick.get('QY_REGION_NAME'),
        'oldCode': pick.get('OLD_CODE'),        # 组织机构代码（旧版三证）
        'qyId': pick.get('QY_ID'),              # 详情页跳转用
        'collected': pick.get('COLLECT_TIME'),  # 四库自己的收录时间
        'exact': bool(exact),
        'nHit': len(lst),
    }


def collect_names(min_n=2):
    """要查的企业 = **只查投标方**（同业对手 + 联合体伙伴）。

    2026-10-22 两次收窄，都是被用户问出来的：

    第一次用户问「哪里来的 795 家，有那么伙伴和对手吗」——
      原来把业主 650 + 供应商 221 全塞进来，795 家里 550 个业主只出现过 1 条记录。

    第二次用户直接点破「业主你要他的资质有啥用，人家发包看你资质啊」——
      **这句话是对的，而且比我原来的方案更对。**
      四库一平台是「建筑市场监管」库，收录的是有施工/设计/监理**资质**的企业。
      业主是**发包方**，他不需要资质，他也不靠资质筛人——他看的是自己有没有这个需求、
      有没有钱、今年批了多少项目。拿他的信用代码，对判断「该不该去对接」零帮助。

    所以名单只剩三类，全都与「投标」有关：
      · 竞争对手（65）  —— 同场竞标，资质是硬门槛
      · 联合体伙伴（52）—— 找伙伴就是找它补哪块资质
      · 战绩榜单位（18）—— 已中标单位，同上（与上面有重叠，去重后约 117 家）

    业主、供应商一律不查。业主该看的东西（发了多少标、买什么、跟谁合作）在业主档案里，
    那些数据本库自己有，比信用代码有用得多。
    """
    names = set()

    def add_file(fn, *keys):
        p = os.path.join(ROOT, '..', 'biz-radar', fn)
        if not os.path.exists(p):
            p = os.path.join(ROOT, fn)
            if not os.path.exists(p):
                return
        s = open(p, encoding='utf-8').read()
        s = s[s.index('=') + 1:].rstrip().rstrip(';')
        try:
            D = json.loads(s)
        except Exception:
            return
        for k in keys:
            v = D.get(k)
            if isinstance(v, list):
                for x in v:
                    if isinstance(x, dict) and x.get('name'):
                        names.add(x['name'])

    # 只这三个来源，都是「会去投标的单位」
    add_file('data.org.js', 'competitors', 'partners', 'rivals')

    out = []
    for n in names:
        c = _clean(n)
        if not c:
            continue
        # 联合体拆开：'A、B' → ['A','B']，只留像公司名的片段
        for part in c.split('、'):
            part = part.strip()
            if len(part) >= 6 and ('公司' in part or '院' in part or '集团' in part):
                out.append(part)
    return sorted(set(out))


def _dump(items, hit):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'),
               'n': len(items), 'hit': hit,
               'note': '信用代码来自四库一平台公开查询接口；资质证书号需人机验证，未抓取',
               'items': items},
              open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, OUT)     # 原子替换，读的一方永远读不到半个文件


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--sleep', type=float, default=0.6, help='每次请求间隔，别把对方打挂')
    a = ap.parse_args()

    names = collect_names()
    if a.limit:
        names = names[:a.limit]
    print('待查 %d 家企业' % len(names))

    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8')).get('items', {})
        except Exception:
            old = {}

    items, hit, miss = {}, 0, 0
    for i, n in enumerate(names, 1):
        if n in old and old[n].get('found') is not None and 'err' not in old[n]:
            items[n] = old[n]
            if old[n].get('found'):
                hit += 1
            continue
        r = query(n)
        items[n] = r
        if r.get('found'):
            hit += 1
        else:
            miss += 1
        if i % 20 == 0 or i == len(names):
            print('  %d/%d · 命中 %d · 未收录 %d' % (i, len(names), hit, miss), flush=True)
            # 每 20 家落一次盘：整批要十几分钟，中途被打断不该把结果全丢掉
            _dump(items, hit)
        time.sleep(a.sleep)

    _dump(items, hit)
    print('✅ %s  查了 %d 家 · 命中 %d 家（%.0f%%）' %
          (OUT, len(items), hit, (hit / len(items) * 100) if items else 0))


if __name__ == '__main__':
    main()
