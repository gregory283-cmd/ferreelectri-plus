import importlib
packages = ['google.auth', 'google.oauth2', 'google_auth_oauthlib', 'oauth2client']
for pkg in packages:
    try:
        importlib.import_module(pkg)
        print(pkg, 'installed')
    except Exception as e:
        print(pkg, 'missing', type(e).__name__)
