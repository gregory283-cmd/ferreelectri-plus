import http.cookiejar, urllib.request, urllib.parse

base = 'http://127.0.0.1:8000'
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
# GET root to obtain CSRF cookie (if set)
resp = opener.open(base + '/')
# extract csrftoken
csrf = None
for c in jar:
    if c.name == 'csrftoken':
        csrf = c.value
        break
print('CSRF:', csrf)
# Prepare POST
url = base + '/producto/A0001/agregar/'
data = urllib.parse.urlencode({'cantidad': '1'}).encode('utf-8')
headers = {
    'X-Requested-With': 'XMLHttpRequest'
}
if csrf:
    headers['X-CSRFToken'] = csrf
req = urllib.request.Request(url, data=data, headers=headers)
try:
    r = opener.open(req)
    print('STATUS', r.getcode())
    print(r.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print('HTTP ERROR', e.code)
    try:
        print(e.read().decode('utf-8'))
    except Exception:
        pass
except Exception as e:
    print('ERROR', str(e))
