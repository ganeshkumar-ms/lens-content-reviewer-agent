# LENS · Project Memory & Architecture Guide
**Agent #4: Enterprise Content Reviewer & Consistency Auditor**

---

## 1. Executive Summary & Live AWS Deployment

| Asset | AWS Endpoint / Identifier |
| :--- | :--- |
| **Agent Name** | **LENS** |
| **Mission** | Content Reviewer & Consistency Auditor |
| **Primary Question** | *"Is this content clear, complete, consistent and ready to publish?"* |
| **CloudFront Live URL** | **[`https://d1hwt5aw0fwzod.cloudfront.net`](https://d1hwt5aw0fwzod.cloudfront.net)** |
| **API Gateway (HTTP API)** | `https://9h9cdk5cxi.execute-api.us-east-1.amazonaws.com` |
| **AWS Account** | `984625844016` (us-east-1) |
| **S3 Hosting Bucket** | `s3://lens-ui-984625844016` (Protected with CloudFront Origin Access Control) |
| **AWS Lambda Compute** | `lens-backend-api` (Python 3.11, Bedrock Nova Pro Converse API) |
| **IAM Execution Role** | `arn:aws:iam::984625844016:role/lens-backend-lambda-role` |
| **Local Project Path** | `c:\Users\ELCOT\OneDrive\Desktop\Agent\lens\` |
| **Beginner Study Guide PDF** | `c:\Users\ELCOT\OneDrive\Desktop\Agent\lens\LENS_BEGINNER_STUDY_GUIDE.pdf` |

---

## 2. Core Question & Enterprise Problem Solved

### Core Question:
> *"Is this content clear, complete, consistent and ready to publish?"*

### Problem:
Before publishing documents (customer communications, SLAs, technical specs, policy guides, press releases, contracts), authors often create internal contradictions:
- Section 2 says *30 days to respond*, while Section 6 says *45 days*.
- Section A quotes *\$500 deductible*, while Section D quotes *\$250*.
- Deadlines use vague phrasing (*"as soon as possible"*, *"in a timely manner"*), exposing the enterprise to dispute.
- Critical prerequisites or contact escalation channels are missing.

### What LENS Does:
1. **Publish Readiness Score & Status:**
   - 0–100 objective score.
   - Status badge: `READY_TO_PUBLISH` (85–100), `NEEDS_REVISION` (50–84), `CRITICAL_BLOCKERS` (0–49).
   - Executive 2-sentence summary.
2. **Contradiction & Inconsistency Detection:**
   - Scans dates, amounts, timelines, and opposing instructions across separate sections.
3. **Actionable Review Matrix (Issue &rarr; Why It Matters &rarr; Suggested Fix):**
   - Severity pills: `CRITICAL`, `WARNING`, `SUGGESTION`.
   - Verbatim excerpt with section location.
   - Impact / risk analysis ("Why It Matters").
   - One-click copyable replacement text ("Suggested Fix").
4. **Pre-Publish Checklist & Content Strengths:**
   - Highlights what is already clear, and lists remaining tasks before dissemination.
5. **Side-by-Side Live Document Viewer:**
   - Previews PDFs, Word, Excel, CSV, and Text documents with one-click metadata download.

---

## 3. UI/UX Innovations & Focus Animation Design

- **Theme Palette:**
  - Primary Accent: `#08d6a2` (Emerald Mint)
  - Secondary Accent: `#0b3d32` (Forest Emerald)
  - Background: `#02110d` (Deep Mint Obsidian)
  - Panel: `#06231b`
- **Focus Lens Sweep Animation:**
  - Dynamic keyframe animation `@keyframes lensFocusSweep` with a rotating lens handle and sweeping beam simulating an optical inspection glass.
- **Header:**
  - Clean title and single `HOME` navigation button.
- **Sidebar:**
  - `+ NEW AUDIT` button, `RECENT CONVERSATIONS` list, inline session rename, and delete confirmation.
  - Zero storage of empty conversations.

---

## 4. Zero-Bug Architecture Standards (Lessons from Taxora, Claria & Index)

1. **Automated Production Build Injection:**
   - `deploy_aws.py` automatically injects the deployed API Gateway endpoint into `frontend/.env.production` and triggers a clean `npm run build` prior to S3 upload. This guarantees requests never route to CloudFront's S3 fallback `index.html`.
2. **Bedrock Converse Alternation & Typo Interceptor:**
   - Strict `user` / `assistant` role alternation starting with `user`.
   - Rapid regex matcher intercepts short greetings/typos (`"ji"`, `"hi"`, `"helo"`, `"hw r u"`), returning instant responses without incurring Bedrock `ValidationException`.
3. **Single Document Badge in User Bubble:**
   - Suppresses raw `[ATTACHED DOCUMENT...]` markers.
   - AI answer cards do not duplicate the open button.
4. **Valid Font-Weights & Smooth Scrolling:**
   - Standard multiples of 100 (`400`, `500`, `600`, `700`, `800`).
   - `.messages` has `overflow-y: auto; scroll-behavior: smooth;` and automatically scrolls to the latest AI reply on session switch.
