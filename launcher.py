import os
import json
import http.client


if not os.environ.get('DEBUG') == 'true':
    print('Downloading latest version of GUI and client')
    conn = http.client.HTTPSConnection('stachelapi.ribica.dev')

    conn.request('GET', '/static/version-info.json')
    versions = json.load(conn.getresponse())

    conn.request('GET', '/static/gui/v{}.py'.format(versions['gui']))
    response = conn.getresponse()
    data = response.read()
    if response.status == 200:
        with open('gui.py', 'wb') as f:
            f.write(data)
    else:
        raise RuntimeError(f'Failed to download GUI code, got status code {response.status}')


    conn.request('GET', '/static/mcclient/v{}.js'.format(versions['client']))
    response = conn.getresponse()
    if response.status == 200:
        with open('main.js', 'wb') as f:
            f.write(response.read())
    else:
        raise RuntimeError(f'Failed to download client code, got status code {response.status}')
else:
    print('DEBUG mode enabled, will not download gui & client')

import sys, os
sys.path.append(os.getcwd())  # required if we use portable python

import importlib
try:
    gui = importlib.import_module('gui')
except ModuleNotFoundError:
    print('gui.py not found, if this is your first time running please remove DEBUG flag')
    sys.exit(1)
print('Launching gui')
gui.main()
