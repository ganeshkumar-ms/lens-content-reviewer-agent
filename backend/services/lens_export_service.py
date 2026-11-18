"""
Zero-dependency formatted PDF & DOCX exporter for LENS remediated documents.
Converts markdown-style titles (#, ##, **Heading**), inline **bold**, and bullets
into real formatted titles, bold headings, bold inline runs, and clean paragraphs.
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape


def _strip_md_inline(text: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', text or '')
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'`(.+?)`', r'\1', s)
    return s


def parse_formatted_blocks(title: str, fixed_text: str) -> list[dict]:
    """Parses raw/markdown text into structured blocks: title, h1, h2, bullet, para."""
    blocks: list[dict] = []
    clean_title = _strip_md_inline(re.sub(r'^#+\s*', '', (title or 'Remediated Document').strip())).strip()
    if clean_title:
        blocks.append({'kind': 'title', 'runs': [{'text': clean_title, 'bold': True}]})

    lines = (fixed_text or '').replace('\r\n', '\n').split('\n')
    for idx, raw_ln in enumerate(lines):
        st = raw_ln.strip()
        if not st:
            continue

        # Markdown headings (#, ##, ###)
        m_h = re.match(r'^(#{1,4})\s+(.+)$', st)
        if m_h:
            lvl = len(m_h.group(1))
            htxt = _strip_md_inline(m_h.group(2)).strip()
            if htxt and (idx > 0 or htxt.lower() != clean_title.lower()):
                blocks.append({'kind': 'h1' if lvl <= 2 else 'h2', 'runs': [{'text': htxt, 'bold': True}]})
            continue

        # Standalone bold heading line like **1. Purpose** or **Executive Summary**
        m_bhead = re.match(r'^\*\*([^*]{2,110})\*\*[:\s]*$', st)
        if m_bhead:
            htxt = m_bhead.group(1).strip()
            if htxt and (idx > 0 or htxt.lower() != clean_title.lower()):
                blocks.append({'kind': 'h2', 'runs': [{'text': htxt, 'bold': True}]})
            continue

        # Numbered / uppercase section heading
        if (len(st) < 85 and st.isupper() and any(c.isalpha() for c in st)) or re.match(
            r'^(?:\d+\.|SECTION|ARTICLE|PART)\s+[A-Z0-9]', st
        ):
            htxt = _strip_md_inline(st)
            if len(htxt) <= 100:
                blocks.append({'kind': 'h2', 'runs': [{'text': htxt, 'bold': True}]})
                continue

        # Bullet item
        m_bul = re.match(r'^(?:[•\-\*▪▸])\s+(.+)$', st)
        if m_bul:
            blocks.append({'kind': 'bullet', 'runs': _parse_inline_runs(m_bul.group(1).strip())})
            continue

        # Regular paragraph with inline bold runs
        blocks.append({'kind': 'para', 'runs': _parse_inline_runs(st)})

    return blocks


def _parse_inline_runs(text: str) -> list[dict]:
    runs: list[dict] = []
    parts = re.split(r'(\*\*[^*]+\*\*)', text or '')
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            runs.append({'text': part[2:-2], 'bold': True})
        else:
            cleaned = part.replace('`', '')
            if cleaned:
                runs.append({'text': cleaned, 'bold': False})
    return runs or [{'text': '', 'bold': False}]


def _pdf_escape(s: str) -> str:
    safe = (s or '').encode('latin-1', 'replace').decode('latin-1')
    return safe.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_formatted_pdf_bytes(title: str, fixed_text: str) -> bytes:
    """Builds a clean, multi-page formatted PDF (%PDF-1.4) with real titles, bold headings, and bullets."""
    blocks = parse_formatted_blocks(title, fixed_text)

    page_w = 595.28
    page_h = 841.89
    margin_x = 52.0
    max_w = page_w - 2 * margin_x
    top_y = page_h - 56.0
    bottom_y = 52.0

    pages: list[list[str]] = [[]]
    y = top_y

    def ensure_space(needed: float):
        nonlocal y
        if y - needed < bottom_y:
            pages.append([])
            y = top_y

    def emit_line(x: float, font: str, size: float, text: str, color: tuple[float, float, float] = (0.08, 0.11, 0.16)):
        r, g, b = color
        pages[-1].append(
            f"BT /{font} {size:.1f} Tf {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(text)}) Tj ET"
        )

    def wrap_runs(runs: list[dict], font_size: float, avail_w: float) -> list[list[dict]]:
        # Approximate average char width for Helvetica (~0.51 * font_size)
        max_chars = max(22, int(avail_w / (font_size * 0.50)))
        lines_out: list[list[dict]] = [[]]
        curr_len = 0
        for run in runs:
            words = re.split(r'(\s+)', run['text'])
            for w in words:
                if not w:
                    continue
                if curr_len + len(w) > max_chars and curr_len > 0 and not w.isspace():
                    lines_out.append([])
                    curr_len = 0
                if curr_len == 0 and w.isspace():
                    continue
                lines_out[-1].append({'text': w, 'bold': run['bold']})
                curr_len += len(w)
        return [ln for ln in lines_out if ln]

    for blk in blocks:
        kind = blk['kind']
        runs = blk['runs']
        if kind == 'title':
            wrapped = wrap_runs(runs, 16.0, max_w)
            ensure_space(len(wrapped) * 21.0 + 14.0)
            for ln in wrapped:
                txt = ''.join(r['text'] for r in ln)
                emit_line(margin_x, 'F2', 16.0, txt, (0.086, 0.227, 0.373))
                y -= 21.0
            # Accent divider line under title
            pages[-1].append(f"0.086 0.227 0.373 RG 1.2 w {margin_x:.2f} {y + 6:.2f} m {page_w - margin_x:.2f} {y + 6:.2f} l S")
            y -= 10.0
        elif kind in ('h1', 'h2'):
            fsize = 13.0 if kind == 'h1' else 11.5
            lead = 17.0 if kind == 'h1' else 15.5
            wrapped = wrap_runs(runs, fsize, max_w)
            ensure_space(len(wrapped) * lead + 8.0)
            y -= 6.0
            for ln in wrapped:
                txt = ''.join(r['text'] for r in ln)
                emit_line(margin_x, 'F2', fsize, txt, (0.086, 0.227, 0.373))
                y -= lead
            y -= 2.0
        elif kind == 'bullet':
            wrapped = wrap_runs(runs, 10.5, max_w - 16.0)
            ensure_space(len(wrapped) * 14.5 + 4.0)
            for li, ln in enumerate(wrapped):
                if li == 0:
                    emit_line(margin_x + 4.0, 'F2', 10.5, '-', (0.086, 0.227, 0.373))
                cx = margin_x + 16.0
                for seg in ln:
                    font = 'F2' if seg['bold'] else 'F1'
                    emit_line(cx, font, 10.5, seg['text'])
                    cx += len(seg['text']) * (10.5 * 0.49)
                y -= 14.5
            y -= 2.0
        else:
            wrapped = wrap_runs(runs, 10.5, max_w)
            ensure_space(len(wrapped) * 14.5 + 5.0)
            for ln in wrapped:
                cx = margin_x
                for seg in ln:
                    font = 'F2' if seg['bold'] else 'F1'
                    emit_line(cx, font, 10.5, seg['text'])
                    cx += len(seg['text']) * (10.5 * 0.49)
                y -= 14.5
            y -= 5.0

    # Assemble PDF objects
    objs: list[bytes] = []
    # 1: Catalog, 2: Pages, 3: F1 Helvetica, 4: F2 Helvetica-Bold
    font1_id = 3
    font2_id = 4
    page_ids = []
    content_ids = []
    next_id = 5
    for _ in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2

    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = ' '.join(f"{pid} 0 R" for pid in page_ids)
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode('latin-1'))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    for pid, cid, cmds in zip(page_ids, content_ids, pages):
        stream_data = '\n'.join(cmds).encode('latin-1', 'replace')
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.2f} {page_h:.2f}] "
            f"/Resources << /Font << /F1 {font1_id} 0 R /F2 {font2_id} 0 R >> >> "
            f"/Contents {cid} 0 R >>".encode('latin-1')
        )
        objs.append(
            f"<< /Length {len(stream_data)} >>\nstream\n".encode('latin-1') + stream_data + b"\nendstream"
        )

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{idx} 0 obj\n".encode('latin-1'))
        out.write(body)
        out.write(b"\nendobj\n")

    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode('latin-1'))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode('latin-1'))
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode('latin-1'))
    return out.getvalue()


def build_formatted_docx_bytes(title: str, fixed_text: str) -> bytes:
    """Builds a valid .docx OOXML document with formatted title, bold headings, bold runs, and bullets."""
    blocks = parse_formatted_blocks(title, fixed_text)
    para_xmls = []

    for blk in blocks:
        kind = blk['kind']
        runs_xml = []
        for r in blk['runs']:
            txt = xml_escape(r['text'])
            if kind == 'title':
                runs_xml.append(f'<w:r><w:rPr><w:b/><w:color w:val="163A5F"/><w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            elif kind in ('h1', 'h2'):
                sz = '26' if kind == 'h1' else '23'
                runs_xml.append(f'<w:r><w:rPr><w:b/><w:color w:val="163A5F"/><w:sz w:val="{sz}"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            elif r['bold']:
                runs_xml.append(f'<w:r><w:rPr><w:b/><w:sz w:val="21"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            else:
                runs_xml.append(f'<w:r><w:rPr><w:sz w:val="21"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')

        if kind == 'bullet':
            bullet_prefix = '<w:r><w:rPr><w:b/><w:sz w:val="21"/></w:rPr><w:t xml:space="preserve">•  </w:t></w:r>'
            para_xmls.append(
                f'<w:p><w:pPr><w:ind w:left="360"/><w:spacing w:after="80"/></w:pPr>{bullet_prefix}{"".join(runs_xml)}</w:p>'
            )
        elif kind in ('title', 'h1', 'h2'):
            para_xmls.append(
                f'<w:p><w:pPr><w:spacing w:before="180" w:after="100"/></w:pPr>{"".join(runs_xml)}</w:p>'
            )
        else:
            para_xmls.append(
                f'<w:p><w:pPr><w:spacing w:after="120"/></w:pPr>{"".join(runs_xml)}</w:p>'
            )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(para_xmls)}<w:sectPr/></w:body></w:document>'
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', doc_xml)
    return buf.getvalue()
