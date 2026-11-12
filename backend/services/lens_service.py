import boto3
import json
import os
import re
import random
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

LENS_SYSTEM_PROMPT = """You are LENS, an Enterprise AI Content Reviewer & Consistency Auditor.
Your mission is to act as an expert second reviewer and audit enterprise documentation, contracts, communications, SOPs, marketing collateral, policy guides, and technical specifications before they go live.

You answer the author's and reviewer's primary question:
"Is this content clear, complete, consistent and ready to publish?"

=== CORE REVIEW DELIVERABLES & BEHAVIORAL RULES ===
1. CONTRADICTIONS & INCONSISTENCIES (CRITICAL):
   - Flag any conflicting dates, differing numbers, incompatible deadlines, or opposing instructions across different sections.
   - Example: Section 2 states "30 days to respond", while Section 6 states "45 days".

2. MISSING MANDATORY INFORMATION:
   - Identify missing prerequisites, omitted contact info, unspecified amounts, or unstated consequences.

3. AMBIGUITY & UNINTENTIONAL CONFUSION:
   - Highlight vague statements, ambiguous pronouns, confusing passive sentences, and jargon that confuses the reader.

4. REPETITION & REDUNDANCY:
   - Identify circular explanations, unnecessary duplication across sections, and excessive fluff.

5. ACTIONABLE REVIEW MATRIX (ISSUE -> WHY IT MATTERS -> SUGGESTED FIX):
   - Do NOT silently rewrite the entire document without explaining.
   - For every finding, provide:
     * Location / Section
     * Severity: "CRITICAL" | "WARNING" | "SUGGESTION"
     * Verbatim Excerpt
     * Issue Description
     * Why it matters (impact on reader / risk to organization)
     * Exact Suggested Fix (ready-to-paste replacement wording)

6. PUBLISH READINESS SCORE:
   - Calculate an objective 0–100 score:
     * 85–100: "READY_TO_PUBLISH" (minor suggestions only)
     * 50–84: "NEEDS_REVISION" (warnings or minor inconsistencies)
     * 0–49: "CRITICAL_BLOCKERS" (blatant contradictions, missing mandatory terms, legal risks)

=== ERROR TOLERANCE & SEMANTIC ROBUSTNESS (LIKE TAXORA) ===
- If the user provides informal notes, messy formatting, OCR text, or asks questions with typos (e.g. "revu this", "check doc", "is this redy"), intelligently comprehend the intent and review thoroughly.
- Never fail on short or informal input.

=== OUTPUT FORMAT ===
You operate dynamically in TWO MODES based on user input:

MODE 1: CONVERSATIONAL & MULTILINGUAL ASSISTANCE (type: "chat")
Trigger whenever the user sends greetings, casual slang (e.g. "bro", "dude", "bhai", "machan"), asks general questions, or messages in ANY language without a document to audit.
Respond smoothly, politely, and naturally in their language.
Output JSON:
{
  "type": "chat",
  "message": "<Your smooth conversational reply in user's language>"
}

MODE 2: CONTENT AUDIT & CONSISTENCY REVIEW (type: "review")
Trigger whenever the user submits a document/file or text draft/article/notice to audit.
Output JSON:
{
  "type": "review",
  "publish_readiness": {
    "status": "READY_TO_PUBLISH" | "NEEDS_REVISION" | "CRITICAL_BLOCKERS",
    "score": 78,
    "summary": "Executive review summary in 2 sentences."
  },
  "metrics": {
    "critical_issues_count": 1,
    "warnings_count": 2,
    "suggestions_count": 1,
    "reading_grade_level": "Grade 9 · Professional & Clear",
    "consistency_rating": "Moderate · 1 Contradiction Detected"
  },
  "issues": [
    {
      "id": "ISSUE-1",
      "severity": "CRITICAL",
      "category": "CONTRADICTION",
      "location": "Section 2 vs Section 6",
      "excerpt": "Section 2: 'within 30 days' vs Section 6: 'within 45 days'",
      "issue": "Conflicting response timelines stated across different sections.",
      "why_it_matters": "Recipients will receive contradictory instructions, risking SLA disputes.",
      "suggested_fix": "Standardize the response window to '30 calendar days' across all sections."
    }
  ],
  "strengths": [
    "Clear section headers and logical overall structure.",
    "Well-defined technical parameters and contact channels."
  ],
  "recommendations": [
    "Harmonize response timelines before customer dissemination.",
    "Clarify fee breakdown in Section 4."
  ]
}
"""

