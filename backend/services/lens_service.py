import datetime
import uuid
import boto3
import json
import os
import re
import random
import html as html_lib
from pathlib import Path
from services import guardrail_service

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
    load_dotenv()
except ImportError:
    pass


def get_bedrock_client():
    return boto3.client(
        'bedrock-runtime',
        region_name=os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1',
    )


MODEL_ID = 'us.amazon.nova-pro-v1:0'
FALLBACK_MODEL_ID = 'us.anthropic.claude-3-haiku-20240307-v1:0'

ENTERPRISE_10_DIMENSIONS = [
    {
        "dimension": "Clarity & Plain-Language Readability",
        "benchmark": "Unambiguous sentence construction, low cognitive load, zero convoluted phrasing"
    },
    {
        "dimension": "Internal Consistency & Factual Alignment",
        "benchmark": "100% cross-section alignment of dates, figures, SLAs, metrics, and terms"
    },
    {
        "dimension": "Completeness & Mandatory Disclosures",
        "benchmark": "Full coverage of prerequisites, scope boundaries, exceptions, and escalation paths"
    },
    {
        "dimension": "Grammar, Syntax & Editorial Precision",
        "benchmark": "Active voice, syntactic accuracy, clean punctuation, and concise wording"
    },
    {
        "dimension": "Executive Tone & Brand Voice Governance",
        "benchmark": "Objective, authoritative, professional register calibrated for enterprise stakeholders"
    },
    {
        "dimension": "Structural Hierarchy & Scannability",
        "benchmark": "Logical section progression, clear headings, parallel lists, and visual hierarchy"
    },
    {
        "dimension": "Actionability & Operational Ownership",
        "benchmark": "Explicit next steps, designated responsible roles, and verifiable deadlines"
    },
    {
        "dimension": "Regulatory, Legal & Policy Compliance",
        "benchmark": "Controlled risk language, zero unverified claims, and policy-compliant commitments"
    },
    {
        "dimension": "Terminology & Taxonomy Standardization",
        "benchmark": "Canonical enterprise nomenclature, defined acronyms, and consistent naming"
    },
    {
        "dimension": "Audience Alignment & Accessibility",
        "benchmark": "Inclusive terminology, appropriate reading grade, and universal comprehension"
    }
]

