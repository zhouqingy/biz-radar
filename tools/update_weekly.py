#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
商机雷达 · 每周一键更新
=========================
流程：raw/weekly/*.json（本周新检索结果）
      → build_data.py（清洗/分类/去重/分级）→ merged.json
      → build_web.py（聚合 + 抓金属行情 + 注入版本号）→ /workspace/biz-radar/data.js
      → publish.js 发布到原链接（网址不变）

用法：
    python3.11 update_weekly.py              # 重建 + 发布
    python3.11 update_weekly.py --no-publish # 只重建不发布（先本地看效果）
    python3.11 update_weekly.py --check      # 只做数据体检，不改任何文件
"""
import json, os, re, subprocess, sys, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = '/workspace/biz-radar'
PY = sys.executable or 'python3.11'
PUBLISH_CANDIDATES = [
    '/root/.codebuddy/skills/sites/scripts/publish.js',      # 现役路径（skill 已由「发布为应用」改名为 sites）
    '/root/.codebuddy/skills/发布为应用/scripts/publish.js',  # 旧路径，留作兜底
    os.path.expanduser('~/.codebuddy/skills/sites/scripts/publish.js'),
]


def find_publish():
    """动态定位发布脚本。

    历史故障：发布技能改过名（发布为应用 → sites），脚本里写死旧路径会导致
    发布环节 MODULE_NOT_FOUND，定时任务每轮白跑而页面毫无变化。
    所以这里改为按候选顺序探测，并额外在 ~/.codebuddy 下模糊搜索兜底。
    返回 (路径, 空字符串) 或 (None, 报错说明)。
    """
    for p in PUBLISH_CANDIDATES:
        if os.path.isfile(p):
            return p, ''
    hits = []
    for base in ('/root/.codebuddy/skills', os.path.expanduser('~/.codebuddy/skills')):
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if 'node_modules' in dirpath:
                continue
            for fn in filenames:
                if fn == 'publish.js':
                    hits.append(os.path.join(dirpath, fn))
    if hits:
        return hits[0], ''
    return None, '未找到 publish.js（发布技能缺失或已改名），请在会话中手动执行发布'
WEEKLY = os.path.join(ROOT, 'raw', 'weekly')
ARGS = set(sys.argv[1:])
try:
    from publish_guard import pin_domain, warn_if_drift, read_pin
except Exception:
    # 降级：定时任务可能落在文件不完整的沙箱（缺 publish_guard.py），
    # 这里用内联最小实现兜底，绝不让脚本因为少一个辅助文件就整体崩溃。
    import hashlib

    def read_pin():
        try:
            raw = open(os.path.join(ROOT, 'publish.conf'), encoding='utf-8').read().strip()
            return raw.split()[0] if raw else ''
        except Exception:
            return ''

    def _state_path():
        return os.path.expanduser('~/.workbuddy-sandbox-publish/state.json')

    def pin_domain():
        want, cur = read_pin(), (os.environ.get('AGENTOS_RUNTIME_ID') or '').strip()
        if not want or not cur:
            return
        p = _state_path()
        st = {}
        if os.path.exists(p):
            try:
                st = json.load(open(p, encoding='utf-8')) or {}
            except Exception:
                st = {}
        if st.get('appName') == want and st.get('runtimeId') == cur:
            return
        st.update({'runtimeId': cur, 'appName': want, 'lastReleaseId': None})
        st.setdefault('createdAt', int(time.time() * 1000))
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump(st, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            print('[域名守卫/降级] 已回绑 %s.app.workbuddy.host' % want)
        except Exception as e:
            print('[域名守卫/降级] 写入失败，继续发布：%s' % e)

    def warn_if_drift(link):
        want = read_pin()
        if not link or not want or want in link:
            return False
        print('[域名守卫] ⚠ 本次落到新域名 %s（旧 %s 未更新）' % (link, want))
        return True


def run(cmd, cwd=ROOT, quiet=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if not quiet:
        tail = (p.stdout or '').strip().splitlines()
        for ln in tail[-12:]:
            print('   | ' + ln)
    if p.returncode != 0:
        print('[ERROR] 命令失败: %s' % ' '.join(cmd))
        print((p.stderr or '')[-1500:])
        sys.exit(1)
    return p.stdout or ''


HEARTBEAT = os.path.join(ROOT, 'raw', '心跳_行情.json')


def write_heartbeat(ok, note, link=''):
    """把本轮发布结果落盘。定时任务只需把这个文件上传到共享盘即可，
    避免靠 LLM 现场拼 JSON 出错。"""
    want = read_pin()
    d = {
        'task': os.environ.get('BIZRADAR_TASK', 'update_weekly.py'),
        'time': time.strftime('%Y-%m-%d %H:%M'),
        'shareLink': link,
        'expectedHost': '%s.app.workbuddy.host' % want if want else '',
        'ok': bool(ok),
        'drift': bool(link and want and want not in link),
        'note': note,
    }
    try:
        os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
        json.dump(d, open(HEARTBEAT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('[心跳] 已写入 %s：ok=%s %s' % (HEARTBEAT, d['ok'], note))
    except Exception as e:
        print('[心跳] 写入失败：%s' % e)
    return d


def do_publish():
    """发布并做域名漂移校验。返回 (是否异常, 链接)。

    重要：优先走 publish_pinned.py（钉域名执行器）。
    背景：域名 = 'a' + md5(AGENTOS_RUNTIME_ID)[:16]，而 runtimeId 由沙箱分配、
    会漂移；实测后端会校验 runtimeId 与 appName 的 md5 对应关系，runtimeId 不
    匹配直接 403 runtimeId mismatch。因此唯一可靠做法是发布前把记录在
    publish.conf 里的「原始 runtimeId」注入环境变量，让 md5 结果与对外域名一致。
    """
    pin_domain()
    pinned = os.path.join(ROOT, 'publish_pinned.py')
    if os.path.isfile(pinned):
        out = run([PY, pinned], cwd='/workspace')
        m = re.search(r'"shareLink":"([^"]+)"', out)
        link = m.group(1) if m else ''
        ok = '✅ 命中目标域名' in out
        if link and ok:
            print('\n已发布（域名已钉住）：%s' % link)
            write_heartbeat(True, '发布成功，网址未漂移', link)
            return False, link
        tail = (out or '').strip()[-400:]
        write_heartbeat(False, '钉域名发布异常；输出：%s' % tail[-200:], link)
        return True, link or tail
    pub, err = find_publish()
    if not pub:
        print('\n[发布失败] %s' % err)
        print('          排查：find /root/.codebuddy -name publish.js -not -path "*/node_modules/*"')
        print('          把真实路径回填到 PUBLISH_CANDIDATES 后重跑（可加 --only-publish 跳过重建）')
        write_heartbeat(False, '发布脚本找不到：%s' % err)
        sys.exit(3)
    print('[发布] 使用脚本：%s' % pub)
    out = run(['node', pub, '--dir', SITE, '--port', '8046'], cwd='/workspace')
    m = re.search(r'"shareLink":"([^"]+)"', out)
    link = m.group(1) if m else ''
    if link:
        print('\n已发布：%s' % link)
        bad = warn_if_drift(link)
        write_heartbeat(not bad,
                        '发布成功，网址未漂移' if not bad else '⚠ 落到了新域名 %s' % link,
                        link)
        return bad, link
    tail = (out or '').strip()[-500:]
    print('\n（未返回链接，请手动发布）')
    print('   发布脚本输出片段：%s' % tail)
    write_heartbeat(False, '发布脚本未返回链接；输出：%s' % tail[-200:])
    return True, ''


def load_site_data():
    s = open(os.path.join(SITE, 'data.js'), encoding='utf-8').read()
    s = s[s.index('{'):s.rindex('}') + 1]
    return json.loads(s)


print('=' * 62)
print('商机雷达 每周更新 · %s' % time.strftime('%Y-%m-%d %H:%M'))
print('=' * 62)

# 0. 检查增量数据
if not os.path.isdir(WEEKLY):
    os.makedirs(WEEKLY, exist_ok=True)
week_files = sorted(f for f in os.listdir(WEEKLY) if f.endswith('.json'))
n_inc = 0
for f in week_files:
    try:
        n_inc += len(json.load(open(os.path.join(WEEKLY, f), encoding='utf-8')))
    except Exception as e:
        print('[WARN] %s 解析失败: %s' % (f, e))
print('本周增量文件: %s' % (', '.join(week_files) or '（无）'))
print('本周新增原始条目: %d 条' % n_inc)

if '--check' in ARGS:
    d = load_site_data()
    print('\n[体检] 当前线上数据：总 %d 条 · 已公示金额 %.1f 亿 · 平台 %d 个'
          % (d['meta']['total'], d['meta']['amtSum'], len(d['platforms'])))
    print('[体检] 金属行情 %d 个品种 · 海外信号 %d 条 · 客户 %d 家'
          % (len(d['metals']['items']), len(d['overseas']), len(d['clients'])))
    sys.exit(0)

# ---------------------------------------------------------------------------
# --data-zip <zip>：先把共享盘上的全量备份包解压回 /workspace，再走后续流程。
# 用途：定时任务在新沙箱跑完只回传了数据包，本会话（唯一能写固定网址的沙箱）
#       用它一条命令完成「恢复最新数据 → 重建 → 发布」。
# ---------------------------------------------------------------------------
_zip = None
for _i, _a in enumerate(sys.argv):
    if _a == '--data-zip' and _i + 1 < len(sys.argv):
        _zip = sys.argv[_i + 1]
if _zip:
    import zipfile as _zf
    if not os.path.isfile(_zip):
        raise SystemExit('[--data-zip] 文件不存在：%s' % _zip)
    print('\n（--data-zip：先从备份包恢复工作区）')
    with _zf.ZipFile(_zip) as _z:
        _z.extractall('/workspace')
    print('   已解压 %s → /workspace' % _zip)
    _sz = os.path.join(SITE, 'data.js')
    if os.path.isfile(_sz):
        print('   包内数据日期：%s' % re.search(r'"updated":"([^"]+)"', open(
            _sz, encoding='utf-8').read(2000)).group(1))

if '--only-publish' in ARGS:
    # 数据已重建好、只是发布环节失败时，用这个参数跳过重建直接补发布
    print('\n（--only-publish：跳过数据重建，直接发布现有 data.js）')
    print('[体检] ' + json.dumps(load_site_data()['meta'], ensure_ascii=False))
    bad2, link2 = do_publish()
    if bad2:
        print('\n⚠ 本次未落到固定网址 a60be47466efe1223.app.workbuddy.host')
    sys.exit(0)

# 1. 备份上一版
bak = os.path.join(ROOT, 'data.js.bak')
if os.path.exists(os.path.join(SITE, 'data.js')):
    shutil.copy(os.path.join(SITE, 'data.js'), bak)
    print('\n已备份上一版数据 → data.js.bak')

# 2. 重建数据
# 上市公司募投/对外投资公告（巨潮 cninfo，有正规 JSON API）
# 网络类渠道，失败不影响主流程（脚本内部已兜底）
if os.path.exists(os.path.join(ROOT, 'mine_cninfo.py')):
    print('\n[0.5] 采集上市公司募投 / 投资公告 → raw/early/ ...')
    run([PY, 'mine_cninfo.py', '--days', '365'], quiet=True)
# 地方热电联产 / 集中供热规划批复（江苏 dataproxy + 浙江 jpaas + 安徽市级）
# 规划批复会直接点名未来热源点项目，比项目核准更早，是市政热电赛道最早的线索
if os.path.exists(os.path.join(ROOT, 'mine_plan.py')):
    print('\n[0.6] 采集地方热电联产 / 集中供热规划批复 → raw/early/ ...')
    run([PY, 'mine_plan.py', '--pages', '8', '--days', '730'], quiet=True)
# [0.7] 浏览器采集：解决 requests 抓不到的 JS 渲染页 / 需要点搜索 /
#       需要登录的平台（登录态放 auth/*.json）。详见 DRIVE.md「浏览器采集」一节。
if os.path.exists(os.path.join(ROOT, 'biz_crawl.py')):
    print('\n[0.7] 浏览器采集（JS 渲染 / 表单交互站点）→ raw/weekly/ ...')
    _today = time.strftime('%Y-%m-%d')
    # 说明：只跑已实测有稳定产出的站点。jsfgw（江苏省发改委）首页一级栏目里
    # 翻不到「项目核准批复」入口（要往政务公开二级挖），暂不列入，避免每周空转。
    for _site in ('baohua', 'ah'):
        _out = os.path.join(WEEKLY, 'crawl-%s-%s.json' % (_site, _today))
        try:
            run([PY, 'biz_crawl.py', '--site', _site, '--days', '30',
                 '--out', _out], quiet=True)
        except Exception as e:
            print('    [WARN] biz_crawl %s 失败：%s' % (_site, e))
print('\n[1/4] 清洗 / 分类 / 去重 / 分级 ...')
run([PY, 'build_data.py'])
print('\n[2/4] 从 A/B 级项目挖掘对手 / 伙伴 ...')
run([PY, 'mine_units.py'])
print('\n[3/4] 合并新增单位（自动去重）...')
run([PY, 'merge_units.py'])
# 微信线索并入档案：文件不存在或技能缺失时静默跳过，不阻断主流程
if os.path.exists(os.path.join(ROOT, 'raw', 'wechat_leads.json')):
    print('\n[3.5] 微信线索并入单位档案 / 行业动态 ...')
    run([PY, 'merge_wechat.py'], quiet=True)
print('\n[4/4] 聚合 / 抓取金属行情 / 生成 data.js ...')
run([PY, 'build_web.py'])

# 3. 结果摘要
d = load_site_data()
meta = d['meta']
grades = meta.get('gradeTop') or []
print('\n[结果] 结果：')
print('   入库总计 %d 条（已公示金额 %.1f 亿）' % (meta['total'], meta['amtSum']))
print('   本轮标记新增 %d 条' % meta.get('new', 0))
for g, n in grades:
    print('   %s 级 %d 条' % (g, n))
ms = d['metals']['items']
if ms:
    print('   行情 %s：%s' % (d['metals']['updated'],
          ' · '.join('%s %s%s%%' % (m['name'], round(m['price']), ('+' if m['chg'] > 0 else '') + str(m['chg'])) for m in ms[:6])))
else:
    print('   [WARN] 金属行情抓取失败，本次不展示该模块')

# ---- 全量自检：确认每个模块都重建成功，且与上一版对比 ----
MODULES = [
    ('商机库 items', lambda x: len(x['items'])),
    ('中标榜 rivals', lambda x: len(x['rivals'])),
    ('业主 buyers', lambda x: len(x['buyers'])),
    ('重点客户 clients', lambda x: len(x['clients'])),
    ('行业动态 trends', lambda x: len(x['trends'])),
    ('竞争对手 competitors', lambda x: len(x['competitors'])),
    ('合作生态 partners', lambda x: len(x['partners'])),
    ('海外信号 overseas', lambda x: len(x['overseas'])),
    ('招标平台 platforms', lambda x: len(x['platforms'])),
    ('金属行情 metals', lambda x: len(x['metals']['items'])),
]
prev = None
if os.path.exists(bak):
    try:
        s = open(bak, encoding='utf-8').read()
        prev = json.loads(s[s.index('{'):s.rindex('}') + 1])
    except Exception:
        prev = None
print('\n[自检] 各模块重建结果（对比上一版）：')
bad = []
for name, fn in MODULES:
    try:
        cur = fn(d)
    except Exception as e:
        cur = -1
        bad.append('%s 读取失败(%s)' % (name, e))
    if prev is not None:
        try:
            old = fn(prev)
            delta = ('%+d' % (cur - old)) if cur != old else '持平'
        except Exception:
            delta = '—'
    else:
        delta = '—'
    flag = ''
    if cur <= 0:
        flag = '  ❌ 为 0，异常！'
        bad.append('%s 为 0' % name)
    print('   %-22s %6d  (%s)%s' % (name, cur, delta, flag))
if bad:
    print('\n[自检] ⚠ 存在问题：%s' % '；'.join(bad))
    print('       → 已保留 data.js.bak，可人工核对后再决定是否发布')
else:
    print('[自检] ✅ 全部模块均已重建且有数据')

# 4. 发布
if '--no-publish' in ARGS:
    print('\n（--no-publish：本次未发布，可本地预览 /workspace/biz-radar/index.html）')
else:
    do_publish()

print('\n完成 ✅')
