# -*- coding: utf-8 -*-
"""把本地工具与数据源推到 GitHub 仓库的 tools/ 目录。

════════════════════════════════════════════════════════════════════════
为什么需要这个脚本
════════════════════════════════════════════════════════════════════════
网站只由 Actions 每天重建。构建脚本在仓库里（tools/），但**我这边改的所有
build_web.py / oversea_clients.py / raw/*.json 改动，一直只落在本地沙箱**。

结果就是每次线上看起来都对（因为是 publish_gh.py 直接推 data.*.js），
可 Actions 一跑就会用仓库里的旧脚本重新生成一遍，把新东西冲掉：
  · 巴淡岛 9 条情报 → 消失
  · 切口标签体系 → 消失
  · 排序规则 → 回到「按报道条数」

2026-10-22 实测确认：远端 tools/build_web.py 里连 guess_cut 都没有。

════════════════════════════════════════════════════════════════════════
传什么、不传什么
════════════════════════════════════════════════════════════════════════
传（Actions 真正需要的）：
  · 5 个构建/采集脚本
  · 2 个 Python 数据模块（oversea_clients.py 是 build_web.py 的依赖）
  · raw/ 下的流程数据（客户名单、海外补录、行业映射等）

不传（会出问题）：
  · collect_*.json 采集快照——体积大，每天重建，属于产物不属于源
  · *.bak / *.bak_looop 备份——纯噪音
  · merged.json / industry.json 这类中间产物——每个 run 自己生成

用法：
  python3 push_tools.py            # 只列出将要上传的差异
  python3 push_tools.py --apply    # 真推
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

OWNER = os.environ.get('GH_OWNER', 'zhouqingy')
REPO = os.environ.get('GH_REPO', 'biz-radar')
API = 'https://api.github.com/repos/%s/%s' % (OWNER, REPO)
LOCAL = os.path.dirname(os.path.abspath(__file__))
PREFIX = 'tools'

# 要同步的脚本（都在 tools/ 根下）
SCRIPTS = [
    'build_web.py',        # ← 切口标签、排序、去重、电力配套分组全在这
    'oversea_clients.py',  # ← CUTS / CUT_RULES / guess_cut / 客户名单
    'build_data.py',
    'clean_data.py',
    'build_owner_graph.py',
    'collect_v4.py',
    'scan_detail.py',
    'fill_missing.py',
    'detail_fields.py',
    'seg_biz.py',
    'seg_match.py',
    'seed_batam.py',       # 巴淡岛情报入库
    'seed_cutwhy.py',      # 切口理由
    'scan_awards.py',      # ★ 2026-10-26 新增：中标结果公告全文扫描（反向索引）
    'crawl_fgw.py',        # ★ 2026-10-27 新增：省市发改委项目/能源公示（业务信号补源方案A）
    'crawl_gxt.py',        # ★ 2026-10-27 新增：省工信厅技改/制造强省/产能置换名单（立项线索层）
    'merge_awards.py',     # ★ 2026-10-26 新增：把 award_index 并进 rival_perf
    'crawl_js_prov.py',
    'crawl_ah.py',
    'crawl_rival_perf.py',
]

# raw/early/ 下的静态存量（线上不自动生成，必须推）
RAW_EARLY = [
    'cninfo-legacy-static.json',   # ★ 2026-10-27：巨潮渠道下线后保留的 2 条竞对情报
]

# 要同步的数据源（tools/raw/ 下）
RAW = [
    'oversea_extra.json',   # ★ 巴淡岛这批人工补录，之前一直没进仓库
    'clients_abroad.json',  # 客户卡海外动态（大头）
    'clients_abroad2.json',
    'partners.json',
    'alias_groups.json',
    'notice_extra.json',
    'digest.json',
    'siku.json',
    'wechat_leads.json',
    'industry.json',
    'jiangsu.json',
    'zhejiang.json',
    'anhui.json',
    'shanghai.json',
    'link_health.json',
    'award_index.json',     # ★ 2026-10-26：中标结果反向索引（4.4 MB，CI 复用可省一次全扫）
    'rival_perf.json.gz',   # ★ 2026-10-26：业绩库（含本次新增 294 条）
]


def token_of():
    for p in ('/root/.config/bizradar/gh_token',
              os.path.expanduser('~/.config/bizradar/gh_token')):
        if os.path.isfile(p):
            return open(p).read().strip()
    return os.environ.get('GH_TOKEN', '').strip()


def api(path, token, method='GET', payload=None):
    url = API + path
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode() or '{}'), None
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:300]
        return None, '%s %s' % (e.code, body)
    except Exception as e:
        return None, str(e)


def remote_sha(path, token, cache):
    if path in cache:
        return cache[path]
    d, err = api('/contents/' + path, token)
    if err:
        if '404' not in str(err):
            print('  [warn] 取不到 %s：%s' % (path, err))
        cache[path] = None
        return None
    cache[path] = d.get('sha')
    return cache[path]


def push(local_path, repo_path, token, sha_cache, apply_):
    if not os.path.isfile(local_path):
        return 'MISSING', None
    raw = open(local_path, 'rb').read()
    sha = remote_sha(repo_path, token, sha_cache)
    if not apply_:
        msg = '新增' if not sha else '覆盖'
        return msg, len(raw)
    payload = {'message': '同步工具与数据源：%s' % os.path.basename(repo_path),
               'content': base64.b64encode(raw).decode()}
    if sha:
        payload['sha'] = sha
    d, err = api('/contents/' + repo_path, token, 'PUT', payload)
    if err and 'sha' in err.lower():
        # 并发写导致 sha 变了，重取一次再试
        sha2 = remote_sha(repo_path, token, {})
        payload['sha'] = sha2
        d, err = api('/contents/' + repo_path, token, 'PUT', payload)
    if err:
        return 'FAIL ' + err[:80], len(raw)
    return 'OK', len(raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='真的推送（默认只预览）')
    a = ap.parse_args()
    token = token_of()
    if not token:
        print('缺少 token')
        return 1

    jobs = [(os.path.join(LOCAL, f), '%s/%s' % (PREFIX, f)) for f in SCRIPTS]
    jobs += [(os.path.join(LOCAL, 'raw', f), '%s/raw/%s' % (PREFIX, f)) for f in RAW]
    # raw/early/ 子目录：这里放的是**静态存量**数据，线上工作流不会自己生成，
    # 不推过去线上就永远缺这几条（2026-10-27 巨潮下线时踩到：2 条竞对情报跟着渠道一起消失）。
    # 对比：raw/ 根下的都是每日采集产物，线上自己会重新跑，不需要推。
    jobs += [(os.path.join(LOCAL, 'raw', 'early', f), '%s/raw/early/%s' % (PREFIX, f))
             for f in RAW_EARLY]

    cache, ok, bad, size = {}, 0, 0, 0
    for lp, rp in jobs:
        st, n = push(lp, rp, token, cache, a.apply)
        flag = '✅' if st in ('OK', '新增', '覆盖') else ('⚠️' if st == 'MISSING' else '❌')
        print('  %s %-34s %s' % (flag, rp, st if st in ('OK', '新增', '覆盖', 'MISSING') else st))
        if st in ('OK', '新增', '覆盖'):
            ok += 1
            size += n or 0
        elif st != 'MISSING':
            bad += 1

    print('\n%s %d 个文件（%.1f KB），失败 %d 个'
          % ('已推送' if a.apply else '待推送', ok, size / 1024.0, bad))
    if not a.apply:
        print('加 --apply 真正执行')
    return 0 if bad == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