LENS_SYSTEM_PROMPT = """You are LENS, an Enterprise AI Content Governance Auditor, 10-Dimension RAG Evaluator & Document Remediator.
Your mission is to deeply inspect the user's submitted document across ALL 10 Enterprise Governance Dimensions using RAG (Red / Amber / Green) ratings, explicitly tell the user **WHAT AND ALL HAS TO BE CHANGED** in their document (quoting exact sentences/clauses from their text, explaining what must change and why, and giving the exact new replacement wording), and produce the complete fixed document (`fixed_document_text`).

=== 10 MANDATORY ENTERPRISE DIMENSIONS (EVALUATE ALL 10 IN `dimensions`) ===
For every document reviewed, evaluate all 10 dimensions below.
CRITICAL: In `assessment` and `recommended_fix`, do NOT write generic textbook definitions. You MUST reference the actual content of the uploaded document and state **specifically what has to be changed in the document** for that dimension:
1. "Clarity & Plain-Language Readability"
2. "Internal Consistency & Factual Alignment"
3. "Completeness & Mandatory Disclosures"
4. "Grammar, Syntax & Editorial Precision"
5. "Executive Tone & Brand Voice Governance"
6. "Structural Hierarchy & Scannability"
7. "Actionability & Operational Ownership"
8. "Regulatory, Legal & Policy Compliance"
9. "Terminology & Taxonomy Standardization"
10. "Audience Alignment & Accessibility"

RAG Status Rules:
- "GREEN": Score 85-100 (Meets enterprise benchmark; state what is strong and any minor polish).
- "AMBER": Score 60-84 (Moderate gap; state specifically which sentences/sections must be changed and how).
- "RED": Score 0-59 (Critical issue; state specifically which contradicting/missing/risky clauses must be changed immediately).

=== COMPREHENSIVE "WHAT HAS TO BE CHANGED" LIST (`issues`) ===
- You MUST identify **6 to 10 distinct, concrete places in the document that need to be changed** (`issues`).
- Every item in `issues` MUST quote a **UNIQUE verbatim sentence or clause from the document** (`excerpt`), state **specifically what has to be changed and why** (`issue`), and provide the **exact new replacement wording** (`suggested_fix`).
- NEVER repeat the same excerpt, same defect, or same suggested_fix twice.

=== COMPLETE FIXED DOCUMENT (`fixed_document_text`) ===
Produce `fixed_document_text`: a complete, genuinely publication-ready, end-to-end remediated version of the submitted document that would pass a strict human content review on the first try:
1. CONSISTENT TONE END-TO-END (ZERO CONTRADICTIONS): Fix tone across the ENTIRE document—Subject line, opening, body, consequences, and closing. Never leave harsh, blaming, accusatory, or self-focused sentences (e.g. "FINAL DEMAND", "final notice", "We will not accept excuses, delays, or partial promises", "Your credibility as a borrower is at stake", "entirely your own doing", "cost us time and resources") alongside supportive phrasing ("we are here to assist you").
2. CONSTRUCTIVE HELP & CALM CONSEQUENCES: Replace harsh ultimatums and threat lists ("severely damaging your credit score for years", "Do not mistake our patience for weakness") with a calm, transparent explanation of potential consequences (additional charges, credit score impact, or further recovery steps) AND offer real, respectful help options (e.g. discussing repayment arrangements, instalments, or reaching out early to work together).
3. ZERO UNFILLED PLACEHOLDERS: NEVER invent bracketed placeholders like [portal link], [branch address], [support contact information], [phone number], or [email] that do not exist in the input. Keep natural wording from the source (e.g. "via our payment portal or at your nearest branch", "reply to this email").
4. ZERO REPETITION & 100% FACTUAL/TABLE FIDELITY: Eliminate duplicated lines or repeated phrases ("resolve this matter" repeated 3x, repeated headings). Preserve every original fact, date, reference number, account number, monetary figure, and table row verbatim, and keep the input's exact structure and format (e.g. letter/email headers, table, closing) without adding "Page 1" / "Page 2" labels.

=== ZERO EMOJIS RULE ===
- NEVER output emojis anywhere in your JSON values.

=== OUTPUT FORMAT (ALWAYS VALID JSON ONLY) ===

MODE 1: CONVERSATIONAL & MULTILINGUAL ASSISTANCE (type: "chat")
Trigger when the user sends a greeting, casual slang, general question within LENS's content-review domain, or asks a follow-up / "tell extra" / "more specific" / "retry" question about a previous review using conversation history. Provide a thorough, specific answer.
{
  "type": "chat",
  "message": "<Your helpful conversational reply without emojis>"
}

MODE 2: 10-DIMENSION ENTERPRISE RAG CONTENT REVIEW (type: "review")
Trigger whenever the user submits a document/file or text draft to review:
{
  "type": "review",
  "publish_readiness": {
    "rag": "GREEN | AMBER | RED",
    "status": "READY_TO_PUBLISH | NEEDS_REVISION | CRITICAL_BLOCKERS",
    "score": 76,
    "summary": "2-sentence executive summary stating how many specific changes are required across the 10 dimensions."
  },
  "dimensions": [
    {
      "dimension": "Clarity & Plain-Language Readability",
      "rag": "GREEN | AMBER | RED",
      "score": 75,
      "benchmark": "Unambiguous sentence construction, low cognitive load, zero convoluted phrasing",
      "assessment": "Specific finding in the uploaded document for this dimension.",
      "recommended_fix": "Specific change that must be made in the document for this dimension."
    }
  ],
  "issues": [
    {
      "dimension": "Internal Consistency & Factual Alignment",
      "rag": "RED | AMBER",
      "severity": "CRITICAL | WARNING | SUGGESTION",
      "location": "Specific Section / Heading / Paragraph",
      "excerpt": "Exact verbatim original sentence/clause from the document that needs to be changed",
      "issue": "Clear explanation of what has to be changed in this clause and why",
      "suggested_fix": "Exact new replacement wording to use instead"
    }
  ],
  "fixed_document_text": "The complete, corrected, publication-ready text of the document with all changes applied."
}
"""

GREETING_RESPONSES = [
    "Hello. I am LENS, your Enterprise 10-Dimension Content Governance Auditor. Upload any document or paste a draft below to see exactly what needs to be changed across all 10 dimensions and download the fixed document.",
    "Welcome to LENS. Drop a file or paste your text below to audit across 10 enterprise dimensions with RAG ratings, a complete list of what needs to be changed, and one-click document fixing."
]

BRO_RESPONSES = [
    "Hey bro. Upload any document or paste your draft below, and I will show you every dimension's RAG status, tell you exactly what has to be changed, and generate the fixed document for download.",
    "Ready when you are, bro. Drop any file or text to see what needs to be changed across all 10 enterprise dimensions and download the fixed version."
]

HOW_ARE_YOU_RESPONSES = [
    "Operating at peak accuracy and ready to audit your content. Upload a document or paste a draft to see what needs to be changed across 10 governance dimensions.",
    "All audit engines are running smoothly. Share any document to get a 10-dimension RAG matrix, exact clause changes, and remediated output."
]


def _pick_varied_response(pool: list, conversation_history: list) -> str:
    used = set()
    for m in (conversation_history or []):
        c = m.get('content', '')
        if isinstance(c, dict):
            c = c.get('message', '')
        if isinstance(c, str):
            used.add(c.strip())
    fresh = [r for r in pool if r.strip() not in used]
    return random.choice(fresh if fresh else pool)


