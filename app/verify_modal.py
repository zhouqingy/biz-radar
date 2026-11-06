# -*- coding: utf-8 -*-
"""2026-11-06 20:40 专项验收：右栏 → 居中弹窗（动态服务 + 静态快照两侧都跑）。

用户原话：「你能做成这种弹窗的形式吗？我不想放在右边」。
验收点：默认不占第三列 / 点条目弹出居中带遮罩的弹窗 / 三种关闭方式 /
        项目详情、业主画像、品种曲线三条链路都能进弹窗 / ②库画像有真实条目表 /
        窄屏弹窗自适应 / 数据与口径红线不变。
只读验收：不写数据、不改口径、不触发采集。
"""
import functools, http.server, socketserver, threading, sys, urllib.request
from playwright.sync_api import sync_playwright

ROOT = '/workspace'
OUT = '/workspace/2026-11-06-V4居中弹窗-'
DYNAMIC = 'http://127.0.0.1:8848/'
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
httpd = socketserver.TCPServer(('127.0.0.1', 0), h)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
STATIC = 'http://127.0.0.1:%d/v4/index.html' % httpd.server_address[1]

ok = fail = 0
fails = []


def chk(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %-50s %s' % (name, detail))
    else:
        fail += 1
        fails.append(name)
        print('  FAIL  %-50s %s' % (name, detail))


def run(pg, label, shots):
    print('\n=== %s ===' % label)
    errs = []
    pg.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
    pg.on('console', lambda m: errs.append('console: ' + m.text) if m.type == 'error' else None)
    pg.goto(pg.url, wait_until='domcontentloaded', timeout=90000)
    pg.wait_for_function("document.querySelectorAll('#rows .row').length>0", timeout=40000)
    pg.wait_for_timeout(350)

    print('--- 1 · 骨架：默认不占右边 ---')
    cols = pg.locator('.body').evaluate('e=>getComputedStyle(e).gridTemplateColumns')
    chk('%s · 主体只有两栏（左导航 + 全宽主区）' % label, len(cols.split()) == 2, cols)
    chk('%s · 弹窗默认收起，不常驻在右边' % label, not pg.locator('#modal').is_visible())
    chk('%s · 主区变宽（≥ 1100px @1440）' % label,
        pg.locator('.main').bounding_box()['width'] >= 1100,
        str(round(pg.locator('.main').bounding_box()['width'])))
    chk('%s · 弹窗容器 / 关闭按钮齐备，且无多余页签（单页）' % label,
        pg.locator('#modal').count() == 1 and pg.locator('#modalClose').count() == 1 and
        pg.locator('.modal-tabs').count() == 0 and
        pg.locator('#modal button[id^="dt"]').count() == 0)
    if shots:
        pg.screenshot(path=OUT + '整页-无弹窗.png', full_page=False)

    print('--- 2 · 点项目标题 → 居中弹窗 ---')
    pg.locator('#rows .rt[data-detail]').first.click()
    pg.wait_for_function("document.querySelector('#dDetail').innerText.indexOf('状态历史')>=0", timeout=30000)
    chk('%s · 弹窗打开（不是从边上滑出）' % label, pg.locator('#modal.on').count() == 1)
    box = pg.locator('.modal-box').bounding_box()
    chk('%s · 弹窗水平居中（中心 720 ±3 @1440）' % label,
        abs(box['x'] + box['width'] / 2 - 720) <= 3,
        'x=%s w=%s' % (round(box['x']), round(box['width'])))
    chk('%s · 弹窗有半透明遮罩' % label,
        'rgba' in pg.locator('#modal').evaluate('e=>getComputedStyle(e).backgroundColor'))
    chk('%s · 标题栏显示具体项目名 + 来源副标题' % label,
        len(pg.locator('#modalTitle').inner_text()) > 8 and
        '项目详情' in pg.locator('#modalSub').inner_text(),
        pg.locator('#modalTitle').inner_text()[:34])
    dt = pg.locator('#dDetail').inner_text()
    chk('%s · 详情仍是接口真实字段' % label,
        all(x in dt for x in ('ID', '业主', '原文', '状态历史')), dt[:70].replace('\n', ' | '))
    chk('%s · 详情有分区标题（不再是一坨）' % label,
        pg.locator('#dDetail .sec-h').count() >= 2)
    if shots:
        pg.screenshot(path=OUT + '项目详情弹窗.png', full_page=False)

    print('--- 3 · 关闭 × / Esc / 点遮罩 ---')
    pg.locator('#modalClose').click()
    chk('%s · 右上角「关闭 ×」可关' % label, not pg.locator('#modal').is_visible())
    pg.locator('#rows .rt[data-detail]').first.click()
    pg.wait_for_timeout(350)
    pg.keyboard.press('Escape')
    chk('%s · Esc 可关' % label, not pg.locator('#modal').is_visible())
    pg.locator('#btnDraw').click()
    chk('%s · 顶栏按钮打开「实时关注」弹窗' % label,
        pg.locator('#modal.on').count() == 1 and pg.locator('#modalTitle').inner_text() == '实时关注')
    chk('%s · 实时关注数据来自接口' % label,
        '读取中' not in pg.locator('#dFocus').inner_text())
    pg.locator('#modal').click(position={'x': 4, 'y': 4})
    chk('%s · 点弹窗外遮罩可关' % label, not pg.locator('#modal').is_visible())

    print('--- 4 · 业主画像（①库业主名 + ②库单位名） ---')
    if pg.locator('#rows .rbuyer[data-owner]').count():
        pg.locator('#rows .rbuyer[data-owner]').first.click()
        pg.wait_for_timeout(900)
        ot = pg.locator('#dOwner').inner_text()
        chk('%s · 点①库业主名进画像弹窗' % label,
            '业主画像' in pg.locator('#modalSub').inner_text() and
            len(pg.locator('#modalTitle').inner_text()) > 3 and
            ('②库' in ot or '暂无' in ot), ot[:70].replace('\n', ' | '))
        pg.locator('#modalClose').click()
    else:
        chk('%s · 点①库业主名进画像弹窗' % label, True, '本页无可点业主名，跳过')
    pg.locator('#navList .ni[data-id="orgs"]').click()
    pg.wait_for_function("document.querySelectorAll('#rows [data-profile]').length>0", timeout=30000)
    pg.locator('#rows [data-profile]').first.click()
    pg.wait_for_timeout(350)
    ot2 = pg.locator('#dOwner').inner_text()
    chk('%s · 点②库单位名进画像（有内容不空白）' % label,
        pg.locator('#modal.on').count() == 1 and len(ot2) > 80, str(len(ot2)))
    chk('%s · 画像分区「客户概况 / 业绩总结」' % label,
        '客户概况' in ot2 and '业绩总结' in ot2)
    chk('%s · 画像用真实条目表（不是空壳）' % label,
        pg.locator('#dOwner .ovtable tr').count() >= 2,
        '%d 行' % pg.locator('#dOwner .ovtable tr').count())
    chk('%s · 弹窗单页：仅画像面板可见、无跳页按钮' % label,
        pg.locator('#drawOwner').is_visible() and
        not pg.locator('#drawCtx').is_visible() and
        not pg.locator('#drawDetail').is_visible() and
        pg.locator('#modal [data-back]').count() == 0)
    chk('%s · 画像仍声明不反推①库' % label, '不反推①库' in ot2)
    if shots:
        pg.screenshot(path=OUT + '业主画像弹窗.png', full_page=False)
    pg.keyboard.press('Escape')

    print('--- 5 · 品种曲线 → 弹窗 ---')
    pg.locator('#btnMkt').click()
    pg.wait_for_function("document.querySelectorAll('#mktPop .mktrow').length===13", timeout=30000)
    pg.locator('#mktPop .mktrow').first.click()
    pg.wait_for_timeout(500)
    chk('%s · 点品种弹窗出历史曲线' % label,
        pg.locator('#modal.on').count() == 1 and pg.locator('#dDetail svg').count() >= 1 and
        '区间最高' in pg.locator('#dDetail').inner_text())
    if shots:
        pg.screenshot(path=OUT + '品种曲线弹窗.png', full_page=False)
    pg.keyboard.press('Escape')

    print('--- 6 · 窄屏 / 数据红线 ---')
    pg.set_viewport_size({'width': 390, 'height': 844})
    pg.wait_for_timeout(250)
    pg.locator('#btnDraw').click()
    bw = pg.locator('.modal-box').bounding_box()
    chk('%s · 390px 弹窗宽度贴合视口' % label, 340 <= bw['width'] <= 380, str(round(bw['width'])))
    if shots:
        pg.screenshot(path=OUT + '手机弹窗.png', full_page=False)
    pg.keyboard.press('Escape')
    pg.set_viewport_size({'width': 1440, 'height': 950})
    pg.wait_for_timeout(250)
    # 上一步停在 ②库，KPI 是②库口径；先切回 ①库再验数字（不是页面问题，是验收路径问题）
    pg.locator('#navList .ni[data-id="opportunities"]').click()
    pg.wait_for_function("document.querySelector('#pk').innerText.indexOf('1,119')>=0", timeout=30000)
    src = urllib.request.urlopen(pg.url.split('#')[0], timeout=20).read().decode('utf-8')
    chk('%s · 源码无判定函数 / 无写死 1119' % label,
        'judge(' not in src and 'semantic_drop(' not in src and '1119' not in src)
    chk('%s · KPI 仍来自接口（1,119）' % label, '1,119' in pg.locator('#pk').inner_text())
    chk('%s · 无 JS 报错' % label, not errs, str(errs[:2]))


with sync_playwright() as p:
    br = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    pg1 = br.new_page(viewport={'width': 1440, 'height': 950})
    pg1.goto(DYNAMIC, wait_until='domcontentloaded', timeout=90000)
    # run() 内用 pg.url 二次 goto，这里先给它一个稳定的 URL
    pg2 = br.new_page(viewport={'width': 1440, 'height': 950})
    pg2.goto(STATIC + '#/opportunities', wait_until='domcontentloaded', timeout=90000)
    run(pg1, '动态服务', True)
    run(pg2, '静态快照', False)
    br.close()

httpd.shutdown()
print('\n结果：PASS %d / FAIL %d' % (ok, fail))
if fails:
    print('失败项：')
    for f in fails:
        print('  -', f)
    sys.exit(1)
