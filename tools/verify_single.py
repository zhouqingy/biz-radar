import time
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={'width':1600,'height':1100}); pg=ctx.new_page()
    errs=[]; pg.on('pageerror',lambda e:errs.append(str(e)))
    pg.goto('file:///workspace/商机雷达-本地预览.html',wait_until='load',timeout=60000)
    time.sleep(2.5)
    for i,name in [(2,'同业与伙伴'),(4,'客户与业主'),(5,'行业动态'),(7,'招标平台'),(1,'中标情报'),(0,'商机库')]:
        pg.click(".tab[data-t='%d']"%i); time.sleep(2.2)
        txt=pg.evaluate("(document.getElementById('p-%s')||{}).innerText||''"%{2:'rival',4:'client',5:'trend',7:'plat',1:'win',0:'items'}[i])
        print('==',name,'len',len(txt),'|',txt.replace('\n',' / ')[:110])
    # 四档
    pg.click(".tab[data-t='0']"); time.sleep(1.0)
    for k in ('tender','win','lead','all'):
        pg.click("[data-bk='%s']"%k); time.sleep(2.0)
        print('档',k, pg.evaluate("document.querySelectorAll('#grid .pj').length"),
              '|', pg.evaluate("(document.querySelector('.wsum, .sumline, .rsum')||{}).textContent||''"))
    print('chunks left', pg.evaluate("window.__CHUNKS__.length"), 'items', pg.evaluate("items.length"))
    pg.click(".tab[data-t='4']"); time.sleep(1.5)
    pg.click("#cTop span[data-k='graph']"); time.sleep(1.8)
    print('客户页计数', pg.evaluate("[].map.call(document.querySelectorAll('[id=cDomN],[id=cAbN],[id=cGrN]'),x=>x.id+'='+x.textContent).join(' ')"))
    pg.click(".tab[data-t='0']"); time.sleep(1.0)
    # 抽屉
    pg.click("[data-bk='tender']"); time.sleep(1.2)
    n0=len(ctx.pages)
    pg.query_selector('#grid .pj .pj-t').click(); time.sleep(1.5)
    print('抽屉', pg.evaluate("document.getElementById('drawer').className"),
          '|', pg.evaluate("(document.querySelector('#drawer .rd-head b')||{}).textContent"))
    pg.evaluate("closeReader()"); time.sleep(0.5)
    print('新标签数', len(ctx.pages)-n0)
    print('errs',errs[:6])
    b.close()
