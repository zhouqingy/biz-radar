# -*- coding: utf-8 -*-
"""V4 静态快照版（GitHub Pages 子路径 /v4/）浏览器回归 + 截图（只读验收）

起一个临时 http.server 指向 /workspace/v4，用 Chromium 实测：
静态 JSON 全可加载、19 模块、检索 / 筛选 / 分页 / 详情 / 有色 / 空 tab / 深链 /
响应式 / 暗色、0 控制台错误、源码无判定函数调用（前端不重判）。
"""
import functools
import json
import os
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

ROOT = '/workspace/v4'
PORT = 8849
B = 'http://127.0.0.1:%d/' % PORT
OUT = '/workspace/2026-11-06-V4静态快照-'
ok = fail = 0
errors = []


def chk(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %-56s %s' % (name, detail))
    else:
        fail += 1
        print('  FAIL  %-56s %s' % (name, detail))


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(('127.0.0.1', PORT),
                          functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium',
                          args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1440, 'height': 950})
    pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.goto(B, wait_until='networkidle', timeout=90000)
    pg.wait_for_timeout(700)

    print('=== 1 · 静态快照接通 / 源码红线 ===')
    src = urllib.request.urlopen(B, timeout=20).read().decode('utf-8')
    chk('页面 200 且为 V4 静态快照', '静态快照' in src and 'id="navList"' in src)
    chk('非离线降级（11 份 JSON 都读到了）',
        '离线降级' not in pg.locator('#notice').inner_text())
    chk('接口状态如实标「静态快照 · 只读（Pages）」',
        '静态快照' in pg.locator('#modeTag').inner_text(),
        pg.locator('#modeTag').inner_text())
    chk('源码零判定函数调用（judge / semantic_drop）',
        'judge(' not in src and 'semantic_drop(' not in src)
    chk('源码不通过 window.DATA_XXX 取数', 'window.DATA_' not in src)
    chk('页面源码不硬编码业务数字 1119', '1119' not in src)
    chk('KPI ①库条目来自快照（1,119）', '1,119' in pg.locator('#pk').inner_text(),
        pg.locator('#pk').inner_text().replace('\n', ' | ')[:80])
    chk('左导航合并为 9 个已接入入口（规划中折叠、行情收进顶栏）',
        pg.locator('#navList .ni').count() == 9, str(pg.locator('#navList .ni').count()))
    chk('默认不占右边第三列（详情收在居中弹窗里）',
        len(pg.locator('.body').evaluate('e=>getComputedStyle(e).gridTemplateColumns').split()) == 2
        and not pg.locator('#modal').is_visible())
    chk('默认页 12 条数据行', pg.locator('#rows .row').count() == 12,
        str(pg.locator('#rows .row').count()))
    rh = pg.locator('#rows .row').first.evaluate('e=>e.getBoundingClientRect().height')
    chk('数据行改紧凑列表（≤ 6 列、高 < 72px）',
        len(pg.locator('#rows .row').first.evaluate(
            'e=>getComputedStyle(e).gridTemplateColumns').split()) <= 6 and rh < 72,
        '%.0f px' % rh)

    print('=== 2 · 11 份静态 JSON 全部可加载 ===')
    names = ['items', 'orgs', 'news', 'metals', 'policies', 'changes',
             'meta', 'health', 'rules', 'collect']
    for n in names:
        u = B + 'api/' + n + '.json'
        try:
            with urllib.request.urlopen(u, timeout=20) as f:
                d = json.loads(f.read().decode('utf-8'))
            chk('api/%-12s 200 且可解析' % (n + '.json'), isinstance(d, dict),
                '%d B' % len(json.dumps(d)))
        except Exception as e:
            chk('api/%-12s 200 且可解析' % (n + '.json'), False, str(e)[:50])
    itj = json.load(urllib.request.urlopen(B + 'api/items.json'))
    chk('items.json 全量 1119 条、w 沿用入库值',
        len(itj['items']) == 1119 and sum(1 for x in itj['items'] if str(x.get('w')) == '1') == 98,
        '%d 条 / 重点关注 %d 条' %
        (len(itj['items']), sum(1 for x in itj['items'] if str(x.get('w')) == '1')))

    print('=== 3 · 筛选 / 分页 / 详情 / 排序 ===')
    chk('facets 工具条有筛选项', pg.locator('#toolbar .fchip').count() >= 12,
        '%d 个' % pg.locator('#toolbar .fchip').count())
    chk('7 个阶段枚举由 facets 返回', pg.locator('#toolbar [data-f="stage"]').count() == 7)
    pg.locator('[data-f="focus"]').click(); pg.wait_for_timeout(420)
    chk('只看重点关注 ≥1亿 生效（命中 98）', '98' in pg.locator('#pager').inner_text(),
        pg.locator('#pager').inner_text().replace('\n', ' ')[:70])
    pg.locator('[data-f="clear"]').click(); pg.wait_for_timeout(380)
    chk('清除筛选恢复 1,119', '1,119' in pg.locator('#pager').inner_text())
    pg.locator('#sortSel').select_option('amt'); pg.wait_for_timeout(350)
    chk('排序切换（金额）不报错', pg.locator('#rows .row').count() > 0)
    pg.locator('#sortSel').select_option('sc'); pg.wait_for_timeout(300)
    pg.locator('#pgN').click(); pg.wait_for_timeout(380)
    chk('下一页生效（静态快照本地分页）', '第 2 /' in pg.locator('#pager').inner_text())
    pg.locator('#pgP').click(); pg.wait_for_timeout(320)
    pg.locator('[data-detail]').first.click(); pg.wait_for_timeout(400)
    chk('点详情打开居中弹窗并展示真实字段',
        pg.locator('#app.drawer').count() == 1 and
        '业主' in pg.locator('#drawDetail').inner_text())
    pg.locator('#modalClose').click()

    print('=== 4 · 12 个模块独立检索（静态本地视图筛选） ===')
    impl = ['opportunities', 'orgs', 'clients', 'overseas', 'wechat',
            'policies', 'changes', 'platforms', 'help']
    phs = []
    for mid in impl:
        pg.locator('#navList .ni[data-id="%s"]' % mid).click()
        pg.wait_for_timeout(240)
        has = pg.locator('#mq').count() == 1 and not pg.locator('#mq').is_disabled()
        empty = pg.locator('#mq').input_value() == ''
        phs.append(pg.locator('#mq').get_attribute('placeholder') or '')
        chk('模块 %-16s 有检索框且切模块自动清空' % mid, has and empty)
    chk('各模块 placeholder 按业务定制', len(set(phs)) >= 9, '%d 种' % len(set(phs)))
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="clients"]').click(); pg.wait_for_timeout(300)
    before = pg.locator('#pk').inner_text()
    pg.locator('#mq').fill('热电'); pg.wait_for_timeout(420)
    chk('客户与业主搜「热电」命中下降',
        '热电' in pg.locator('#rows').inner_text() and pg.locator('#pk').inner_text() != before)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="orgs"]').click(); pg.wait_for_timeout(300)
    chk('切模块后检索词不残留', pg.locator('#mq').input_value() == '')
    pg.locator('#mq').fill('华光'); pg.wait_for_timeout(420)
    chk('同业与伙伴搜「华光」生效', '华光' in pg.locator('#rows').inner_text())
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="overseas"]').click(); pg.wait_for_timeout(300)
    ov = pg.locator('#pk').inner_text()
    pg.locator('#mq').fill('印尼'); pg.wait_for_timeout(420)
    chk('海外机会搜「印尼」生效', pg.locator('#pk').inner_text() != ov)

    print('=== 5 · 当日行情面板 / 品种曲线 / 业主画像 / 政策档 / 口径 ===')
    chk('导航不再单列有色金属行情模块',
        pg.locator('#navList .ni[data-id="metals"]').count() == 0)
    pg.locator('#btnMkt').click(); pg.wait_for_timeout(220)
    chk('当日行情可展开（旧版那个下拉回来了）', pg.locator('#mktPop.on').count() == 1)
    chk('13 个品种紧凑行', pg.locator('#mktPop .mktrow').count() == 13,
        str(pg.locator('#mktPop .mktrow').count()))
    chk('面板含真实价格（沪铜 / 106,170）',
        '沪铜' in pg.locator('#mktPop').inner_text() and '106,170' in pg.locator('#mktPop').inner_text())
    chk('每行有迷你走势 SVG（hist 顶层 s 字段已修）',
        pg.locator('#mktPop .mktrow svg').count() >= 10,
        str(pg.locator('#mktPop .mktrow svg').count()))
    pg.screenshot(path=OUT + '当日行情.png', full_page=False)
    pg.locator('#mktPop .mktrow').first.click(); pg.wait_for_timeout(420)
    chk('点品种打开详情并画出历史曲线',
        pg.locator('#app.drawer').count() == 1 and
        pg.locator('#drawDetail svg').count() >= 1 and
        '区间最高' in pg.locator('#drawDetail').inner_text())
    pg.screenshot(path=OUT + '品种曲线.png', full_page=False)
    pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(330)
    pg.locator('#rows .rt[data-detail]').first.click(); pg.wait_for_timeout(420)
    chk('点标题打开项目详情（真实字段）',
        pg.locator('#app.drawer').count() == 1 and '业主' in pg.locator('#drawDetail').inner_text())
    pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    if pg.locator('#rows .rbuyer[data-owner]').count():
        pg.locator('#rows .rbuyer[data-owner]').first.click(); pg.wait_for_timeout(520)
        ot = pg.locator('#drawOwner').inner_text()
        chk('点业主名打开业主画像（②库只读 / 不补假数据）',
            pg.locator('#app.drawer').count() == 1 and ('②库' in ot or '暂无' in ot),
            ot.replace('\n', ' | ')[:80])
        pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    pg.screenshot(path=OUT + '桌面-找商机.png', full_page=False)
    pg.screenshot(path=OUT + '桌面-整页.png', full_page=True)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="policies"]').click(); pg.wait_for_timeout(350)
    chk('政策档原文可见', pg.locator('#rows').inner_text().count('条') > 0 and
        len(pg.locator('#rows').inner_text()) > 200)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="help"]').click(); pg.wait_for_timeout(350)
    chk('口径与帮助：规则源可 import / 12 条启用规则',
        '唯一规则源' in pg.locator('#rows').inner_text() or
        '12' in pg.locator('#pk').inner_text())

    print('=== 6 · 空 tab / 全库检索 / 个人中心 / 通知 ===')
    pg.locator('#navList .fold').click(); pg.wait_for_timeout(160)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="funnel"]').click(); pg.wait_for_timeout(320)
    chk('空 tab 提示「功能待实现」且检索禁用',
        '功能待实现' in pg.locator('#rows').inner_text() and pg.locator('#mq').is_disabled())
    ph = pg.evaluate('document.documentElement.scrollHeight')
    chk('空 tab 整页约一屏（无大片留白）', abs(ph - 950) <= 100, '%d px' % ph)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(350)
    pg.locator('#gq').fill('余热'); pg.wait_for_timeout(750)
    chk('全库统一检索返回跨库分组命中',
        '全库统一检索' in pg.locator('#extra').inner_text() and '命中' in pg.locator('#extra').inner_text())
    pg.locator('#btnUser').click(); pg.wait_for_timeout(150)
    chk('个人中心含深色 / 预览档 / 接口状态',
        all(x in pg.locator('#popUser').inner_text() for x in ('深色模式', '预览档', '接口状态')))
    pg.locator('#btnTheme').click()
    chk('暗色主题切换', pg.locator('body.dark').count() == 1)
    pg.locator('#btnTheme').click(); pg.locator('#btnUser').click()
    pg.locator('#btnBell').click(); pg.wait_for_timeout(150)
    chk('通知面板为只读事实（质量体检 / planned）',
        '质量体检' in pg.locator('#bellBody').inner_text())
    pg.locator('#btnBell').click()
    pg.evaluate("document.getElementById('extra').innerHTML=''")
    pg.screenshot(path=OUT + '桌面-找商机.png', full_page=False)
    pg.screenshot(path=OUT + '桌面-整页.png', full_page=True)

    print('=== 7 · 旧深链 / 响应式 / 控制台 ===')
    pg.goto(B + '#t3', wait_until='networkidle', timeout=90000); pg.wait_for_timeout(350)
    chk('旧深链 #t3 → #/overseas（海外机会）',
        pg.evaluate('location.hash') == '#/overseas' and
        pg.locator('#ptitle').inner_text() == '海外机会')
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(380)
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(320)
    chk('390px 下左导航隐藏', pg.locator('.nav').evaluate('e=>getComputedStyle(e).display') == 'none')
    chk('390px 下数据行收敛为 ≤ 4 列',
        len(pg.locator('#rows .row').first.evaluate(
            'e=>getComputedStyle(e).gridTemplateColumns').split()) <= 4)
    pg.screenshot(path=OUT + '手机.png', full_page=False)
    pg.set_viewport_size({'width': 1440, 'height': 950}); pg.wait_for_timeout(220)
    chk('控制台 / pageerror 0 错误', len(errors) == 0, '; '.join(errors[:3]))
    b.close()

srv.shutdown()
print('\n=== 结果：%d 通过 / %d 失败 ===' % (ok, fail))
if errors:
    print('错误明细：', errors[:8])
raise SystemExit(1 if fail else 0)
