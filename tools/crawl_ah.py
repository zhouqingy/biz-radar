#!/usr/bin/env python3
"""安徽省公共资源交易平台采集器（ggzy.ah.gov.cn）
═══════════════════════════════════════════════
2026-10-24 破解：列表是服务端渲染 GET /jsgc/list?pageNo=N（翻页有效），
bulletinNature: 1=招标公告 3=中标结果（2=候选人，站内筛选不单列）。
意外收获：/approveItem/indexlist?approvelLevel=N 返回 JSON 立项批复
（projectName/approvelDeptName/approvelDate）—— 用户要的「审批平台」源头。
数据 schema 与 nt_lifecycle.json 一致（items[{id,city,cat,t,d,url,...}]），
build_data/build_web 的出口 A/B 直接复用。
合法合规：法定公开公告，0.35s/请求，不碰登录，仅内部决策用。
"""
import json, os, re, sys, time, html, argparse, hashlib, subprocess

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
OUT = os.path.join(RAW, 'ah_lifecycle.json')
BAD_T = ('转让', '挂牌', '竞价', '拍卖', '竞买', '产权交易', '报废处置',
         '车辆', '废旧物资', '物资处置')

NATURE = {1: 'notice', 2: 'cand', 3: 'result'}


def fetch(url, data=None):
    cmd = ['curl', '-s', '-m', '25', url, '-H', 'User-Agent: ' + UA,
           '-H', 'Referer: https://ggzy.ah.gov.cn/jsgc/list']
    if data is not None:
        cmd += ['-X', 'POST', '-H', 'Content-Type: application/x-www-form-urlencoded',
                '--data', data]
    p = subprocess.run(cmd, capture_output=True)
    return p.stdout.decode('utf-8', 'ignore')


def parse_list(page_html):
    """一页 10 条：<a newDetail...><span class="area">【市-县-类型】</span>
       <span class="title" title="全标题">…</span></a><span class="date">日期</span>"""
    out = []
    for m in re.finditer(
            r'newDetail\?guid=([a-f0-9-]{20,})&(?:amp;)?tenderProjectType=([^&"]+)&(?:amp;)?bulletinNature=(\d)[^"]*"[^>]*>\s*'
            r'<span[^>]*class="area[^"]*"[^>]*>【([^】]*)】</span>\s*'
            r'<span[^>]*class="title[^"]*"[^>]*title="([^"]{6,200})"', page_html):
        guid, tpt, nat, area, title = m.groups()
        t = html.unescape(title).strip()
        if not t or any(b in t[:30] for b in BAD_T):
            continue
        dm = re.search(r'class="date[^"]*"[^>]*>\s*(20\d\d-\d\d-\d\d)', page_html[m.end():m.end()+400])
        out.append({
            'guid': guid, 'nat': int(nat), 'area': html.unescape(area).strip(),
            't': t, 'd': dm.group(1) if dm else '',
            'url': 'https://ggzy.ah.gov.cn/jsgc/newDetail?guid=%s&tenderProjectType=%s&bulletinNature=%s'
                   % (guid, tpt, nat),
        })
    return out


def crawl_list(nat, stop_date, max_pages=3000):
    """POST currentPage 翻页（GET pageNo 无效，页面 pagination() 提交表单）"""
    seen, out, last = set(), [], ''
    empty = 0
    for pg in range(1, max_pages):
        raw = fetch('https://ggzy.ah.gov.cn/jsgc/list',
                    'currentPage=%d&bulletinNature=%d' % (pg, nat))
        rows = parse_list(raw)
        if not rows:
            empty += 1
            if empty >= 3:
                break
            continue
        empty = 0
        stop = False
        for x in rows:
            if x['guid'] in seen:
                continue
            seen.add(x['guid'])
            if not x['d']:
                continue
            if x['d'] < stop_date:
                stop = True
                break
            last = max(last, x['d'])
            out.append(x)
        if stop or pg % 50 == 0:
            print('  nature=%d page %d, 累计 %d, 最新 %s' % (nat, pg, len(out), last), flush=True)
        if stop:
            break
        time.sleep(0.35)
    return out


def crawl_approvals():
    """立项批复（发改委端）——审批平台源头，三个层级全拉"""
    out = []
    for lv in (1, 2, 3):
        try:
            raw = fetch('https://ggzy.ah.gov.cn/approveItem/indexlist?approvelLevel=%d' % lv)
            arr = json.loads(raw)
            for x in arr or []:
                out.append({
                    'guid': x.get('guid') or '',
                    't': (x.get('projectName') or '').strip(),
                    'd': (x.get('approvelDate') or '')[:10],
                    'dept': (x.get('approvelDeptName') or '').strip(),
                    'code': (x.get('projectCode') or '').strip(),
                    'url': 'https://ggzy.ah.gov.cn/approveItem/detail?guid=' + (x.get('guid') or ''),
                    'nat': 0,
                })
        except Exception as e:
            print('  审批 lv%d 失败: %s' % (lv, str(e)[:60]))
        time.sleep(0.3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill-days', type=int, default=365)
    ap.add_argument('--approvals', type=int, default=1)
    args = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    old = {'items': []}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            pass
    items = {x['id']: x for x in old.get('items') or []}

    stop = time.strftime('%Y-%m-%d', time.localtime(time.time() - args.backfill_days * 86400))
    print('[安徽] 回补至 %s' % stop)

    for nat, cat in NATURE.items():
        rows = crawl_list(nat, stop)
        new = 0
        for x in rows:
            rec = {
                'id': '安徽:' + hashlib.md5((x['t'] + x['d']).encode()).hexdigest()[:12],
                'city': '安徽', 'cat': cat, 't': x['t'], 'd': x['d'],
                'url': x['url'], 'rg': '安徽', 'area': x['area'],
            }
            if rec['id'] not in items:
                items[rec['id']] = rec
                new += 1
        print('  nature=%d → %d 条(新 %d) 累计 %d' % (nat, len(rows), new, len(items)))
        json.dump({'updated': time.strftime('%F %T'), 'items': list(items.values())},
                  open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)

    if args.approvals:
        rows = crawl_approvals()
        new = 0
        for x in rows:
            if not x['t']:
                continue
            rec = {
                'id': '皖批:' + hashlib.md5((x['t'] + x['d']).encode()).hexdigest()[:12],
                'city': '安徽', 'cat': 'approval', 't': x['t'], 'd': x['d'],
                'url': x['url'], 'rg': '安徽', 'dept': x['dept'], 'code': x['code'],
            }
            if rec['id'] not in items:
                items[rec['id']] = rec
                new += 1
        print('  立项批复 → %d 条(新 %d) 累计 %d' % (len(rows), new, len(items)))

    data = {'updated': time.strftime('%F %T'), 'items': list(items.values())}
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('✅ 共 %d 条 → %s' % (len(data['items']), OUT))


if __name__ == '__main__':
    main()