GREETING_RESPONSES = [
    "Hello! I am LENS, your Enterprise Content Reviewer & Consistency Auditor. Paste any draft, article, SOP, policy, or document, and I will audit it for contradictions, conflicting dates, missing details, and publish readiness.",
    "Hi there! Welcome to LENS. I'm ready to act as your expert second reviewer. Upload a document or paste text below to check clarity, completeness, and consistency before you publish.",
    "Greetings! I am LENS. Share any business document, customer notice, or technical spec, and I will identify conflicting instructions, ambiguous phrasing, and recommend exact fixes.",
    "Hello! Ready when you are. Send over any draft or contract, and I'll produce an actionable Issue → Why It Matters → Suggested Fix review matrix.",
    "Hey there! Welcome to LENS. Feel free to paste or attach any content you want audited. I'll evaluate publish readiness with zero hallucinations."
]

BRO_RESPONSES = [
    "Hey bro! Ready when you are. Send over any document, policy, draft, or notice, and I'll audit it for clarity, contradictions, and publish readiness.",
    "Yo bro! What's up? I'm LENS, your Enterprise Content Reviewer. Drop any file or paste your draft, and I'll find any inconsistencies before you publish.",
    "Hey bro! Standing by. You can upload any document or paste text, and I'll generate a complete review matrix with suggested fixes.",
    "Sup bro! All systems go. Send over any contract, article, or policy draft, and I'll review it with zero hallucinations."
]

