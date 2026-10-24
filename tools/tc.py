#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯云 API 极简客户端 · tc.py
============================
不依赖 SDK（沙箱装 tencentcloud-sdk-python 太重），直接用 TC3-HMAC-SHA256 签名。

签名算法（腾讯云 API 3.0）：
  1. CanonicalRequest = HTTPMethod + '\n' + CanonicalURI + '\n' + CanonicalQueryString
                       + '\n' + CanonicalHeaders + '\n' + SignedHeaders + '\n' + HashedPayload
  2. StringToSign = Algorithm + '\n' + RequestTimestamp + '\n' + CredentialScope + '\n' + Hash(CanonicalRequest)
  3. SecretSigning = HMAC('TC3' + SecretKey, Date)
     SecretDate     = HMAC(SecretSigning, Service)
     SecretService  = HMAC(SecretDate, 'tc3_request')
     Signature      = HMAC(SecretService, StringToSign)

用法：
  python3 tc.py describe          # 查云开发环境
"""
import configparser
import hashlib
import hmac
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone

CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.tcloud.ini')


def load_cred():
    cp = configparser.ConfigParser()
    cp.read(CONF)
    s = cp['default']
    return s['secret_id'].strip(), s['secret_key'].strip()


def _hmac(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def sign_request(secret_id, secret_key, service, action, payload, version='2018-06-08',
                 region='', host=None):
    host = host or '%s.tencentcloudapi.com' % service
    endpoint = 'https://' + host
    ts = int(time.time())
    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')

    ct = 'application/json; charset=utf-8'
    body = json.dumps(payload, ensure_ascii=False)
    hashed_payload = hashlib.sha256(body.encode('utf-8')).hexdigest()

    canonical_headers = 'content-type:%s\nhost:%s\n' % (ct, host)
    signed_headers = 'content-type;host'
    canonical_request = '\n'.join(['POST', '/', '', canonical_headers, signed_headers,
                                   hashed_payload])

    algorithm = 'TC3-HMAC-SHA256'
    credential_scope = '%s/%s/tc3_request' % (date, service)
    string_to_sign = '\n'.join([
        algorithm, str(ts), credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()])

    k_date = _hmac(('TC3' + secret_key).encode('utf-8'), date)
    k_service = _hmac(k_date, service)
    k_signing = _hmac(k_service, 'tc3_request')
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'),
                         hashlib.sha256).hexdigest()

    auth = '%s Credential=%s/%s, SignedHeaders=%s, Signature=%s' % (
        algorithm, secret_id, credential_scope, signed_headers, signature)

    headers = {
        'Authorization': auth,
        'Content-Type': ct,
        'Host': host,
        'X-TC-Action': action,
        'X-TC-Timestamp': str(ts),
        'X-TC-Version': version,
    }
    if region:
        headers['X-TC-Region'] = region

    req = urllib.request.Request(endpoint, data=body.encode('utf-8'),
                                 headers=headers, method='POST')
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'Response': {'Error': {'Code': 'HTTP%d' % e.code,
                                       'Message': e.read().decode('utf-8', 'ignore')}}}
    except Exception as e:
        return {'Response': {'Error': {'Code': 'NET', 'Message': str(e)}}}


def call(action, payload=None, service='tcb', version='2018-06-08', region=''):
    sid, skey = load_cred()
    return sign_request(sid, skey, service, action, payload or {}, version, region)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'describe'
    if cmd == 'describe':
        r = call('DescribeEnvs', {'EnvId': 'getinfo-d3ghutir5752f2749'})
        print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])
    elif cmd == 'envs':
        r = call('DescribeEnvs', {})
        print(json.dumps(r, ensure_ascii=False, indent=1)[:3000])
    else:
        print('unknown cmd')


# ============ COS（对象存储）最小客户端，用于静态托管桶读写 ============
def cos_put(bucket, region, key, data, content_type='application/json'):
    """上传/覆盖对象。返回 (ok, msg)"""
    import hashlib as _h1, hmac as _hmac1
    sid, skey = load_cred()
    host = '%s.cos.%s.myqcloud.com' % (bucket, region)
    path = '/' + key.lstrip('/')
    ts = int(time.time())
    st = '%s;%s' % (ts, ts + 3600)
    hs = 'put\n%s\n\nhost=%s\n' % (path, host)
    sts = 'sha1\n%s\n%s\n%s\n' % (st, _h1.sha1(hs.encode()).hexdigest(), '')
    ks = _hmac1.new(skey.encode(), sts.encode(), _h1.sha1).hexdigest()
    auth = ('q-sign-algorithm=sha1&q-ak=%s&q-sign-time=%s&q-key-time=%s'
            '&q-header-list=host&q-url-param-list=&q-signature=%s') % (sid, st, st, ks)
    req = urllib.request.Request('https://%s%s' % (host, path),
                                 data=data.encode('utf-8') if isinstance(data, str) else data,
                                 method='PUT',
                                 headers={'Host': host, 'Authorization': auth,
                                          'Content-Type': content_type})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, 'HTTP%d' % r.status
    except urllib.error.HTTPError as e:
        return False, 'HTTP%d %s' % (e.code, e.read().decode('utf-8', 'ignore')[:300])
    except Exception as e:
        return False, str(e)


def cos_get(bucket, region, key):
    sid, skey = load_cred()
    import hashlib as _h1, hmac as _hmac1
    host = '%s.cos.%s.myqcloud.com' % (bucket, region)
    path = '/' + key.lstrip('/')
    ts = int(time.time())
    st = '%s;%s' % (ts, ts + 3600)
    hs = 'get\n%s\n\nhost=%s\n' % (path, host)
    sts = 'sha1\n%s\n%s\n%s\n' % (st, _h1.sha1(hs.encode()).hexdigest(), '')
    ks = _hmac1.new(skey.encode(), sts.encode(), _h1.sha1).hexdigest()
    auth = ('q-sign-algorithm=sha1&q-ak=%s&q-sign-time=%s&q-key-time=%s'
            '&q-header-list=host&q-url-param-list=&q-signature=%s') % (sid, st, st, ks)
    req = urllib.request.Request('https://%s%s' % (host, path), method='GET',
                                 headers={'Host': host, 'Authorization': auth})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, r.read().decode('utf-8', 'ignore')
    except urllib.error.HTTPError as e:
        return False, 'HTTP%d %s' % (e.code, e.read().decode('utf-8', 'ignore')[:300])
    except Exception as e:
        return False, str(e)
