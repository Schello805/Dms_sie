"""CI-only login check against local nginx with an external HTTPS Origin."""
import http.cookiejar
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1'
HOST = 'dms.proxy.test'
ORIGIN = 'https://' + HOST


def request(opener, data=None, origin=ORIGIN):
    headers = {'Host':HOST, 'Origin':origin, 'Referer':origin+'/login/'}
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    return opener.open(urllib.request.Request(BASE+'/login/', data=body, headers=headers), timeout=30)


if __name__ == '__main__':
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with request(opener) as response:
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.read().decode())[1]
    data = {'username':'admin', 'password':Path('/etc/ims-dms/initial-admin-password').read_text().strip()}
    for origin, payload in [(ORIGIN,data), ('https://attacker.test',data | {'csrfmiddlewaretoken':token})]:
        try:
            request(opener,payload,origin)
        except urllib.error.HTTPError as error:
            assert error.code == 403, 'Unexpected rejection status'
        else:
            raise AssertionError('Unsafe login request was accepted')
    with request(opener,data | {'csrfmiddlewaretoken':token}) as response:
        assert response.status == 200 and '/login/' not in response.url, 'Login failed'
    assert any(cookie.name == 'sessionid' for cookie in jar), 'No authenticated session'
    print('HTTPS-origin login through internal HTTP passed; missing token and foreign origin rejected.')
