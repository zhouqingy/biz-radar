#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 合成数据回归：不联网、不读取或改写真实业务库。"""
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
PY = sys.executable
TODAY = '2026-11-26'


def dump_js(path, var, obj):
    path.write_text('window.%s=%s;\n' % (var, json.dumps(obj, ensure_ascii=False)), encoding='utf-8')


def run_script(script, root, scope, extra=(), env=None):
    e = dict(os.environ)
    e['GITHUB_RUN_ID'] = 'test-run'
    if env:
        e.update(env)
    return subprocess.run([PY, str(HERE / 'release_manifest.py'), 'build', '--root', str(root),
                           '--scope', scope, *extra], text=True, capture_output=True, env=e)


class P0Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='biz-p0-test-')
        self.root = Path(self.tmp.name)
        (self.root / 'tools' / 'raw').mkdir(parents=True)
        self.make_site()

    def tearDown(self):
        self.tmp.cleanup()

    def make_site(self):
        rows = [
            {'id': 'a', 't': '项目A', 'd': '2026-11-25', 'g': 'A', 'w': 1, 'amt': 1.2,
             'st': '招标公告', 'url': 'https://example.com/a'},
            {'id': 'b', 't': '项目B', 'd': TODAY, 'g': 'B', 'w': 0, 'amt': 0.2,
             'st': '招标公告', 'url': 'https://example.com/b'},
        ]
        core = {'meta': {'total': 2, 'dataAsOf': TODAY},
                'metals': {'updated': TODAY, 'items': [{'code': str(i), 'date': TODAY} for i in range(20)]}}
        dump_js(self.root / 'data.core.js', 'DATA_CORE', core)
        for name, part in [('data.items.js', rows[:1]), ('data.chunk-lead.js', rows[1:]),
                           ('data.chunk-rest.js', [])]:
            keys = sorted({k for r in rows for k in r})
            dump_js(self.root / name, 'DATA_ITEMS', {
                'n': len(part), 'cols': {k: [r.get(k) for r in part] for k in keys},
                'order': list(range(len(part))), 'ext': {}})
        digest = {'updated': TODAY + ' 08:00', 'items': [{'t': '精选%d' % i} for i in range(85)]}
        news = {'digest': digest, 'overseaFlash': [{'t': '出海', 'd': TODAY}], 'trends': []}
        dump_js(self.root / 'data.news.js', 'DATA_NEWS', news)
        dump_js(self.root / 'data.js', 'DATA', {'meta': core['meta'], 'digest': digest,
                                               'news': ['其他字段保持']})
        dump_js(self.root / 'data.changes.js', 'DATA_CHANGES', {
            'asOf': TODAY, 'kpi': {'libTotal': 2}, 'groups': {}})
        dump_js(self.root / 'data.plan.js', 'DATA_PLAN', {'n': 153, 'gen': TODAY + ' 08:00'})
        dump_js(self.root / 'data.metalhist.js', 'DATA_METALHIST', {
            'updated': TODAY, 's': {str(i): {'end': TODAY, 'd': ['1126'], 'p': [1]}
                                      for i in range(20)}})
        (self.root / 'index.html').write_text('<html>业务信号</html>', encoding='utf-8')
        (self.root / '数据质量体检.json').write_text(json.dumps({
            'gen': TODAY + ' 08:01', 'summary': {'errors': 0, 'warns': 0}}), encoding='utf-8')
        (self.root / 'tools' / 'raw' / 'digest.json').write_text(
            json.dumps(digest, ensure_ascii=False), encoding='utf-8')

    def manifest(self):
        return json.loads((self.root / 'release-manifest.json').read_text())

    def test_01_daily_bootstrap_and_same_snapshot(self):
        r = run_script('release_manifest.py', self.root, 'daily', env={'BIZ_EXPECT_DATE': TODAY})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        m = self.manifest()
        self.assertEqual(m['modules']['items']['total'], 2)
        self.assertEqual(m['modules']['digest']['count'], 85)
        self.assertEqual(m['modules']['changes']['libTotal'], 2)
        self.assertEqual(m['modules']['metals']['historyEnds'], [TODAY])
        self.assertIn('data.news.js', m['files'])

    def test_02_digest_85_to_53_is_rejected_without_overwrite(self):
        self.assertEqual(run_script('release_manifest.py', self.root, 'daily').returncode, 0)
        before = (self.root / 'release-manifest.json').read_bytes()
        bad = {'updated': '2026-11-09 08:00', 'items': [{'t': str(i)} for i in range(53)]}
        for name, var in [('data.news.js', 'DATA_NEWS'), ('data.js', 'DATA')]:
            p = self.root / name
            s = p.read_text()
            d = json.loads(s[s.index('{'):s.rindex('}') + 1])
            d['digest'] = bad
            dump_js(p, var, d)
        (self.root / 'tools' / 'raw' / 'digest.json').write_text(json.dumps(bad), encoding='utf-8')
        r = run_script('release_manifest.py', self.root, 'digest')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('日期回退', r.stderr)
        self.assertEqual((self.root / 'release-manifest.json').read_bytes(), before)

    def test_03_changes_and_core_mismatch_is_rejected(self):
        p = self.root / 'data.changes.js'
        s = p.read_text(); d = json.loads(s[s.index('{'):s.rindex('}') + 1])
        d['kpi']['libTotal'] = 791
        dump_js(p, 'DATA_CHANGES', d)
        r = run_script('release_manifest.py', self.root, 'daily')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('不是同一快照', r.stderr)

    def test_04_stale_metal_cache_and_mixed_history_are_rejected(self):
        p = self.root / 'data.core.js'
        s = p.read_text(); d = json.loads(s[s.index('{'):s.rindex('}') + 1])
        d['metals']['updated'] = '2026-11-25'
        dump_js(p, 'DATA_CORE', d)
        r = run_script('release_manifest.py', self.root, 'metals', env={'BIZ_EXPECT_DATE': TODAY})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('可能回退了缓存', r.stderr)

    def test_05_module_update_preserves_other_manifest_modules(self):
        self.assertEqual(run_script('release_manifest.py', self.root, 'daily').returncode, 0)
        p = self.root / 'data.news.js'
        s = p.read_text(); d = json.loads(s[s.index('{'):s.rindex('}') + 1])
        d['digest'] = {'updated': '2026-11-27 08:00', 'items': [{'t': str(i)} for i in range(86)]}
        dump_js(p, 'DATA_NEWS', d)
        for name, var in [('data.js', 'DATA')]:
            p = self.root / name; s = p.read_text(); x = json.loads(s[s.index('{'):s.rindex('}') + 1])
            x['digest'] = d['digest']; dump_js(p, var, x)
        (self.root / 'tools' / 'raw' / 'digest.json').write_text(json.dumps(d['digest']), encoding='utf-8')
        r = run_script('release_manifest.py', self.root, 'digest')
        self.assertEqual(r.returncode, 0, r.stderr)
        m = self.manifest()
        self.assertEqual(m['modules']['items']['total'], 2)
        self.assertEqual(m['modules']['digest']['count'], 86)

    def test_06_merge_digest_touches_only_digest_in_both_files(self):
        shutil.copy2(HERE / 'merge_digest.py', self.root / 'tools' / 'merge_digest.py')
        rv = {'n_src': 1, 'items': [{'t': '新项目签约', 'd': TODAY, 'level': 'A',
                                    'tag': '海外', 'srcKind': '官网'}]}
        (self.root / 'tools' / 'raw' / 'rival_news.json').write_text(json.dumps(rv), encoding='utf-8')
        (self.root / 'tools' / 'raw' / 'wechat_digest.json').write_text('{"items":[]}', encoding='utf-8')
        before_news = self.read_var(self.root / 'data.news.js')
        before_full = self.read_var(self.root / 'data.js')
        r = subprocess.run([PY, str(self.root / 'tools' / 'merge_digest.py')],
                           text=True, capture_output=True, env=dict(os.environ, BIZ_OUT=str(self.root)))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        after_news = self.read_var(self.root / 'data.news.js')
        after_full = self.read_var(self.root / 'data.js')
        self.assertEqual({k: v for k, v in before_news.items() if k != 'digest'},
                         {k: v for k, v in after_news.items() if k != 'digest'})
        self.assertEqual({k: v for k, v in before_full.items() if k != 'digest'},
                         {k: v for k, v in after_full.items() if k != 'digest'})
        self.assertEqual(after_news['digest'], after_full['digest'])
        self.assertEqual(after_news['digest']['items'][0]['t'], '新项目签约')

    @staticmethod
    def read_var(path):
        s = path.read_text(); return json.loads(s[s.index('{'):s.rindex('}') + 1])

    def test_07_daily_digest_ci_layout_and_missing_mail_config(self):
        tools = self.root / 'tools'
        shutil.copy2(HERE / 'daily_digest.py', tools / 'daily_digest.py')
        (tools / 'preflight.py').write_text('def require_briefing(x):\n    return None\n', encoding='utf-8')
        (tools / 'biz_rules.py').write_text(
            'def judge(t,s):\n    return {"investable":True}\n', encoding='utf-8')
        (tools / 'raw' / 'oversea_flash.json').write_text(json.dumps({
            'updated': TODAY, 'items': [{'tier': 'S', 'title': '中资项目', 'd': TODAY}]}), encoding='utf-8')
        env = dict(os.environ, BIZ_OUT=str(self.root), BIZ_SITE=str(self.root), HOME=str(self.root))
        r = subprocess.run([PY, str(tools / 'daily_digest.py')], text=True, capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn('①库当前 2 条', r.stdout)
        self.assertTrue((tools / 'raw' / 'digest_daily.json').is_file())
        r = subprocess.run([PY, str(tools / 'daily_digest.py'), '--mail'],
                           text=True, capture_output=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('未发送', r.stderr + r.stdout)

    def test_08_real_http_readback_and_mismatch(self):
        self.assertEqual(run_script('release_manifest.py', self.root, 'daily').returncode, 0)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(self.root))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = 'http://127.0.0.1:%d' % server.server_port
            base = [PY, str(HERE / 'release_manifest.py'), 'verify-online', '--root', str(self.root),
                    '--scope', 'daily', '--base-url', url, '--attempts', '1']
            r = subprocess.run(base, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            (self.root / 'data.news.js').write_text('window.DATA_NEWS={};', encoding='utf-8')
            r = subprocess.run(base, text=True, capture_output=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('未通过线上回读', r.stderr)
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_09_mixed_metal_history_is_rejected(self):
        p = self.root / 'data.metalhist.js'
        s = p.read_text(); d = json.loads(s[s.index('{'):s.rindex('}') + 1])
        d['s']['0']['end'] = '2026-11-25'
        dump_js(p, 'DATA_METALHIST', d)
        r = run_script('release_manifest.py', self.root, 'metals')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('历史端点不一致', r.stderr)

    def test_10_workflow_contract(self):
        import yaml
        wf = HERE.parent / '.github' / 'workflows'
        if not wf.is_dir():
            wf = HERE
        groups = []
        for name in ('daily.yml', 'digest.yml', 'metals.yml', 'guard-index.yml'):
            text = (wf / name).read_text()
            d = yaml.safe_load(text)
            groups.append(d['concurrency']['group'])
            self.assertNotIn('strategy-option=ours', text)
        self.assertEqual(groups, ['biz-radar-release'] * 4)
        self.assertNotIn('python build_web.py', (wf / 'digest.yml').read_text())
        self.assertNotIn('python build_web.py', (wf / 'metals.yml').read_text())
        self.assertIn('refresh_metals_core.py', (wf / 'metals.yml').read_text())
        daily = (wf / 'daily.yml').read_text()
        self.assertIn('python daily_digest.py --mail\n', daily)
        self.assertNotIn('每日摘要发送失败（不影响已推数据）', daily)
        self.assertIn('release_manifest.py verify-online', daily)


if __name__ == '__main__':
    unittest.main(verbosity=2)
