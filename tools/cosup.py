#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CloudBase 静态托管上传器（COS 直传，用 STS 临时密钥）

为什么走 STS：子账号的永久密钥在 COS 侧表现异常（始终返回
"AccessDenied / Request has expired"，即使时间戳、StringToSign 与官方示例完全一致）。
改用 GetFederationToken 拿临时密钥后签名正常，条条 200。

用法：
    python3 cosup.py --ls [prefix]
    python3 cosup.py <本地文件> <远端key>
    python3 cosup.py --ping
"""
import sys, os, re, json, time, hmac, hashlib, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tc

BUCKET = '9932-static-getinfo-d3ghutir5752f2749-1342254874'
REGION = 'ap-shanghai'
HOST = '%s.cos.%s.myqcloud.com' % (BUCKET, REGION)
CDN = 'https://getinfo-d3ghutir5752f2749-1342254874.tcloudbaseapp.com'

_CACHE = {'cred': None, 'exp': 0}


def _sts():
    """取临时密钥，缓存 30 分钟"""
    now = time.time()
    if _CACHE['cred'] and _CACHE['exp'] > now + 120:
        return _CACHE['cred']
    pol = json.dumps({"version": "2.0",
                      "statement": [{"effect": "allow", "action": ["*"], "resource": ["*"]}]})
    r = tc.call('GetFederationToken',
                {'Name': 'bizradar-cos', 'Policy': pol, 'DurationSeconds': 1800},
                'sts', '2018-08-13', region=REGION)
    c = r.get('Response', {}).get('Credentials')
    if not c:
        raise RuntimeError('STS 失败: %s' % json.dumps(r, ensure_ascii=False)[:300])
    _CACHE['cred'] = (c['TmpSecretId'], c['TmpSecretKey'], c['Token'])
    _CACHE['exp'] = now + 1700
    return _CACHE['cred']


def _sign(verb, key, extra_headers=None):
    sid, skey, token = _sts()
    path = '/' + key.lstrip('/') if key else '/'
    ts = int(time.time())
    st = '%s;%s' % (ts, ts + 900)
    hdrs = [('host', HOST), ('x-cos-security-token', token)]
    for k, v in (extra_headers or {}).items():
        hdrs.append((k.lower(), v))
    hdrs.sort()
    hs = ('%s\n%s\n\n' % (verb.lower(), path)) + ''.join('%s=%s\n' % (k, v) for k, v in hdrs)
    sh = ';'.join(k for k, _ in hdrs)
    sts = 'sha1\n%s\n%s\n%s\n' % (st, hashlib.sha1(hs.encode()).hexdigest(), '')
    ks = hmac.new(skey.encode(), sts.encode(), hashlib.sha1).hexdigest()
    q = urllib.parse.quote
    auth = ('q-sign-algorithm=sha1&q-ak=%s&q-sign-time=%s&q-key-time=%s'
            '&q-header-list=%s&q-url-param-list=&q-signature=%s'
            % (q(sid, safe=''), q(st, safe=''), q(st, safe=''), sh, ks))
    return auth, path, token


def put(local, key, content_type='application/json', cache='no-cache'):
    data = open(local, 'rb').read() if os.path.isfile(local) else local.encode('utf-8')
    extra = {'content-type': content_type, 'cache-control': cache}
    auth, path, token = _sign('put', key, extra)
    req = urllib.request.Request('https://%s%s' % (HOST, path), data=data, method='PUT',
                                 headers={'Host': HOST, 'Authorization': auth,
                                          'Content-Type': content_type, 'Cache-Control': cache,
                                          'x-cos-security-token': token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, 'HTTP%d %dB' % (r.status, len(data))
    except urllib.error.HTTPError as e:
        b = e.read().decode('utf-8', 'ignore')
        m = re.search(r'<Code>(.*?)</Code>.*?<Message>(.*?)</Message>', b, re.S)
        return False, 'HTTP%d %s' % (e.code, m.groups() if m else b[:200])
    except Exception as e:
        return False, str(e)


def ls(prefix='', maxk=200):
    auth, path, token = _sign('get', '')
    url = 'https://%s/?prefix=%s&max-keys=%d' % (HOST, urllib.parse.quote(prefix), maxk)
    req = urllib.request.Request(url, method='GET',
                                 headers={'Host': HOST, 'Authorization': auth,
                                          'x-cos-security-token': token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return True, re.findall(r'<Key>(.*?)</Key>', body)
    except urllib.error.HTTPError as e:
        b = e.read().decode('utf-8', 'ignore')
        m = re.search(r'<Code>(.*?)</Code>.*?<Message>(.*?)</Message>', b, re.S)
        return False, 'HTTP%d %s' % (e.code, m.groups() if m else b[:200])
    except Exception as e:
        return False, str(e)


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--ls':
        ok, keys = ls(sys.argv[2] if len(sys.argv) > 2 else '')
        print('OK' if ok else 'FAIL', keys)
    elif len(sys.argv) >= 2 and sys.argv[1] == '--ping':
        key = '_conn_test_.json'
        ok, msg = put('{"t":%d}' % int(time.time()), key)
        print('PUT', ok, msg)
        if ok:
            try:
                with urllib.request.urlopen('%s/%s' % (CDN, key), timeout=20) as r:
                    print('CDN', r.status, r.read()[:120])
            except Exception as e:
                print('CDN ERR', str(e)[:150])
    elif len(sys.argv) >= 3:
        print(put(sys.argv[1], sys.argv[2]))
    else:
        print(__doc__)
