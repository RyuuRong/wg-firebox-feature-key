#!/usr/bin/env python3
"""Apply a feature key to a WatchGuard Firebox V through the Web UI.

Standard-library only (Python 3.6+).

Usage:
    python apply_license.py --host 10.0.1.1 --port 8080 \
        --user admin --password <pass> --license-file feature_key.txt

Flow implemented:
    1. XML-RPC login      POST /agent/login          -> sid + csrf_token
    2. Session establish  POST /auth/login (form)    -> session cookie
    3. Page CSRF token    GET  /system/featurekey
    4. Submit key         POST /put_data/ (JSON)     -> {"status": true}
    5. Verify             GET  /system/featurekey    -> feature_list_all

Notes:
    * The Firebox allows only ONE admin session. If another session is
      active, the XML-RPC login fails with "currently logged in from ...";
      close it (or reboot the appliance) and retry.
    * The certificate is self-signed; validation is disabled.
"""

import argparse
import http.cookiejar
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client

ALARM_OBJ = {
    "__module__": "modules.scripts.vo.AlarmActionObj",
    "__class__": "AlarmActionObj",
    "name": "",
    "property": 0,
    "enable": 1,
    "severity": 7,
    "protocol": 7,
    "trap_enable": 0,
    "block_ip_enable": 0,
    "remote_enable": 0,
    "action_type": 1,
    "launch_interval": 900,
    "repeat_count": 10,
}

FEATURE_KEY_OBJ = {
    "__module__": "modules.scripts.page.system.PageSystemFeatureKeyObj",
    "__class__": "PageSystemFeatureKeyPutObj",
    "action": "update_feature_key",
    "feature_key": "",
    "new_feature_key_auto_sync": 0,
    "fk_expired_alarm_obj": ALARM_OBJ,
}


class WebUISession:
    def __init__(self, host, port, user, password):
        self.base = f"https://{host}:{port}"
        self.user = user
        self.password = password
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def _fetch(self, url, data=None, headers=None, method=None):
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            return self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            return exc

    def login(self):
        xml = xmlrpc.client.dumps(
            ({"password": self.password, "user": self.user,
              "domain": "Firebox-DB", "uitype": "2"},),
            methodname="login",
        )
        resp = self._fetch(self.base + "/agent/login",
                           data=xml.encode(), headers={"Content-Type": "text/xml"})
        body = resp.read().decode(errors="replace")
        sid = re.search(r"<name>sid</name><value>([0-9A-F]+)</value>", body)
        csrf = re.search(r"<name>csrf_token</name><value>([0-9A-F]+)</value>", body)
        if not sid or not csrf:
            print("Login failed. Server response:")
            print(body)
            sys.exit(1)
        form = urllib.parse.urlencode({
            "username": self.user,
            "password": self.password,
            "domain": "Firebox-DB",
            "sid": sid.group(1),
            "csrf_token": csrf.group(1),
            "privilege": "2",
            "from_page": "/",
        }).encode()
        resp = self._fetch(self.base + "/auth/login", data=form, method="POST")
        print(f"login: {resp.status}")

    def page_csrf(self, path="/system/featurekey"):
        resp = self._fetch(self.base + path)
        html = resp.read().decode(errors="replace")
        match = re.search(r'id="csrf_token" value="([0-9a-f]+)"', html)
        return match.group(1) if match else None, html

    def apply_feature_key(self, license_text):
        token, _ = self.page_csrf()
        if not token:
            raise RuntimeError("could not find page CSRF token")
        obj = dict(FEATURE_KEY_OBJ)
        obj["feature_key"] = license_text
        payload = json.dumps(obj).encode()
        headers = {
            "Content-Type": "application/json",
            "X-CSRFToken": token,
            "Origin": self.base,
            "Referer": self.base + "/system/featurekey",
        }
        resp = self._fetch(self.base + "/put_data/", data=payload,
                           headers=headers, method="POST")
        print(f"put_data: {resp.status} -> {resp.geturl()}")
        body = resp.read().decode(errors="replace")
        if resp.status == 200 and body.lstrip().startswith("{"):
            print(body)
        else:
            print(body[:200])
        return body

    def verify(self):
        _, html = self.page_csrf()
        match = re.search(r"var feature_list_all = (\[.*?\]);", html, re.S)
        features = json.loads(match.group(1)) if match else []
        print(f"feature_list_all entries: {len(features)}")
        for feature in features:
            print("  ", feature)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.0.1.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", required=True)
    parser.add_argument("--license-file", required=True,
                        help="path to the signed feature key file")
    args = parser.parse_args()

    license_text = open(args.license_file).read().strip()
    session = WebUISession(args.host, args.port, args.user, args.password)
    session.login()
    session.apply_feature_key(license_text)
    session.verify()
    print("Done.")


if __name__ == "__main__":
    main()