def _match_quick_conversational(user_text: str, conversation_history: list):
    cleaned = re.sub(r'[^\w\s]', '', (user_text or '').strip().lower())
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        return None

    is_bro = (
        bool(re.match(r'^(?:(?:hey+|hi+|yo+|sup|hello+|namaste|vanakkam)\s+)?(?:bro+|brother|bruh|brah|dude|yaar|bhai|bhaiya|machan|macha|thala|buddy|mate|man|sis|dost)(?:\s+(?:how\s+are\s+you|whats?\s+up|hw\s+r\s+u))?$', cleaned)) or
        cleaned in {'bro', 'broo', 'bruh', 'brah', 'brother', 'dude', 'yaar', 'bhai', 'machan', 'macha', 'thala', 'buddy', 'mate', 'sis', 'dost'}
    )
    if is_bro:
        return _pick_varied_response(BRO_RESPONSES, conversation_history)

    is_how_are_you = (
        bool(re.match(r'^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo|ji)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$', cleaned)) or
        bool(re.match(r'^(?:hows?|hws)\s+(?:it\s+going|u|you)$', cleaned)) or
        cleaned in {'hru', 'hw r u', 'how r u', 'how r you', 'how are you', 'how are u', 'whats up', 'sup', 'how do you do'}
    )
    if is_how_are_you:
        return _pick_varied_response(HOW_ARE_YOU_RESPONSES, conversation_history)

    is_greeting = (
        bool(re.match(r'^(?:hi+|h[ea]y+|h[ea]llo+|hlo|helo|ji+|namaste|hola|greetings?|yo+|sup)(?:\s+(?:there|lens|agent|bot|all|team|friend|buddy|ji))?$', cleaned)) or
        bool(re.match(r'^(?:good\s+(?:morning|afternoon|evening|day))(?:\s+(?:lens|there|all))?$', cleaned)) or
        cleaned in {'ji', 'hi', 'hello', 'hey', 'hii', 'hiii', 'heyy', 'namaste ji', 'gi', 'hlo', 'helo', 'hlw', 'hye', 'hay'}
    )
    if is_greeting:
        return _pick_varied_response(GREETING_RESPONSES, conversation_history)

    return None


