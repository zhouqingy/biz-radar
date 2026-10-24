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
DATA = os.path.join(os.path.dirname(ROOT), 'biz-radar', 'data.js')
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

    # 落盘供 build_web.py 重建时保留（否则下次全量重建会把精选清空）
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'n_src': rv.get('n_src', 0),
               'items': kept}, open(os.path.join(RAW, 'digest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    s = open(DATA, encoding='utf-8').read()
    d = json.loads(s[s.find('{'):s.rfind('}') + 1])
    d['digest'] = {'updated': time.strftime('%Y-%m-%d %H:%M'),
                   'n_src': rv.get('n_src', 0), 'items': kept}
    out = 'window.DATA=' + json.dumps(d, ensure_ascii=False, separators=(',', ':')) + ';'
    open(DATA, 'w', encoding='utf-8').write(out)

    from collections import Counter
    print('合并前 %d 条 → 相似度去重后 %d 条' % (len(allx), len(kept)))
    print('来源:', dict(Counter(x.get('srcKind') for x in kept)))
    print('分级:', dict(Counter(x['level'] for x in kept)))
    print('分类:', dict(Counter(x['tag'] for x in kept)))
    print('data.js 已写入 %.2f MB' % (len(out) / 1048576.0))


if __name__ == '__main__':
    main()
