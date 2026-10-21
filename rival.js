/* 商机雷达 · 竞对画像抽屉
 * 挂进主站：在 index.html 末尾引 rival.js 即可（注释里不要写闭合的 script 标签，
 * 否则浏览器解析外部 JS 时会把它当结束标记，整个文件被截断）
 * 调用：Rival.open('中国联合工程有限公司')
 */
(function () {
  'use strict';
  var API = 'https://getinfo-d3ghutir5752f2749-1342254874.ap-shanghai.app.tcloudbase.com/api';
  var HOST = 'https://zfcg.nantong.gov.cn';
  var CACHE = {};
  var ALLUNITS = null;   // 有画像的单位清单，只拉一次

  // 顶部切换条：把有画像的对手列出来，点一下就地切换，不跳页
  function mountSwitch(active) {
    var bar = document.getElementById('rv-switch');
    if (!bar) return;
    if (!ALLUNITS) {
      bar.innerHTML = '';
      fetch(API + '?all=1&t=' + Date.now(), { mode: 'cors' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          ALLUNITS = (d.units || []).map(function (u) {
            return { name: u.name, abbr: u.abbr, n: u.n };
          });
          mountSwitch(active);
        })
        .catch(function () { });
      return;
    }
    if (!ALLUNITS.length) { bar.style.display = 'none'; return; }
    bar.style.display = 'flex';
    var h = '<span class="lb">已有画像</span>';
    ALLUNITS.forEach(function (u) {
      var on = u.name === active || u.abbr === active;
      h += '<button class="sw' + (on ? ' on' : '') + '" onclick="Rival.open(\'' +
        u.name.replace(/'/g, '') + '\')">' + esc(u.abbr) +
        '<sm>' + u.n + '</sm></button>';
    });
    bar.innerHTML = h;
  }


  var CSS = `
#rv-mask{position:fixed;inset:0;background:rgba(15,23,42,.42);opacity:0;pointer-events:none;transition:.28s;z-index:9000;backdrop-filter:blur(2px)}
#rv-mask.on{opacity:1;pointer-events:auto}
#rv-panel{position:fixed;top:0;right:0;height:100%;width:min(880px,94vw);background:#f5f6f8;
  box-shadow:-6px 0 32px rgba(0,0,0,.16);transform:translateX(102%);transition:transform .32s cubic-bezier(.32,.72,0,1);
  z-index:9001;display:flex;flex-direction:column}
#rv-panel.on{transform:translateX(0)}
#rv-head{flex:none;padding:15px 20px;background:#fff;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;gap:12px}
#rv-head .t{font-size:16px;font-weight:700;letter-spacing:-.3px;flex:1;min-width:0}
#rv-head .t small{display:block;font-size:11.5px;color:#6b7280;font-weight:400;margin-top:1px;letter-spacing:0}
#rv-close{flex:none;width:30px;height:30px;border:none;background:#f3f4f6;border-radius:7px;cursor:pointer;
  font-size:17px;color:#6b7280;line-height:1;display:flex;align-items:center;justify-content:center}
#rv-close:hover{background:#e5e7eb;color:#111827}
#rv-body{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:16px 18px 60px}
#rv-body::-webkit-scrollbar{width:8px}
#rv-body::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:4px}
.rv-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:9px;margin-bottom:14px}
.rv-kpi{background:#fff;border:1px solid #e5e7eb;border-radius:9px;padding:11px 12px}
.rv-kpi .n{font-size:21px;font-weight:700;letter-spacing:-.8px;line-height:1.15}
.rv-kpi .n sm{font-size:12px;font-weight:600;color:#6b7280;margin-left:2px}
.rv-kpi .l{font-size:11px;color:#6b7280;margin-top:2px}
.rv-kpi.a .n{color:#0f766e}.rv-kpi.b .n{color:#b45309}
.rv-sec{background:#fff;border:1px solid #e5e7eb;border-radius:9px;padding:13px 14px;margin-bottom:13px}
.rv-sec h4{font-size:13px;margin:0 0 10px;font-weight:600;display:flex;align-items:center;gap:7px}
.rv-sec h4 i{width:3px;height:13px;background:#0f766e;border-radius:2px}
.rv-q{display:flex;gap:11px;align-items:flex-start;padding:9px 0;border-bottom:1px solid #f3f4f6}
.rv-q:last-child{border-bottom:none;padding-bottom:0}
.rv-q .ic{width:32px;height:32px;flex:none;border-radius:8px;background:linear-gradient(135deg,#0f766e,#14b8a6);
  display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;font-weight:700}
.rv-q .nm{font-size:13px;font-weight:600;margin-bottom:1px}
.rv-q .cd{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#0f766e;background:#f0fdfa;
  display:inline-block;padding:0 6px;border-radius:3px}
.rv-q .nt{font-size:11.5px;color:#4b5563;line-height:1.5;margin-top:2px}
.rv-q .sr{font-size:11px;color:#9ca3af;margin-top:2px}
.rv-tb{width:100%;border-collapse:collapse;font-size:12.5px}
.rv-tb th{text-align:left;padding:7px 6px;border-bottom:1.5px solid #e5e7eb;font-size:11.5px;color:#6b7280;font-weight:600;white-space:nowrap}
.rv-tb td{padding:8px 6px;border-bottom:1px solid #f3f4f6;vertical-align:top}
.rv-tb tr:hover td{background:#f9fafb}
.rv-tb td.d{color:#6b7280;white-space:nowrap;font-size:11.5px;font-variant-numeric:tabular-nums}
.rv-tb td.p{line-height:1.45}
.rv-tb td.p b{font-weight:600;color:#111827}
.rv-tb td.p .sc{display:block;margin-top:3px;font-size:11px;color:#0f766e;background:#ecfdf5;
  border-left:2px solid #14b8a6;padding:1px 5px;border-radius:0 3px 3px 0}
.rv-tb td.p .sc.none{color:#9ca3af;background:#f9fafb;border-left-color:#e5e7eb;font-style:italic}
.rv-tb td.o{color:#4b5563;font-size:11.5px;max-width:130px}
.rv-tb td.m{text-align:right;font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}
.rv-tb td.m big{font-size:13px;color:#b45309}
.rv-tag{display:inline-block;font-size:10.5px;padding:0 5px;border-radius:3px;background:#f1f5f9;color:#475569;white-space:nowrap}
.rv-tag.t1{background:#ecfdf5;color:#0f766e}.rv-tag.t2{background:#fef3c7;color:#92400e}.rv-tag.t3{background:#eef2ff;color:#3730a3}
.rv-btn{display:inline-block;font-size:11px;padding:2px 7px;border-radius:4px;border:1px solid #d1d5db;
  background:#fff;color:#374151;cursor:pointer;text-decoration:none;white-space:nowrap;line-height:1.5;margin:1px 0}
.rv-btn:hover{background:#f3f4f6}
.rv-btn.pri{background:#0f766e;border-color:#0f766e;color:#fff}
.rv-btn.pri:hover{background:#115e59}
.rv-bar{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px}
.rv-bar .bl{width:100px;flex:none;color:#4b5563;text-align:right;font-size:11.5px;line-height:1.3}
.rv-bar i{height:15px;background:linear-gradient(90deg,#0f766e,#14b8a6);border-radius:3px;min-width:2px;flex:0 1 auto;max-width:calc(100% - 160px)}
.rv-bar i.g{background:#94a3b8}
.rv-bar em{font-style:normal;color:#6b7280;font-size:11px;flex:none;white-space:nowrap}
.rv-note{font-size:11.5px;color:#6b7280;line-height:1.6;background:#fafafa;border-radius:6px;padding:9px 11px}
.rv-note b{color:#374151}
dl.co{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:7px 24px;margin:0;font-size:12.5px}
dl.co dt{color:#9ca3af;font-size:11.5px;line-height:1.7}
dl.co dd{margin:0;color:#374151;line-height:1.6;word-break:break-all}
dl.co dd.mono{font-family:ui-monospace,Consolas,monospace;letter-spacing:.2px}
#rv-switch{flex:none;display:flex;align-items:center;gap:6px;padding:7px 20px;background:#fff;
  border-bottom:1px solid #eef0f2;overflow-x:auto;white-space:nowrap}
#rv-switch .lb{font-size:11px;color:#9ca3af;margin-right:2px;flex:none}
#rv-switch .sw{flex:none;font-size:12px;padding:3px 9px;border-radius:14px;border:1px solid #e5e7eb;
  background:#fafafa;color:#4b5563;cursor:pointer;line-height:1.55}
#rv-switch .sw:hover{background:#f3f4f6;border-color:#d1d5db}
#rv-switch .sw.on{background:#0f766e;border-color:#0f766e;color:#fff;font-weight:600}
#rv-switch .sw sm{font-size:10px;opacity:.65;margin-left:3px}
.rv-tb tr.off td{opacity:.62}
.rv-tb tr.off td.p b{font-weight:500}
i.est{font-style:normal;color:#d97706;margin-left:2px;cursor:help;font-weight:700}
.rv-load{text-align:center;padding:60px 20px;color:#9ca3af;font-size:13px}
.rv-err{text-align:center;padding:50px 20px;color:#b91c1c;font-size:13px}
`;

  function injectCSS() {
    if (document.getElementById('rv-style')) return;
    var s = document.createElement('style');
    s.id = 'rv-style';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function esc(x) {
    return String(x == null ? '' : x)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function money(a) {
    return a >= 1 ? (Math.round(a * 100) / 100).toFixed(2) + '亿'
                  : Math.round(a * 10000) + '万';
  }

  function toast(msg) {
    var t = document.getElementById('rv-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'rv-toast';
      t.style.cssText = 'position:fixed;left:50%;bottom:40px;transform:translateX(-50%) translateY(20px);' +
        'background:#111827;color:#fff;padding:10px 20px;border-radius:8px;font-size:13px;' +
        'opacity:0;transition:.25s;pointer-events:none;z-index:99999';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = '1';
    t.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(t._h);
    t._h = setTimeout(function () {
      t.style.opacity = '0';
      t.style.transform = 'translateX(-50%) translateY(20px)';
    }, 2200);
  }

  window.rvCopy = function (txt, btn) {
    function done() {
      toast('链接已复制，粘贴到浏览器即可打开');
      if (btn) {
        var o = btn.textContent;
        btn.textContent = '已复制';
        setTimeout(function () { btn.textContent = o; }, 1500);
      }
    }
    function fb() {
      var ta = document.createElement('textarea');
      ta.value = txt;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { prompt('手动复制：', txt); }
      document.body.removeChild(ta);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(txt).then(done).catch(fb);
    } else { fb(); }
  };

  function build(d) {
    var Q = d.q, items = d.items || [];
    var total = 0, nbig = 0, bigamt = 0, coreTotal = 0, ncore = 0;
    var tk = {}, pv = {}, own = {};
    items.forEach(function (x) {
      var a = x.a || 0;
      total += a;
      if (a >= 1) { nbig++; bigamt += a; }
      if (x.core) { ncore++; coreTotal += a; }
      var t = x.tk || '其他', p = x.pv || '其他';
      tk[t] = (tk[t] || 0) + a;
      if (p !== '其他/海外') pv[p] = (pv[p] || 0) + a; else pv['其他'] = (pv['其他'] || 0) + a;
      if (x.o) own[x.o] = 1;
      if (!x.url) x.url = HOST + (x.s || '');
    });
    var tkArr = Object.keys(tk).map(function (k) { return [k, tk[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    var pvArr = Object.keys(pv).map(function (k) { return [k, pv[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
    var mxTk = tkArr.length ? tkArr[0][1] : 1;
    var mxPv = pvArr.length ? pvArr[0][1] : 1;

    var h = '';
    h += '<div class="rv-kpis">';
    h += '<div class="rv-kpi a"><div class="n">' + items.length + '<sm>条</sm></div><div class="l">可查业绩</div></div>';
    h += '<div class="rv-kpi b"><div class="n">' + (Math.round(total * 100) / 100).toFixed(2) + '<sm>亿</sm></div><div class="l">合同额合计</div></div>';
    h += '<div class="rv-kpi"><div class="n">' + ncore + '<sm>条</sm></div><div class="l">热电主赛道</div></div>';
    h += '<div class="rv-kpi"><div class="n">' + nbig + '<sm>条</sm></div><div class="l">亿元级大单</div></div>';
    h += '<div class="rv-kpi"><div class="n">' + pvArr.length + '<sm>省</sm></div><div class="l">业务覆盖</div></div>';
    h += '<div class="rv-kpi"><div class="n">' + Object.keys(own).length + '<sm>家</sm></div><div class="l">服务业主</div></div>';
    h += '</div>';

    if (Q && (Q.parent || Q.credit || Q.base)) {
      h += '<div class="rv-sec"><h4><i></i>企业档案</h4><dl class="co">';
      if (Q.parent) h += '<dt>母公司</dt><dd>' + esc(Q.parent) + '</dd>';
      if (Q.credit) h += '<dt>统一信用代码</dt><dd class="mono">' + esc(Q.credit) + '</dd>';
      if (Q.founded) h += '<dt>成立/沿革</dt><dd>' + esc(Q.founded) + '</dd>';
      if (Q.base) h += '<dt>注册地</dt><dd>' + esc(Q.base) + '</dd>';
      if (Q.tag) h += '<dt>一句话</dt><dd>' + esc(Q.tag) + '</dd>';
      h += '</dl></div>';
    }

    if (Q && Q.qual && Q.qual.length) {
      h += '<div class="rv-sec"><h4><i></i>企业资质</h4>';
      Q.qual.forEach(function (q) {
        h += '<div class="rv-q"><div class="ic">资</div><div style="flex:1;min-width:0">' +
          '<div class="nm">' + esc(q.n) + '</div>' +
          '<div class="cd">' + esc(q.code) + '</div>' +
          '<div class="nt">' + esc(q.note) + '</div>' +
          '<div class="sr">来源：' + esc(q.src) + '</div></div></div>';
      });
      h += '</div>';
    }

    h += '<div class="rv-sec"><h4><i></i>业绩明细 <span style="font-weight:400;color:#9ca3af;font-size:11px">按合同额降序 · 灰字为热电主赛道之外</span></h4>';
    h += '<table class="rv-tb"><thead><tr><th>日期</th><th>项目 / 规模</th><th>建设单位</th><th style="text-align:right">合同额</th><th>原文</th></tr></thead><tbody>';
    items.forEach(function (x) {
      var sc = x.sc
        ? '<span class="sc">' + esc(x.sc) + (x.iv ? ' · 总投资 ' + esc(x.iv) : '') + '</span>'
        : '<span class="sc none">原表未列规模</span>';
      var cls = x.a >= 5 ? 't1' : (x.a >= 1 ? 't2' : 't3');
      h += '<tr class="' + (x.core ? '' : 'off') + '">' +
        '<td class="d">' + esc(x.d || '—') + (x.est ? '<i class="est" title="原表未列中标时间，取公示发布日期">*</i>' : '') + '</td>' +
        '<td class="p"><b>' + esc(x.p) + '</b>' + sc +
          '<div style="margin-top:3px"><span class="rv-tag ' + cls + '">' + esc(x.tk || '其他') + '</span> ' +
          '<span class="rv-tag">' + esc(x.pv || '其他') + '</span></div></td>' +
        '<td class="o">' + (x.o ? esc(x.o) : '<span style="color:#c7cbd1">原表未列</span>') + '</td>' +
        '<td class="m"><big>' + money(x.a) + '</big></td>' +
        '<td><a class="rv-btn pri" href="' + esc(x.url || '') + '" target="_blank" rel="noopener">原文</a>' +
          '<button class="rv-btn" onclick="rvCopy(\'' + esc(x.url || '') + '\',this)">复制</button></td>' +
        '</tr>';
    });
    h += '</tbody></table></div>';

    h += '<div class="rv-sec"><h4><i></i>赛道分布</h4>';
    tkArr.forEach(function (r) {
      h += '<div class="rv-bar"><span class="bl">' + esc(r[0]) + '</span>' +
        '<i style="width:' + (r[1] / mxTk * 90).toFixed(1) + '%"></i><em>' + money(r[1]) + '</em></div>';
    });
    h += '</div>';

    h += '<div class="rv-sec"><h4><i></i>地域分布</h4>';
    pvArr.forEach(function (r) {
      h += '<div class="rv-bar"><span class="bl">' + esc(r[0]) + '</span>' +
        '<i class="' + (r[0] === '浙江' ? '' : 'g') + '" style="width:' + (r[1] / mxPv * 90).toFixed(1) +
        '%"></i><em>' + money(r[1]) + '</em></div>';
    });
    h += '</div>';

    // 打法提示：由数据驱动，不再写死某一家
    var topTk = tkArr.length ? tkArr[0][0] : '—';
    var corePct = total > 0 ? (coreTotal / total * 100).toFixed(0) : 0;
    var bigPct = total > 0 ? (bigamt / total * 100).toFixed(0) : 0;
    var note = '<b>主赛道：</b>热电相关 ' + ncore + ' 条 / ' + (Math.round(coreTotal * 100) / 100).toFixed(2) +
      ' 亿，占合同额 ' + corePct + '%。<br>' +
      '<b>赛道结构：</b>' + (corePct >= 95
        ? '几乎全部落在热电主赛道，是纯粹的热电玩家。'
        : '除热电外还有 ' + (100 - corePct) + '% 在特高压、燃煤大机组等非热电领域，热电只是其中一块。') +
      '<br><b>集中度：</b>';
    if (nbig === 0) {
      note += '无亿元级大单，最大单笔 ' + (items.length ? money(items[0].a) : '—') +
        '，走的是中小项目多点开花路线，单笔不大但家数多。';
    } else {
      note += nbig + ' 条亿元级合计 ' + (Math.round(bigamt * 100) / 100).toFixed(2) + ' 亿，占 ' + bigPct + '%。' +
        (bigPct >= 70 ? '收入高度依赖少数大单，丢一个大项目业绩就断档。' : '项目个数与金额较均衡。');
    }
    if (Q && Q.risk) note += '<br><b>要注意：</b>' + esc(Q.risk);
    if (Q && Q.role) note += '<br><b>同场表现：</b>' + esc(Q.role) + (Q.quote ? '（报价 ' + esc(Q.quote) + '）' : '');
    h += '<div class="rv-sec"><h4><i></i>打法提示</h4><div class="rv-note">' + note + '</div></div>';

    return h;
  }

  function open(unit) {
    injectCSS();
    unit = unit || '中国联合工程有限公司';

    var mask = document.getElementById('rv-mask');
    var panel = document.getElementById('rv-panel');
    if (!panel) {
      mask = document.createElement('div');
      mask.id = 'rv-mask';
      mask.onclick = close;
      document.body.appendChild(mask);

      panel = document.createElement('div');
      panel.id = 'rv-panel';
      panel.innerHTML =
        '<div id="rv-head">' +
        '<div class="t" id="rv-title">竞对画像<small>加载中…</small></div>' +
        '<button id="rv-close" onclick="Rival.close()">✕</button></div>' +
        '<div id="rv-switch"></div>' +
        '<div id="rv-body"><div class="rv-load">正在拉取业绩数据…</div></div>';
      document.body.appendChild(panel);
    }

    mountSwitch(unit);

    document.getElementById('rv-body').innerHTML = '<div class="rv-load">正在拉取业绩数据…</div>';
    // 标题显示单位全称：从已知清单里反查，避免切到简称时标题变成「江苏院」
    var showName = unit;
    if (ALLUNITS) {
      var hit = null;
      for (var i = 0; i < ALLUNITS.length; i++) {
        if (ALLUNITS[i].name === unit || ALLUNITS[i].abbr === unit) { hit = ALLUNITS[i]; break; }
      }
      if (hit) showName = hit.name;
    }
    document.getElementById('rv-title').innerHTML = esc(showName) + '<small>加载中…</small>';

    requestAnimationFrame(function () {
      mask.classList.add('on');
      panel.classList.add('on');
    });
    document.body.style.overflow = 'hidden';

    function render(d) {
      document.getElementById('rv-title').innerHTML =
        esc((d.q && d.q.name) || unit) +
        '<small>数据源：南通公共资源交易平台 · 更新 ' + esc(d.updated || '') + '</small>';
      document.getElementById('rv-body').innerHTML = build(d);
      document.getElementById('rv-body').scrollTop = 0;
    }

    if (CACHE[unit]) { render(CACHE[unit]); return; }

    var url = API + '?unit=' + encodeURIComponent(unit) + '&t=' + Date.now();
    fetch(url, { mode: 'cors' })
      .then(function (r) {
        // 404 = 这家没有画像数据（不是故障），照常读 body 交给下面处理
        if (r.status === 404) return r.json();
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        if (d && d.ok === false) {
          CACHE[unit] = d;
          var avail = (d.available || []).map(function (a) {
            return '<button class="rv-btn" style="margin:2px 4px 2px 0" onclick="Rival.open(\'' +
              a.name + '\')">' + a.abbr + '（' + a.n + '条）</button>';
          }).join('');
          document.getElementById('rv-title').innerHTML = esc(unit) + '<small>暂无画像</small>';
          document.getElementById('rv-body').innerHTML =
            '<div class="rv-err" style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin:16px;color:#4b5563;line-height:1.8">' +
            '<b style="color:#111827">这家还没有画像数据</b><br>' +
            '业绩画像目前覆盖以下单位，点击直接查看：<div style="margin-top:10px">' + avail + '</div>' +
            '<div style="margin-top:14px;font-size:11.5px;color:#9ca3af">' +
            '画像来自公开中标候选人公示中的企业业绩表。要新增公司，把它的中标公示链接给我即可。</div></div>';
          return;
        }
        CACHE[unit] = d;
        render(d);
      })
      .catch(function (e) {
        document.getElementById('rv-body').innerHTML =
          '<div class="rv-err">数据加载失败：' + esc(e.message) +
          '<br><br>可能是网络问题，或云函数未响应。<br>稍后重试，或直接访问：<br>' +
          '<a href="' + API + '" target="_blank" style="color:#0f766e">' + API + '</a></div>';
      });
  }

  function close() {
    var mask = document.getElementById('rv-mask');
    var panel = document.getElementById('rv-panel');
    if (panel) panel.classList.remove('on');
    if (mask) mask.classList.remove('on');
    document.body.style.overflow = '';
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
  });

  window.Rival = { open: open, close: close, API: API };
})();
