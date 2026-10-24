#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_sites.py —— 批量探测各地交易平台是否可用「同构 ES 接口」

结论会写进 raw/sites_probe.json，供后续扩充采集器时参考。

用法：python3 probe_sites.py
"""
import json, os, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# 已确认可用的省级站 + 待验证的市级站
SITES = [
    # (名称, 省份, 站点根, 备注)
    ('江苏省公共资源交易平台', '江苏', 'http://jsggzy.jszwfw.gov.cn', '省级，已接入'),
    ('浙江省公共资源交易服务平台', '浙江', 'https://ggzy.zj.gov.cn', '省级，已接入'),
    ('苏州市公共资源交易中心', '江苏', 'https://ggzy.suzhou.gov.cn', '市级，与省级同构'),
    ('常州市公共资源交易中心', '江苏', 'https://ggzy.changzhou.gov.cn', '市级'),
    ('合肥市公共资源交易中心', '安徽', 'https://ggzy.hefei.gov.cn', '市级'),
    ('南京市公共资源交易中心', '江苏', 'http://njggzy.nanjing.gov.cn', '市级'),
    ('上海市公共资源交易平台', '上海', 'https://www.shggzy.com', '省级'),
]


def probe(root, timeout=20):
    api = root.rstrip('/') + '/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'
    pm = {
        'token': '', 'pn': 0, 'rn': '3', 'sdt': '2026-08-01', 'edt': '2026-10-21',
        'wd': '热电', 'inc_wd': '', 'exc_wd': '',
        'fields': 'title;categorynum;linkurl', 'cnum': '001',
        'sort': '{"infodate":"0"}', 'ssort': 'title', 'cl': 200,
        'terminal': '', 'condition': None, 'time': None, 'highlights': 'title',
        'statistics': None, 'unionCondition': None, 'opCondition': None,
        'opType': 0, 'accuracy': '', 'noParticiple': '', 'searchRange': None,
        'isBusiness': '1',
    }
    try:
        p = subprocess.run(
            ['curl', '-s', '-m', str(timeout), '-X', 'POST', api,
             '-H', 'Content-Type: application/json;charset=utf-8',
             '-H', 'User-Agent: ' + UA,
             '-d', json.dumps(pm, ensure_ascii=False)],
            capture_output=True, text=True, errors='ignore', timeout=timeout + 8)
    except Exception as e:
        return {'ok': False, 'why': '请求异常: %s' % str(e)[:60]}
    out = (p.stdout or '').strip()
    if not out:
        return {'ok': False, 'why': '无响应'}
    try:
        o = json.loads(out)
    except Exception:
        return {'ok': False, 'why': '非 JSON: ' + out[:80]}
    # 兼容双层嵌套 {code, content:"{...}"}
    inner = o.get('content')
    if isinstance(inner, str):
        try:
            o = json.loads(inner)
        except Exception:
            pass
    r = o.get('result') or {}
    if not isinstance(r, dict):
        return {'ok': False, 'why': 'result 结构异常'}
    recs = r.get('records') or []
    total = r.get('totalcount')
    sample = []
    for x in recs[:2]:
        t = x.get('title') or ''
        t = t.split('<')[0]
        sample.append(t[:40])
    return {'ok': bool(total), 'totalcount': total, 'got': len(recs), 'sample': sample}


def main():
    out = []
    for name, prov, root, note in SITES:
        r = probe(root)
        r.update({'name': name, 'prov': prov, 'root': root, 'note': note})
        out.append(r)
        flag = '✅' if r.get('ok') else '❌'
        extra = ('total=%s 样例:%s' % (r.get('totalcount'), r.get('sample', [None])[0])
                 if r.get('ok') else r.get('why', ''))
        print('%-4s %-26s %s' % (flag, name, extra))
        time.sleep(0.4)
    json.dump({'at': time.strftime('%Y-%m-%d %H:%M'), 'sites': out},
              open(os.path.join(RAW, 'sites_probe.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    ok = [x for x in out if x.get('ok')]
    print('\n可用 %d / %d' % (len(ok), len(out)))
    for x in ok:
        print('  ✅', x['prov'], x['name'], x['root'])


if __name__ == '__main__':
    main()
