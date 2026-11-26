#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
合并「情报精选」两个源 → 写入 data.js 的 digest 字段。
  1) rival_news.json  竞对官网（自动抓）
  2) wechat_digest.json 微信深度稿（抓全文后分级）
去重用标题相似度（同一事件常被官网多栏目/媒体号重复报道），保留日期最新的一条。
"""
import os, re, json, difflib, time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')

# data.js 位置。三种环境：
#   · 本地沙箱        tools/ 的同级有 biz-radar/ → tools/../biz-radar/data.js
#   · GitHub Actions  tools/ 直接躺在仓库根下   → tools/../data.js
# 原来写死第一种，Actions 上就变成 <repo>/biz-radar/data.js（多套一层），
# 2026-11-04 首次跑 digest.yml 报 FileNotFoundError 就是这个原因。
# 和 build_web.py 保持一致：优先认 BIZ_OUT。
def _out_file(name):
    out = os.environ.get('BIZ_OUT')
    if out:
        return os.path.join(out, name)
    a = os.path.join(os.path.dirname(ROOT), 'biz-radar', name)
    if os.path.exists(a):
        return a
    return os.path.join(os.path.dirname(ROOT), name)


DATA = _out_file('data.js')
NEWS = _out_file('data.news.js')
RIVAL = os.path.join(RAW, 'rival_news.json')
WX = os.path.join(RAW, 'wechat_digest.json')
SIM = 0.72


def load(p, d):
    if not os.path.exists(p):
        return d
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


def norm(t):
    t = re.sub(r'^[\u4e00-\u9fa5A-Za-z0-9·、]{2,12}[：:]\s*', '', t or '')
    t = re.sub(r'[\s：:，,。、（）()《》「」""\'\'·|｜—\-]', '', t)
    return t


def main():
    rv = load(RIVAL, {'items': [], 'n_src': 0})
    wx = load(WX, {'items': []})
    allx = list(rv.get('items', [])) + list(wx.get('items', []))
    # 微信稿优先（信息密度更高），再按日期倒序
    allx.sort(key=lambda z: (0 if z.get('srcKind') == '微信' else 1, z.get('d') or ''), reverse=False)
    allx.sort(key=lambda z: (z.get('d') or ''), reverse=True)

    kept, keys = [], []
    for x in allx:
        n = norm(x['t'])
        dup = False
        for k in keys:
            if difflib.SequenceMatcher(None, n, k).ratio() >= SIM:
                dup = True
                break
        if dup:
            continue
        keys.append(n)
        kept.append(x)

    # 2026-11-26：精选只保留主业竞对动作、可核验官网来源，并补 URL 日期。
    from news_rules import clean_digest
    s0 = open(DATA, encoding='utf-8').read()
    competitors = json.loads(s0[s0.find('{'):s0.rfind('}') + 1]).get('competitors', [])
    kept, archived = clean_digest(kept, competitors)
    print('精选口径过滤：保留 %d 条，归档 %d 条（原始 rival/wechat 文件不删）' % (len(kept), len(archived)))

    # 只替换 digest 字段，其余业务模块保持原值；绝不用 merged.snapshot 重建整站。
    # data.js 是整包回退，data.news.js 是页面实际懒加载模块，两者必须同事务更新。
    payload = {'updated': time.strftime('%Y-%m-%d %H:%M'),
               'n_src': rv.get('n_src', 0), 'archived': len(archived), 'items': kept}
    json.dump(payload, open(os.path.join(RAW, 'digest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    sizes = []
    for path in (DATA, NEWS):
        s = open(path, encoding='utf-8').read()
        d = json.loads(s[s.find('{'):s.rfind('}') + 1])
        before = {k: v for k, v in d.items() if k != 'digest'}
        d['digest'] = dict(payload)
        assert {k: v for k, v in d.items() if k != 'digest'} == before, \
            '除 digest 外的数据发生变化，拒绝写盘：' + path
        prefix = s[:s.find('{')]
        out = prefix + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + ';\n'
        tmp = path + '.tmp'
        open(tmp, 'w', encoding='utf-8').write(out)
        os.replace(tmp, path)
        sizes.append(len(out))

    from collections import Counter
    print('合并前 %d 条 → 相似度去重后 %d 条' % (len(allx), len(kept)))
    print('来源:', dict(Counter(x.get('srcKind') for x in kept)))
    print('分级:', dict(Counter(x['level'] for x in kept)))
    print('分类:', dict(Counter(x['tag'] for x in kept)))
    print('data.js + data.news.js 已同步更新（%.2f MB / %.2f MB），其余字段未改'
          % (sizes[0] / 1048576.0, sizes[1] / 1048576.0))


if __name__ == '__main__':
    main()
