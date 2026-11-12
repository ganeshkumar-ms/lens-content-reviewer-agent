import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / 'backend'
sys.path.insert(0, str(BACKEND_DIR))

from services import lens_service

print("Testing greeting 'ji':")
resp = lens_service.review_content("ji")
print("Response:", resp)

print("\nTesting review on sample text with contradiction:")
sample = """
Standard Operating Procedure - Refund Policy
Section 1: Customers may request a refund within 30 days of purchase.
Section 5: All refund requests must be submitted within 14 days of invoice date.
Section 8: Refunds will be processed as soon as possible.
"""
review_resp = lens_service.review_content(sample, file_name="refund_policy.txt")
print("Publish Readiness:", review_resp.get("publish_readiness"))
print("Issues found:", len(review_resp.get("issues", [])))
print("First issue:", review_resp.get("issues", [{}])[0])

