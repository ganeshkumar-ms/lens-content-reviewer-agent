import urllib.request
import json
import ssl
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
body = bytearray()
body.extend(f'--{boundary}\r\n'.encode())
body.extend(b'Content-Disposition: form-data; name="file"; filename="test.pdf"\r\n')
body.extend(b'Content-Type: application/pdf\r\n\r\n')

pdf_path = Path(r'c:\Users\ELCOT\OneDrive\Desktop\Agent\lens-content-reviewer-agent\LENS_BEGINNER_STUDY_GUIDE.pdf')
body.extend(pdf_path.read_bytes())
body.extend(b'\r\n')
body.extend(f'--{boundary}\r\n'.encode())
body.extend(b'Content-Disposition: form-data; name="text"\r\n\r\n\r\n')
body.extend(f'--{boundary}\r\n'.encode())
body.extend(b'Content-Disposition: form-data; name="conversation_history"\r\n\r\n[]\r\n')
body.extend(f'--{boundary}--\r\n'.encode())

req = urllib.request.Request(
    'https://9h9cdk5cxi.execute-api.us-east-1.amazonaws.com/api/review',
    data=bytes(body),
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
)

try:
    print("Sending PDF to live API Gateway...")
    with urllib.request.urlopen(req, context=ctx, timeout=60) as res:
        print('STATUS:', res.status)
        raw = res.read().decode('utf-8', errors='replace')
        print('RESPONSE:', raw[:500])
except Exception as e:
    print('ERROR:', e)
    if hasattr(e, 'read'):
        print('ERR BODY:', e.read().decode('utf-8', errors='replace'))

