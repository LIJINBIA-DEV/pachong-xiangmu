import os
import socket
import urllib.request

urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3).close()
ports = (5900, 6080, 17890, 19090) if os.environ.get('MEDIACRAWLER_BUNDLED_PROXY') == '1' else (5900, 6080)
for port in ports:
    with socket.create_connection(('127.0.0.1', port), timeout=2):
        pass
