import os
import sys
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#4A5568"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "LENS · Enterprise Content Reviewer & Consistency Auditor")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        page_str = f"Page {self._pageNumber} of {total_pages}"
        self.drawRightString(558, 32, page_str)
        self.drawString(54, 32, "Confidential & Enterprise Learning Material · Antigravity AI Platform")
        self.restoreState()


def build_pdf(filename="LENS_BEGINNER_STUDY_GUIDE.pdf"):
    out_path = Path(__file__).resolve().parent / filename
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    PRIMARY = colors.HexColor("#08d6a2")   # Emerald Mint
    SECONDARY = colors.HexColor("#0b3d32") # Deep Forest Emerald
    ACCENT = colors.HexColor("#065f46")    # Pine
    DARK_BG = colors.HexColor("#02110d")
    LIGHT_BG = colors.HexColor("#F0FDF4")
    CARD_BG = colors.HexColor("#F8FAFC")
    TEXT_MAIN = colors.HexColor("#0F172A")
    TEXT_MUTED = colors.HexColor("#475569")
    SUCCESS = colors.HexColor("#059669")
    DANGER = colors.HexColor("#DC2626")
    WARNING = colors.HexColor("#D97706")
    BORDER = colors.HexColor("#A7F3D0")

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=SECONDARY,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=16,
        textColor=ACCENT,
        spaceAfter=14,
    )
    h1_style = ParagraphStyle(
        "H1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=SECONDARY,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=ACCENT,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=TEXT_MAIN,
        spaceAfter=6,
    )
    body_muted = ParagraphStyle(
        "BodyMuted",
        parent=body_style,
        textColor=TEXT_MUTED,
        fontSize=8.5,
        leading=12,
    )
    code_style = ParagraphStyle(
        "CodeBlock",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#064E3B"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3,
    )

    story = []

    # COVER HEADER
    story.append(Paragraph("LENS · CONTENT REVIEWER & CONSISTENCY AUDITOR", title_style))
    story.append(Paragraph("Enterprise BFSI Study Guide & System Architecture Specification · Zero-Bug Blueprint", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=0, spaceAfter=12))

    # SECTION 1: WHAT IS LENS?
    story.append(Paragraph("1. Executive Overview & Agent Identity", h1_style))
    story.append(Paragraph(
        "<b>LENS</b> is the 4th agent in the 10-agent Content Intelligence Platform "
        "(<i>CLARIA · LENS · INDEX · BRIDGE · GRID · ADAPTA · GLANCE · SORTIA · ECHO · ALLY</i>). "
        "While CLARIA redesigns customer communications and INDEX tags enterprise knowledge graphs, "
        "<b>LENS serves as the final gatekeeper and consistency auditor</b> before any content goes live.",
        body_style,
    ))
    story.append(Paragraph(
        "<b>Primary Question Answered:</b> <i>\"Is this content clear, complete, consistent and ready to publish?\"</i>",
        body_style,
    ))

    # Overview Table
    overview_data = [
        [Paragraph("<b>Attribute</b>", body_style), Paragraph("<b>Specification</b>", body_style)],
        [Paragraph("<b>Agent Identity</b>", body_style), Paragraph("LENS · Enterprise Content Reviewer & Consistency Auditor", body_style)],
        [Paragraph("<b>Core Focus</b>", body_style), Paragraph("Contradiction detection, conflicting dates/numbers, ambiguity, publish readiness", body_style)],
        [Paragraph("<b>AI Model</b>", body_style), Paragraph("Amazon Bedrock Nova Pro (us.amazon.nova-pro-v1:0) with Claude 3 Haiku fallback", body_style)],
        [Paragraph("<b>Color Palette</b>", body_style), Paragraph("Emerald Mint (#08d6a2) · Forest Emerald (#0b3d32) · Dark Panel (#06231b)", body_style)],
        [Paragraph("<b>Review Output</b>", body_style), Paragraph("0–100 Readiness Score · Actionable Review Matrix (Issue → Why Matters → Fix)", body_style)],
    ]
    t_overview = Table(overview_data, colWidths=[1.8 * inch, 5.0 * inch])
    t_overview.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), SECONDARY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    story.append(t_overview)
    story.append(Spacer(1, 12))

    # SECTION 2: ARCHITECTURE & AUDIT ENGINE
    story.append(Paragraph("2. System Architecture & Dual-Engine Fallback", h1_style))
    story.append(Paragraph(
        "LENS follows a resilient serverless architecture built on AWS Lambda, Amazon Bedrock, "
        "Amazon S3, and CloudFront. To guarantee 100% uptime even during network or credential interruptions, "
        "LENS implements a three-tier execution hierarchy:",
        body_style,
    ))
    story.append(Paragraph("• <b>Tier 1 (Instant Conversational Matcher):</b> Intercepts greetings, typos (e.g. 'ji', 'gi', 'hlo'), and queries like 'how are you' with zero-latency contextual replies, preventing unnecessary LLM token spend.", bullet_style))
    story.append(Paragraph("• <b>Tier 2 (Bedrock Nova Pro Converse):</b> Analyzes cross-section semantics, identifies subtle timeline discrepancies, calculates readiness scores, and generates structured JSON audits.", bullet_style))
    story.append(Paragraph("• <b>Tier 3 (Heuristic Deterministic Fallback):</b> If Bedrock is unreachable, a local regex-powered contradiction engine parses numerical and date timelines, identifying day-count disparities without failing.", bullet_style))
    story.append(Spacer(1, 8))

    # SECTION 3: THE ACTIONABLE REVIEW MATRIX
    story.append(Paragraph("3. The Actionable Review Matrix Framework", h1_style))
    story.append(Paragraph(
        "A critical flaw in standard AI tools is the silent rewrite: LLMs often rewrite text without "
        "telling the author why. LENS adopts the enterprise standard <b>Issue → Why It Matters → Suggested Fix</b> matrix:",
        body_style,
    ))

    matrix_data = [
        [Paragraph("<b>Component</b>", body_style), Paragraph("<b>Enterprise Purpose</b>", body_style), Paragraph("<b>Example</b>", body_style)],
        [
            Paragraph("<b>Location</b>", body_style),
            Paragraph("Pinpoints exact sections where inconsistencies or flaws occur.", body_style),
            Paragraph("Section 2 vs Section 6", body_muted),
        ],
        [
            Paragraph("<b>Severity</b>", body_style),
            Paragraph("CRITICAL (blocker), WARNING (caution), SUGGESTION (polish).", body_style),
            Paragraph("<font color='#DC2626'><b>CRITICAL</b></font>", body_style),
        ],
        [
            Paragraph("<b>Verbatim Excerpt</b>", body_style),
            Paragraph("Quotes exact wording from the document to establish provenance.", body_style),
            Paragraph("\"within 30 days\" vs \"within 45 days\"", body_muted),
        ],
        [
            Paragraph("<b>Why It Matters</b>", body_style),
            Paragraph("Articulates operational risk, legal exposure, or customer confusion.", body_style),
            Paragraph("Recipients receive contradictory SLAs, risking disputes.", body_muted),
        ],
        [
            Paragraph("<b>Suggested Fix</b>", body_style),
            Paragraph("Provides copy-paste replacement text ready for immediate insertion.", body_style),
            Paragraph("\"within 30 calendar days of invoice date\"", body_muted),
        ],
    ]
    t_matrix = Table(matrix_data, colWidths=[1.3 * inch, 2.7 * inch, 2.8 * inch])
    t_matrix.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_matrix)
    story.append(Spacer(1, 12))

    story.append(PageBreak())

    # SECTION 4: LESSONS LEARNED & ZERO-BUG MANDATES
    story.append(Paragraph("4. Zero-Bug Implementation Standards (Lessons from Taxora, Claria & Index)", h1_style))
    story.append(Paragraph(
        "During the development of previous agents, specific failure modes were documented. "
        "LENS integrates all preventive safeguards into its architecture:",
        body_style,
    ))

    bugs_data = [
        [Paragraph("<b>Previous Bug Encountered</b>", body_style), Paragraph("<b>Root Cause</b>", body_style), Paragraph("<b>LENS Built-in Safeguard</b>", body_style)],
        [
            Paragraph("<b>Raw HTML in Chat Bubble</b>", body_style),
            Paragraph("Missing <code>VITE_API_BASE</code> in production caused requests to hit CloudFront S3 fallback <code>index.html</code>.", body_style),
            Paragraph("<code>deploy_aws.py</code> automatically injects API Gateway URL into <code>.env.production</code> and triggers automated rebuild prior to S3 upload.", body_style),
        ],
        [
            Paragraph("<b>Bedrock ValidationException on 'ji'</b>", body_style),
            Paragraph("User sent typo greeting 'ji'; Converse API requires strict role alternation starting with 'user'.", body_style),
            Paragraph("Fuzzy typo regex intercepts greetings immediately; Converse messages enforce strict role alternation starting with 'user'.", body_style),
        ],
        [
            Paragraph("<b>Duplicate 'Open Document' Badges</b>", body_style),
            Paragraph("Both user bubble and AI answer card rendered document chips.", body_style),
            Paragraph("Single badge in user bubble only; AI cards display clean review metrics and copyable fix matrices.", body_style),
        ],
        [
            Paragraph("<b>Unscrollable Chat Page</b>", body_style),
            Paragraph("Nested CSS with <code>overflow: hidden</code> on <code>.messages</code> and non-standard font weights (850, 650).", body_style),
            Paragraph("Pure standard multiples of 100 (400, 600, 700, 800) with <code>overflow-y: auto</code> and auto-scroll to last AI card.", body_style),
        ],
        [
            Paragraph("<b>Empty Conversations Saved</b>", body_style),
            Paragraph("Opening new chat immediately persisted an empty session into localStorage.", body_style),
            Paragraph("Strict filter: sessions are persisted only when <code>messages.length > 0</code>.", body_style),
        ],
        [
            Paragraph("<b>Viewer 'No preview available'</b>", body_style),
            Paragraph("Document viewer failed when <code>view_url</code> was empty.", body_style),
            Paragraph("Lambda streams PDF inline and converts Office/Text formats to HTML, with raw text fallback.", body_style),
        ],
    ]
    t_bugs = Table(bugs_data, colWidths=[2.0 * inch, 2.3 * inch, 2.5 * inch])
    t_bugs.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_bugs)
    story.append(Spacer(1, 12))

    # SECTION 5: VERIFICATION TEST SUITE
    story.append(Paragraph("5. Verification Test Suite & Validation Commands", h1_style))
    story.append(Paragraph(
        "To verify that LENS is 100% bug-free across local and production environments, "
        "execute the following commands:",
        body_style,
    ))

    code_text = (
        "# 1. Test conversational greetings and fallback engine:\n"
        ".\\taxora\\backend\\venv\\Scripts\\python.exe lens\\test_backend.py\n\n"
        "# 2. Test local frontend development server:\n"
        "cd lens\\frontend && npm run build\n\n"
        "# 3. Run automated AWS deployment (Lambda, S3, CloudFront):\n"
        ".\\taxora\\backend\\venv\\Scripts\\python.exe lens\\deploy_aws.py\n"
    )
    story.append(Paragraph(code_text.replace("\n", "<br/>").replace(" ", "&nbsp;"), code_style))
    story.append(Spacer(1, 14))

    # SECTION 6: SUMMARY & CONCLUSION
    story.append(Paragraph("6. Conclusion & Roadmap", h1_style))
    story.append(Paragraph(
        "LENS establishes an uncompromising quality standard for enterprise document publishing. "
        "By enforcing consistency, eliminating contradictions, and offering copy-ready fixes, "
        "LENS safeguards organizations against operational confusion and legal exposure. "
        "With 4 out of 10 agents completed (TAXORA, CLARIA, INDEX, LENS), the Content Intelligence Platform "
        "continues towards comprehensive enterprise automation.",
        body_style,
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"LENS Beginner Study Guide PDF generated successfully: {out_path}")
    return str(out_path)


if __name__ == "__main__":
    build_pdf()