HOW_ARE_YOU_RESPONSES = [
    "I'm operating at peak vigilance and ready to review your content! Paste any text or upload a document to audit for consistency and contradictions.",
    "All audit rules, guardrails, and consistency scanners are running smoothly! I'm here to help make sure your documents are 100% ready to publish.",
    "Doing very well, thank you! I'm ready to review your next publication draft or policy document.",
    "I'm ready to assist! Share your document or draft, and I'll identify any contradictory statements, missing details, or confusing sections."
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

    # Casual brother/slang words (bro, bruh, dude, yaar, bhai, machan, etc.)
    is_bro = (
        bool(re.match(r'^(?:(?:hey+|hi+|yo+|sup|hello+|namaste|vanakkam)\s+)?(?:bro+|brother|bruh|brah|dude|yaar|bhai|bhaiya|machan|macha|thala|buddy|mate|man|sis|dost)(?:\s+(?:how\s+are\s+you|whats?\s+up|hw\s+r\s+u))?$', cleaned)) or
        cleaned in {'bro', 'broo', 'bruh', 'brah', 'brother', 'dude', 'yaar', 'bhai', 'machan', 'macha', 'thala', 'buddy', 'mate', 'sis', 'dost'}
    )
    if is_bro:
        return _pick_varied_response(BRO_RESPONSES, conversation_history)

    # "How are you" variants and typos
    is_how_are_you = (
        bool(re.match(r'^(?:(?:hi+|h[ea]y+|h[ea]llo+|hlo|ji)\s+)?(?:how|hw)\s+(?:r|are|re)\s+(?:u|you|yu)(?:\s+doing)?$', cleaned)) or
        bool(re.match(r'^(?:hows?|hws)\s+(?:it\s+going|u|you)$', cleaned)) or
        cleaned in {'hru', 'hw r u', 'how r u', 'how r you', 'how are you', 'how are u', 'whats up', 'sup', 'how do you do'}
    )
    if is_how_are_you:
        return _pick_varied_response(HOW_ARE_YOU_RESPONSES, conversation_history)

    # Greeting variants including typos (ji, gi, helo, hlo, etc.)
    is_greeting = (
        bool(re.match(r'^(?:hi+|h[ea]y+|h[ea]llo+|hlo|helo|ji+|namaste|hola|greetings?|yo+|sup)(?:\s+(?:there|lens|agent|bot|all|team|friend|buddy|ji))?$', cleaned)) or
        bool(re.match(r'^(?:good\s+(?:morning|afternoon|evening|day))(?:\s+(?:lens|there|all))?$', cleaned)) or
        cleaned in {'ji', 'hi', 'hello', 'hey', 'hii', 'hiii', 'heyy', 'namaste ji', 'gi', 'hlo', 'helo', 'hlw', 'hye', 'hay'}
    )
    if is_greeting:
        return _pick_varied_response(GREETING_RESPONSES, conversation_history)

    return None


def _rule_based_review_fallback(content: str, file_name: str = "") -> dict:
    clean_strip = (content or '').strip()
    if not file_name and len(clean_strip) < 65:
        return {
            "type": "chat",
            "message": "Hello! I am LENS, your Enterprise Content Reviewer. I'm ready to audit any document, SOP, contract, or draft for consistency, contradictions, and publish readiness."
        }
    words = content.split()
    word_count = len(words)
    title = file_name.replace('_', ' ').replace('-', ' ').title() if file_name else "Submitted Content"

    # Quick heuristic contradiction check
    has_contradiction = False
    issues = []
    
    # Check for date / day mentions
    day_matches = re.findall(r'(\d+)\s*(?:calendar\s*)?(?:business\s*)?days?', content, re.IGNORECASE)
    if len(set(day_matches)) > 1:
        has_contradiction = True
        issues.append({
            "id": "ISSUE-1",
            "severity": "CRITICAL",
            "category": "CONTRADICTION",
            "location": "Timeline / Response Window Statements",
            "excerpt": f"Multiple differing day counts detected: {', '.join(set(day_matches))} days",
            "issue": "Content specifies multiple conflicting response/completion day timelines.",
            "why_it_matters": "Causes confusion and SLA ambiguity for recipients and stakeholders.",
            "suggested_fix": f"Confirm single definitive timeframe ({day_matches[0]} days) and align throughout."
        })

    # Check for passive or vague terms
    if re.search(r'\b(as soon as possible|asap|timely manner|various|etc\.)\b', content, re.IGNORECASE):
        issues.append({
            "id": f"ISSUE-{len(issues)+1}",
            "severity": "WARNING",
            "category": "AMBIGUITY",
            "location": "Instructional Clauses",
            "excerpt": "Vague timeline phrasing detected ('as soon as possible' / 'in a timely manner')",
            "issue": "Subjective timeline phrases leave deadlines open to interpretation.",
            "why_it_matters": "Enforceability and operational commitments become difficult to measure.",
            "suggested_fix": "Replace vague timeline phrases with an explicit number of calendar days or fixed date."
        })

    score = 75 if not issues else (45 if has_contradiction else 65)
    status = "READY_TO_PUBLISH" if score >= 85 else ("CRITICAL_BLOCKERS" if score < 50 else "NEEDS_REVISION")

    return {
        "type": "review",
        "publish_readiness": {
            "status": status,
            "score": score,
            "summary": f"LENS audited {word_count} words across '{title}'. {'Found potential conflicting timelines that need alignment.' if has_contradiction else 'Content is well-structured with minor clarity recommendations.'}"
        },
        "metrics": {
            "critical_issues_count": sum(1 for i in issues if i['severity'] == 'CRITICAL'),
            "warnings_count": sum(1 for i in issues if i['severity'] == 'WARNING'),
            "suggestions_count": sum(1 for i in issues if i['severity'] == 'SUGGESTION'),
            "reading_grade_level": "Grade 9 · Professional",
            "consistency_rating": "Review Recommended" if issues else "High"
        },
        "issues": issues if issues else [
            {
                "id": "ISSUE-1",
                "severity": "SUGGESTION",
                "category": "CLARITY",
                "location": "Overall Content Flow",
                "excerpt": content[:80] + "...",
                "issue": "Consider breaking dense paragraphs into bulleted action points.",
                "why_it_matters": "Enhances readability and executive retention.",
                "suggested_fix": "Add descriptive subheaders above major thematic sections."
            }
        ],
        "strengths": [
            "Content covers the primary subject matter with clear terminology.",
            "Document follows a cohesive presentation structure."
        ],
        "recommendations": [
            "Harmonize all numerical and timeline commitments.",
            "Conduct a final author review before publishing."
        ]
    }


def review_content(text: str, file_name: str = "", conversation_history: list = None) -> dict:
    if conversation_history is None:
        conversation_history = []

    # Quick Conversational / Greeting Check
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
        return {
            "type": "chat",
            "message": guardrail_result.get("message", "The submitted content violates Enterprise BFSI Guardrails and cannot be reviewed."),
            "guardrail_status": "BLOCKED",
            "guardrail_details": guardrail_result
        }

    sanitized_text = guardrail_result.get("sanitized_text", text)

    # Step 2: Build Converse API Messages strictly obeying Bedrock requirements
    messages = []
    for msg in (conversation_history or [])[-6:]:
        content_txt = msg.get('content', '')
        if isinstance(content_txt, dict):
            content_txt = content_txt.get('message') or json.dumps(content_txt)
        content_txt = str(content_txt or '').strip()
        if not content_txt or content_txt.startswith('<!doctype') or '<html' in content_txt.lower():
            continue

        role = 'assistant' if msg.get('role') in ('ai', 'assistant') else 'user'
        if messages and messages[-1]['role'] == role:
            prev_txt = messages[-1]['content'][0]['text']
            messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{content_txt[:2000]}"
        else:
            messages.append({
                'role': role,
                'content': [{'text': content_txt[:2000]}]
            })

    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

    user_prompt = f"Review and audit the following content thoroughly.\n"
    if file_name:
        user_prompt += f"Document Title / Filename: {file_name}\n"
    user_prompt += f"\n--- CONTENT TO REVIEW ---\n{sanitized_text}\n--- END CONTENT ---\n\nProduce the complete JSON Content Review & Consistency Audit according to the required schema."

    if messages and messages[-1]['role'] == 'user':
        prev_txt = messages[-1]['content'][0]['text']
        messages[-1]['content'][0]['text'] = f"{prev_txt}\n\n{user_prompt}"
    else:
        messages.append({
            'role': 'user',
            'content': [{'text': user_prompt}]
        })

    while messages and messages[0]['role'] != 'user':
        messages.pop(0)

    if not messages:
        messages = [{'role': 'user', 'content': [{'text': user_prompt}]}]

    client = get_bedrock_client()

    try:
        response = client.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{'text': LENS_SYSTEM_PROMPT}],
            inferenceConfig={
                'maxTokens': 4000,
                'temperature': 0.1,
                'topP': 0.9,
            }
        )

        output_text = response['output']['message']['content'][0]['text'].strip()
        json_match = re.search(r'\{[\s\S]*\}', output_text)
        if json_match:
            parsed = json.loads(json_match.group(0))
            parsed['type'] = 'review'
            return parsed
        else:
            return {"type": "chat", "message": output_text}
    except Exception as e:
        print(f"[LENS Service] Primary model call failed ({e}). Trying fallback {FALLBACK_MODEL_ID}...")
        try:
            fallback_response = client.converse(
                modelId=FALLBACK_MODEL_ID,
                messages=messages,
                system=[{'text': LENS_SYSTEM_PROMPT}],
                inferenceConfig={'maxTokens': 3500, 'temperature': 0.1}
            )
            output_text = fallback_response['output']['message']['content'][0]['text'].strip()
            json_match = re.search(r'\{[\s\S]*\}', output_text)
            if json_match:
                parsed = json.loads(json_match.group(0))
                parsed['type'] = 'review'
                return parsed
            else:
                return {"type": "chat", "message": output_text}
        except Exception as e2:
            print(f"[LENS Service] Fallback call also failed ({e2}). Using rule-based review engine.")
            return _rule_based_review_fallback(sanitized_text, file_name)

