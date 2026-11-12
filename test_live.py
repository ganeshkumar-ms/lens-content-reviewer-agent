import urllib.request
import json
import ssl
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

API_URL = "https://9h9cdk5cxi.execute-api.us-east-1.amazonaws.com"
CF_URL = "https://d1hwt5aw0fwzod.cloudfront.net"

print("1. Testing Live /api/health...")
req = urllib.request.Request(f"{API_URL}/api/health")
with urllib.request.urlopen(req, context=ctx) as res:
    data = json.loads(res.read().decode())
    print("   Health Response:", data)
    assert data.get("status") == "ok"
    assert data.get("agent") == "LENS"

print("\n2. Testing Live Typo Greeting 'ji'...")
post_data = json.dumps({"text": "ji", "conversation_history": []}).encode()
req = urllib.request.Request(
    f"{API_URL}/api/review",
    data=post_data,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, context=ctx) as res:
    data = json.loads(res.read().decode())
    print("   Greeting Response:", data)
    assert data.get("type") == "chat"
    assert len(data.get("message", "")) > 10

print("\n3. Testing Live Content Review on Sample SLA Draft...")
sample_text = (
    "Customer Support SLA Agreement\n"
    "Section 2: Premium clients receive 1-hour critical response SLA.\n"
    "Section 8: All critical issues will be acknowledged within 4 business hours.\n"
    "Section 11: Please submit escalations as soon as possible."
)
post_data = json.dumps({"text": sample_text, "conversation_history": []}).encode()
req = urllib.request.Request(
    f"{API_URL}/api/review",
    data=post_data,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, context=ctx) as res:
    data = json.loads(res.read().decode())
    print("   Review Status:", data.get("publish_readiness", {}).get("status"))
    print("   Score:", data.get("publish_readiness", {}).get("score"))
    print("   Summary:", data.get("publish_readiness", {}).get("summary"))
    print("   Total Issues:", len(data.get("issues", [])))
    if data.get("issues"):
        print("   First Issue:", data.get("issues")[0].get("issue"))
        print("   Fix:", data.get("issues")[0].get("suggested_fix"))

print("\n4. Testing Live CloudFront Frontend...")
req = urllib.request.Request(CF_URL)
with urllib.request.urlopen(req, context=ctx) as res:
    html = res.read().decode()
    print("   CloudFront Status:", res.status)
    assert "<title>LENS" in html
    print("   Title verified in HTML!")

print("\n=======================================================")
print(" ALL LIVE VERIFICATION TESTS PASSED WITH ZERO ERRORS!")
print("=======================================================")