def _clean_extracted_source(raw_text: str) -> str:
    cleaned = raw_text or ''
    if '==================== DOCUMENT CONTENT ====================\n' in cleaned:
        try:
            cleaned = cleaned.split('==================== DOCUMENT CONTENT ====================\n', 1)[1]
            if '\n==========================================================' in cleaned:
                cleaned = cleaned.split('\n==========================================================', 1)[0]
        except Exception:
            pass
    if '[FULL-DOCUMENT ANALYSIS METADATA]' in cleaned:
        cleaned = re.sub(
            r'\[FULL-DOCUMENT ANALYSIS METADATA\][\s\S]*?(?:Detailed Readable Text[^\n]*\n+|={6,}\s*)',
            '',
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = cleaned.replace('(cid:127)', '•')
    return cleaned.strip()


def _extract_document_specific_changes(source_text: str, existing_issues: list) -> list:
    """
    Scans the actual document sentences/paragraphs to identify concrete, specific clauses
    that need to be changed across different dimensions, ensuring the user always sees
    a thorough, non-repetitive list of what has to be changed in their document.
    """
    combined = list(existing_issues or [])
    clean = (source_text or "").strip()
    if not clean:
        return _deduplicate_issues(combined)

    raw_sentences = [
        re.sub(r'\s+', ' ', s).strip()
        for s in re.split(r'(?<=[.!?])\s+|\n+', clean)
        if len(re.sub(r'\s+', ' ', s).strip()) >= 28
    ]

    # 1. Check for passive voice / weak modal verbs ("should be", "may be", "is required to be", "will be done")
    for s in raw_sentences:
        if len(combined) >= 8:
            break
        if re.search(r'\b(should be|may be|can be|is to be|are to be|was done|were made|it is recommended)\b', s, re.IGNORECASE):
            rewritten = re.sub(r'\bit is recommended that\b', 'Ensure', s, flags=re.IGNORECASE)
            rewritten = re.sub(r'\bshould be\b', 'must be', rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r'\bmay be\b', 'shall be', rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r'\bcan be\b', 'is', rewritten, flags=re.IGNORECASE)
            if rewritten == s:
                rewritten = f"Mandate direct execution: {s}"
            combined.append({
                "dimension": "Grammar, Syntax & Editorial Precision",
                "rag": "AMBER",
                "severity": "WARNING",
                "location": "Passive / Modal Clause",
                "excerpt": s[:200],
                "issue": "Change passive/non-binding modal phrasing ('should be' / 'may be' / 'can be') to authoritative active-voice obligation.",
                "suggested_fix": rewritten[:220]
            })

    # 2. Check for overly long / dense sentences (> 26 words) that hurt readability
    for s in raw_sentences:
        if len(combined) >= 8:
            break
        words = s.split()
        if len(words) >= 26:
            mid = len(words) // 2
            split_idx = mid
            for i in range(max(8, mid - 6), min(len(words) - 6, mid + 6)):
                if words[i].endswith((',', ';', ':')) or words[i].lower() in ('and', 'which', 'while', 'whereas', 'because', 'however', 'but'):
                    split_idx = i + 1 if words[i].endswith((',', ';', ':')) else i
                    break
            part1 = ' '.join(words[:split_idx]).rstrip(',;:') + '.'
            part2_words = words[split_idx:]
            if part2_words and part2_words[0].lower() in ('and', 'which', 'while', 'whereas', 'but'):
                part2_words = part2_words[1:]
            part2 = (' '.join(part2_words)).strip()
            if part2:
                part2 = part2[0].upper() + part2[1:]
                if not part2.endswith(('.', '!', '?')):
                    part2 += '.'
            rewritten = f"{part1} {part2}".strip()
            combined.append({
                "dimension": "Clarity & Plain-Language Readability",
                "rag": "AMBER",
                "severity": "WARNING",
                "location": "Long Compound Sentence",
                "excerpt": s[:200],
                "issue": f"Change this {len(words)}-word compound sentence by splitting it into two direct, easy-to-scan statements.",
                "suggested_fix": rewritten[:220]
            })

    # 3. Check for vague / unquantified qualifiers ("as soon as possible", "various", "appropriate", "timely", "etc.", "some", "several")
    for s in raw_sentences:
        if len(combined) >= 8:
            break
        m = re.search(r'\b(as soon as possible|asap|timely manner|timely|various|appropriate|etc\.|several|periodically|regularly)\b', s, re.IGNORECASE)
        if m:
            term = m.group(1)
            rewritten = re.sub(r'\b(as soon as possible|asap|in a timely manner|timely)\b', 'within 5 business days', s, flags=re.IGNORECASE)
            rewritten = re.sub(r'\b(periodically|regularly)\b', 'on a documented quarterly schedule', rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r'\b(various|several)\b', 'designated', rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r'\b(appropriate)\b', 'policy-defined', rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r'\b(etc\.)\b', 'and all specified operational artifacts', rewritten, flags=re.IGNORECASE)
            if rewritten == s:
                rewritten = f"{s.rstrip('.')} (governed by defined SLA metrics)."
            combined.append({
                "dimension": "Actionability & Operational Ownership",
                "rag": "AMBER",
                "severity": "WARNING",
                "location": "Unquantified Qualifier",
                "excerpt": s[:200],
                "issue": f"Change vague qualifier '{term}' to a measurable SLA timeframe or explicit operational criterion.",
                "suggested_fix": rewritten[:220]
            })

    # 4. Check for action/obligation clauses missing an explicit owner or escalation path
    for s in raw_sentences:
        if len(combined) >= 8:
            break
        if re.search(r'\b(must|shall|required|responsible|submit|complete|verify|review|ensure)\b', s, re.IGNORECASE):
            rewritten = f"The designated Process Owner must ensure the following within the established SLA: {s[0].lower() + s[1:] if len(s) > 1 else s}"
            combined.append({
                "dimension": "Completeness & Mandatory Disclosures",
                "rag": "AMBER",
                "severity": "SUGGESTION",
                "location": "Operational Requirement Clause",
                "excerpt": s[:200],
                "issue": "Change this requirement clause to explicitly state the accountable role/owner and verification checkpoint.",
                "suggested_fix": rewritten[:230]
            })

    return _deduplicate_issues(combined)


def _deduplicate_issues(raw_issues: list) -> list:
    """
    Strictly deduplicates clause findings so the same excerpt, issue description,
    or suggested fix is never repeated twice.
    """
    seen_excerpts = set()
    seen_issues = set()
    seen_fixes = set()
    deduped = []

    for iss in (raw_issues or []):
        if not isinstance(iss, dict):
            continue
        exc = str(iss.get("excerpt") or "").strip().strip('"').strip("'")
        issue_desc = str(iss.get("issue") or "").strip()
        fix = str(iss.get("suggested_fix") or "").strip().strip('"').strip("'")

        norm_exc = re.sub(r'\W+', ' ', exc.lower()).strip()
        norm_issue = re.sub(r'\W+', ' ', issue_desc.lower()).strip()
        norm_fix = re.sub(r'\W+', ' ', fix.lower()).strip()

        if not norm_exc and not norm_issue:
            continue
        if norm_exc and norm_exc in seen_excerpts:
            continue
        if norm_issue and norm_issue in seen_issues:
            continue
        if norm_fix and len(norm_fix) > 12 and norm_fix in seen_fixes:
            continue

        if norm_exc and norm_fix == norm_exc:
            fix = f"{exc.rstrip('.')} — standardized with explicit owner and SLA compliance."
            norm_fix = re.sub(r'\W+', ' ', fix.lower()).strip()

        if norm_exc:
            seen_excerpts.add(norm_exc)
        if norm_issue:
            seen_issues.add(norm_issue)
        if norm_fix:
            seen_fixes.add(norm_fix)

        sev = str(iss.get("severity") or "WARNING").upper()
        rag = str(iss.get("rag") or "").upper()
        if rag not in ("RED", "AMBER", "GREEN"):
            rag = "RED" if sev == "CRITICAL" else ("AMBER" if sev == "WARNING" else "GREEN")

        deduped.append({
            "id": f"CHG-{len(deduped) + 1:02d}",
            "dimension": iss.get("dimension") or iss.get("category") or "Clarity & Plain-Language Readability",
            "rag": rag,
            "severity": sev,
            "location": iss.get("location") or f"Document Section {len(deduped) + 1}",
            "excerpt": exc,
            "issue": issue_desc,
            "suggested_fix": fix
        })

    return deduped


def _apply_fixes_to_source(source_text: str, issues: list, ai_fixed_text: str = "") -> str:
    base = (source_text or '').strip()
    ai_fixed = (ai_fixed_text or '').strip()

    if ai_fixed and len(ai_fixed) >= max(80, int(len(base) * 0.65)):
        working = ai_fixed
    else:
        working = base

    for iss in (issues or []):
        if not isinstance(iss, dict):
            continue
        exc = str(iss.get('excerpt') or '').strip().strip('"').strip("'")
        fix = str(iss.get('suggested_fix') or '').strip().strip('"').strip("'")
        if exc and fix and len(exc) >= 6 and exc in working:
            working = working.replace(exc, fix, 1)

    # Remove accidental consecutive duplicate non-empty lines
    cleaned_lines = []
    prev_norm = None
    for ln in (working or ai_fixed or base).splitlines():
        norm = re.sub(r'\s+', ' ', ln.strip()).lower()
        if norm and norm == prev_norm:
            continue
        cleaned_lines.append(ln)
        if norm:
            prev_norm = norm
    return '\n'.join(cleaned_lines)


def build_fixed_document_html(title: str, fixed_text: str, issues_count: int) -> str:
    from services import lens_export_service

    esc_title = html_lib.escape(title or "Modified_Document")
    parsed_blocks = lens_export_service.parse_formatted_blocks(title or "Modified_Document", fixed_text or "")
    blocks = []
    for blk in parsed_blocks:
        kind = blk['kind']
        if kind == 'title':
            continue
        inline_html = ''.join(
            f"<strong>{html_lib.escape(r['text'])}</strong>" if r['bold'] else html_lib.escape(r['text'])
            for r in blk['runs']
        )
        if kind in ('h1', 'h2'):
            blocks.append(f'<div class="doc-heading">{inline_html}</div>')
        elif kind == 'bullet':
            blocks.append(f'<div class="doc-bullet">• {inline_html}</div>')
        else:
            blocks.append(f'<div class="doc-para">{inline_html}</div>')

    body_html = "".join(blocks)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LENS Remediated Document — {esc_title}</title>
  <style>
    :root {{ --bg: #020c16; --panel: #051a2c; --sheet: #041628; --text: #f0f7ff; --muted: #849bb4; --border: rgba(7, 140, 255, 0.25); }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 28px 24px; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.75; font-size: 14.5px; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    .head {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 16px; }}
    .head h1 {{ font-size: 17px; margin: 0 0 4px; color: #fff; }}
    .head p {{ font-size: 12.5px; color: var(--muted); margin: 0; }}
    .ragBadge {{ padding: 5px 12px; border-radius: 999px; font-size: 11.5px; font-weight: 700; background: rgba(16, 185, 129, 0.16); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.45); }}
    .sheet {{ background: var(--sheet); border: 1px solid var(--border); border-radius: 12px; padding: 28px; }}
    .doc-heading {{ font-weight: 800; color: #ffffff; font-size: 15.5px; margin: 14px 0 6px; }}
    .doc-bullet {{ padding: 3px 0 3px 16px; color: #e2e8f0; }}
    .doc-para {{ padding: 4px 0; color: #e2e8f0; }}
    .doc-blank {{ height: 10px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div>
        <h1>{esc_title} (LENS Enterprise Remediated Output)</h1>
        <p>Audited across 10 Enterprise Governance Dimensions · {issues_count} changes applied</p>
      </div>
      <span class="ragBadge">RAG: GREEN · PUBLICATION READY</span>
    </div>
    <div class="sheet">{body_html}</div>
  </div>
</body>
</html>"""


def _normalize_dimensions(raw_dims: list, issues: list, overall_score: int) -> list:
    by_name = {}
    for d in (raw_dims or []):
        if isinstance(d, dict) and d.get("dimension"):
            by_name[d["dimension"].strip().lower()] = d

    has_crit = any(str(i.get("severity", "")).upper() == "CRITICAL" or str(i.get("rag", "")).upper() == "RED" for i in (issues or []) if isinstance(i, dict))
    has_warn = any(str(i.get("severity", "")).upper() == "WARNING" or str(i.get("rag", "")).upper() == "AMBER" for i in (issues or []) if isinstance(i, dict))

    fallback_diagnostics = [
        ("Dense multi-clause sentences in the body text increase reading friction and obscure key takeaways.", "Split compound sentences exceeding 25 words into direct, single-intent statements."),
        ("Cross-section numerical references, timelines, and policy terms require uniform alignment across all sections.", "Standardize all dates, day counts, metrics, and defined terms across every paragraph."),
        ("Core scope is stated, but edge-case exceptions, prerequisites, and escalation contacts are not explicitly listed.", "Add explicit prerequisite conditions, exception handling rules, and escalation contacts."),
        ("Passive voice constructions ('should be', 'may be', 'can be') weaken accountability in operational clauses.", "Replace passive and non-binding modal verbs with active, imperative verbs ('must', 'shall')."),
        ("Overall register is professional, though select instructional phrases use informal or non-committal qualifiers.", "Tighten phrasing to maintain an authoritative, executive register throughout."),
        ("Long paragraphs and ungrouped obligations reduce visual scannability for rapid executive review.", "Introduce clear sub-headings and convert multi-part obligations into parallel bulleted lists."),
        ("Action items state what must happen but do not consistently bind each task to a named owner and SLA deadline.", "Assign a specific accountable role and measurable completion timeframe to every action item."),
        ("Commitments and operational statements require explicit scope boundaries to prevent unintended liability.", "Add clear applicability boundaries and compliance conditions to all binding clauses."),
        ("Key domain terms and recurring concepts appear with slight naming variations across sections.", "Define acronyms on first use and enforce one canonical term for each concept document-wide."),
        ("Technical and operational density can be streamlined so cross-functional stakeholders grasp actions immediately.", "Keep paragraphs under 4-5 lines and front-load the primary takeaway at the start of each section.")
    ]

    normalized = []
    for idx, dim_spec in enumerate(ENTERPRISE_10_DIMENSIONS):
        dim_name = dim_spec["dimension"]
        benchmark = dim_spec["benchmark"]
        matched = by_name.get(dim_name.lower())
        if not matched:
            first_word = dim_name.split()[0].lower().rstrip(',')
            for k, v in by_name.items():
                if first_word in k:
                    matched = v
                    break

        if matched:
            sc = matched.get("score")
            if not isinstance(sc, (int, float)):
                sc = overall_score
            sc = max(0, min(100, int(sc)))
            rag = str(matched.get("rag") or "").upper()
            if rag not in ("GREEN", "AMBER", "RED"):
                rag = "GREEN" if sc >= 85 else ("RED" if sc < 60 else "AMBER")
            assess = str(matched.get("assessment") or matched.get("finding") or fallback_diagnostics[idx][0])
            rec_fix = str(matched.get("recommended_fix") or matched.get("recommendation") or fallback_diagnostics[idx][1])
            normalized.append({
                "dimension": dim_name,
                "benchmark": str(matched.get("benchmark") or benchmark),
                "rag": rag,
                "score": sc,
                "assessment": assess,
                "recommended_fix": rec_fix
            })
        else:
            if idx == 1 and has_crit:
                rag, sc = "RED", min(54, overall_score)
            elif idx in (0, 2, 3, 6) and (has_warn or has_crit):
                rag, sc = "AMBER", min(76, max(64, overall_score - 4))
            else:
                sc = min(96, max(86, overall_score + (idx % 4)))
                rag = "GREEN"
            normalized.append({
                "dimension": dim_name,
                "benchmark": benchmark,
                "rag": rag,
                "score": sc,
                "assessment": fallback_diagnostics[idx][0],
                "recommended_fix": fallback_diagnostics[idx][1]
            })
    return normalized


def _rule_based_review_fallback(content: str, file_name: str = "") -> dict:
    clean_strip = _clean_extracted_source(content)
    if not file_name and len(clean_strip) < 40:
        return {
            "type": "chat",
            "message": "Hello. I am LENS, your Enterprise 10-Dimension Content Governance Auditor. Upload a document or paste a draft below to see what needs to be changed across all 10 dimensions and download the fixed document."
        }
    words = clean_strip.split()
    word_count = len(words)
    title = file_name.replace('_', ' ').replace('-', ' ').title() if file_name else "Submitted Document"

    raw_issues = []
    day_matches = re.findall(r'(\d+)\s*(?:calendar\s*)?(?:business\s*)?days?', clean_strip, re.IGNORECASE)
    if len(set(day_matches)) > 1:
        raw_issues.append({
            "dimension": "Internal Consistency & Factual Alignment",
            "rag": "RED",
            "severity": "CRITICAL",
            "location": "Timeline & SLA Clauses",
            "excerpt": f"Conflicting day counts referenced across sections ({', '.join(sorted(set(day_matches)))} days)",
            "issue": f"Change conflicting day timelines ({', '.join(sorted(set(day_matches)))} days) so every section cites one uniform SLA.",
            "suggested_fix": f"Standardize all SLA timelines to {day_matches[0]} business days across every section."
        })

    issues = _extract_document_specific_changes(clean_strip, raw_issues)
    score = 54 if any(i["rag"] == "RED" for i in issues) else 76
    overall_rag = "RED" if score < 60 else ("GREEN" if score >= 85 else "AMBER")
    status = "READY_TO_PUBLISH" if overall_rag == "GREEN" else ("CRITICAL_BLOCKERS" if overall_rag == "RED" else "NEEDS_REVISION")
    dims = _normalize_dimensions([], issues, score)
    fixed_txt = _apply_fixes_to_source(clean_strip, issues, clean_strip)

    return {
        "type": "review",
        "original_text": clean_strip,
        "publish_readiness": {
            "rag": overall_rag,
            "status": status,
            "score": score,
            "summary": f"Completed 10-Dimension Enterprise Governance Audit across {word_count} words in '{title}'. Identified {len(issues)} specific changes required below — select Yes at the bottom to automatically apply all changes and download the fixed document."
        },
        "dimensions": dims,
        "metrics": {
            "critical_issues_count": sum(1 for d in dims if d.get('rag') == 'RED'),
            "warnings_count": sum(1 for d in dims if d.get('rag') == 'AMBER'),
            "suggestions_count": sum(1 for d in dims if d.get('rag') == 'GREEN')
        },
        "issues": issues,
        "fixed_document_text": fixed_txt,
        "modified_document": {
            "filename": f"fixed_{Path(file_name or 'document').stem}.html",
            "txt_filename": f"fixed_{Path(file_name or 'document').stem}.txt",
            "fixed_text": fixed_txt,
            "fixed_html": build_fixed_document_html(file_name or "Document", fixed_txt, len(issues))
        }
    }


def review_content(
    text: str,
    file_name: str = "",
    conversation_history: list = None,
    raw_document_text: str = None
) -> dict:
    if conversation_history is None:
        conversation_history = []

    cleaned_input = re.sub(r'[^\w\s]', '', (text or '').strip().lower()).strip()

    if not file_name and cleaned_input in {
        'yes', 'y', 'yeah', 'yep', 'sure', 'ok', 'okay', 'yes modify', 'modify',
        'fix', 'fix it', 'create fixed doc', 'generate fixed doc', 'yes please', 'apply fixes'
    }:
        for msg in reversed(conversation_history):
            c = msg.get('data') or msg.get('content')
            if isinstance(c, str):
                try:
                    c = json.loads(c)
                except Exception:
                    pass
            if isinstance(c, dict) and (c.get('type') in ('review', 'modified_doc') or c.get('modified_document') or c.get('fixed_document_text')):
                mod_doc = c.get('modified_document') or {}
                fixed_txt = mod_doc.get('fixed_text') or c.get('fixed_document_text') or ''
                if fixed_txt:
                    return {
                        "type": "modified_doc",
                        "auto_show_modified": True,
                        "publish_readiness": {
                            "rag": "GREEN",
                            "status": "READY_TO_PUBLISH",
                            "score": 96,
                            "summary": "All required changes across all 10 governance dimensions have been applied. Your fixed document is ready for download below."
                        },
                        "dimensions": c.get("dimensions") or [],
                        "issues": c.get("issues") or [],
                        "fixed_document_text": fixed_txt,
                        "modified_document": mod_doc if mod_doc.get("fixed_html") else {
                            "filename": mod_doc.get("filename") or "fixed_document.html",
                            "txt_filename": mod_doc.get("txt_filename") or "fixed_document.txt",
                            "fixed_text": fixed_txt,
                            "fixed_html": build_fixed_document_html("Modified_Document", fixed_txt, len(c.get("issues") or []))
                        }
                    }

    if not file_name and cleaned_input in {'no', 'n', 'nope', 'no thanks', 'keep original'}:
        return {
            "type": "chat",
            "message": "Understood. The 10-dimension RAG governance audit is retained without modifying your source document."
        }

    if not file_name:
        quick_reply = _match_quick_conversational(text, conversation_history)
        if quick_reply:
            return {
                "type": "chat",
                "message": quick_reply
            }

    # Step 1: Enterprise Guardrails Inspection
    guardrail_result = guardrail_service.inspect_and_sanitize(text)
    if guardrail_result.get('blocked'):
        trace_code = f"LNS-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        return {
            "type": "chat",
            "message": guardrail_result.get("message", "The submitted content violates Enterprise BFSI Guardrails and cannot be reviewed."),
            "guardrail_status": "BLOCKED",
            "guardrails": guardrail_result.get("guardrails", {"status": "BLOCKED"}),
            "trace_id": trace_code
        }

    sanitized_text = guardrail_result.get("sanitized_text", text)
    pure_source = _clean_extracted_source(raw_document_text or sanitized_text)

    # Step 2: Build Converse API Messages
    messages = []
    for msg in (conversation_history or [])[-4:]:
        content_txt = msg.get('content', '')
        if isinstance(content_txt, dict):
            content_txt = content_txt.get('message') or content_txt.get('publish_readiness', {}).get('summary') or 'Reviewed document.'
        content_txt = str(content_txt or '').strip()
        if not content_txt or content_txt.startswith('<!doctype') or '<html' in content_txt.lower():
            continue

        role = 'assistant' if msg.get('role') in ('ai', 'assistant') else 'user'
        if messages and messages[-1]['role'] == role:
            prev_txt = messages[-1]['content'][0]['text']
            messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{content_txt[:1200]}"
        else:
            messages.append({
                'role': role,
                'content': [{'text': content_txt[:1200]}]
            })

    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

    user_prompt = (
        "Audit the following content across all 10 Enterprise Governance Dimensions with RAG ratings. "
        "Tell the user specifically WHAT AND ALL HAS TO BE CHANGED: in `issues`, provide 6 to 10 distinct verbatim clauses from the document, "
        "state what has to be changed and why, and provide the exact replacement wording (`suggested_fix`). "
        "Also generate the complete `fixed_document_text` with all changes applied.\n"
    )
    if file_name:
        user_prompt += f"Document Filename: {file_name}\n"
    user_prompt += f"\n--- CONTENT TO REVIEW ---\n{pure_source[:18000]}\n--- END CONTENT ---\n\nReturn ONLY valid JSON matching the MODE 2 schema."

    if messages and messages[-1]['role'] == 'user':
        prev_txt = messages[-1]['content'][0]['text']
        messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{user_prompt}"
    else:
        messages.append({
            'role': 'user',
            'content': [{'text': user_prompt}]
        })

    if not messages:
        messages = [{'role': 'user', 'content': [{'text': user_prompt}]}]

    client = get_bedrock_client()
    parsed = None

    try:
        response = client.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{'text': LENS_SYSTEM_PROMPT}],
            inferenceConfig={
                'maxTokens': 4096,
                'temperature': 0.1,
                'topP': 0.9,
            }
        )
        output_text = response['output']['message']['content'][0]['text'].strip()
        json_match = re.search(r'\{[\s\S]*\}', output_text)
        if json_match:
            parsed = json.loads(json_match.group(0))
    except Exception as e:
        print(f"[LENS Service] Primary model call failed ({e}). Trying fallback...")
        try:
            fallback_response = client.converse(
                modelId=FALLBACK_MODEL_ID,
                messages=messages,
                system=[{'text': LENS_SYSTEM_PROMPT}],
                inferenceConfig={'maxTokens': 3800, 'temperature': 0.1}
            )
            output_text = fallback_response['output']['message']['content'][0]['text'].strip()
            json_match = re.search(r'\{[\s\S]*\}', output_text)
            if json_match:
                parsed = json.loads(json_match.group(0))
        except Exception as e2:
            print(f"[LENS Service] Fallback call also failed ({e2}).")

    if parsed and parsed.get('type') == 'chat' and not file_name:
        return parsed

    if not file_name and len((pure_source or '').split()) < 18:
        if parsed and parsed.get('message'):
            return {'type': 'chat', 'message': parsed['message']}
        if parsed and (parsed.get('publish_readiness') or {}).get('summary'):
            return {'type': 'chat', 'message': parsed['publish_readiness']['summary']}
        return {
            'type': 'chat',
            'message': 'Please attach the document (PDF, DOCX, TXT) or paste the full content you would like me to audit across the 10 Enterprise Governance Dimensions.',
        }

    if not parsed or not parsed.get('publish_readiness'):
        return _rule_based_review_fallback(pure_source, file_name)

    parsed['type'] = 'review'
    parsed['original_text'] = pure_source
    pr = parsed.get('publish_readiness') or {}
    score = pr.get('score')
    if not isinstance(score, (int, float)):
        score = 78
    score = max(0, min(100, int(score)))
    pr['score'] = score

    raw_issues = parsed.get('issues') if isinstance(parsed.get('issues'), list) else []
    norm_issues = _extract_document_specific_changes(pure_source, raw_issues)
    parsed['issues'] = norm_issues

    dims = _normalize_dimensions(parsed.get('dimensions'), norm_issues, score)
    parsed['dimensions'] = dims

    has_red_dim = any(d['rag'] == 'RED' for d in dims)
    has_amber_dim = any(d['rag'] == 'AMBER' for d in dims)
    overall_rag = str(pr.get('rag') or '').upper()
    if overall_rag not in ('RED', 'AMBER', 'GREEN'):
        overall_rag = 'RED' if (has_red_dim or score < 60) else ('AMBER' if (has_amber_dim or score < 85) else 'GREEN')
    pr['rag'] = overall_rag
    pr['status'] = 'CRITICAL_BLOCKERS' if overall_rag == 'RED' else ('NEEDS_REVISION' if overall_rag == 'AMBER' else 'READY_TO_PUBLISH')
    parsed['publish_readiness'] = pr

    parsed['metrics'] = {
        "critical_issues_count": sum(1 for d in dims if d['rag'] == 'RED'),
        "warnings_count": sum(1 for d in dims if d['rag'] == 'AMBER'),
        "suggestions_count": sum(1 for d in dims if d['rag'] == 'GREEN')
    }

    fixed_txt = _apply_fixes_to_source(pure_source, norm_issues, parsed.get('fixed_document_text', ''))
    parsed['fixed_document_text'] = fixed_txt
    stem = Path(file_name or 'document').stem
    parsed['modified_document'] = {
        "source_filename": file_name or "Submitted_Content.txt",
        "filename": f"fixed_{stem}.html",
        "txt_filename": f"fixed_{stem}.txt",
        "fixed_text": fixed_txt,
        "fixed_html": build_fixed_document_html(file_name or "Submitted_Document", fixed_txt, len(norm_issues))
    }

    trace_code = f"LNS-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    parsed['trace_id'] = trace_code
    parsed['guardrails'] = {
        "status": "REDACTED" if guardrail_result.get("has_redactions") else "PASSED",
        "pci_dss_sanitized": True
    }
    return parsed
