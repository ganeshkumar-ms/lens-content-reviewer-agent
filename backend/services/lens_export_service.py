"""
Zero-dependency formatted PDF & DOCX exporter for LENS remediated documents.
Matches the uploaded input document's font, colors, page dimensions, font sizes,
and table styling while cleanly stripping stray markdown tokens (e.g. **title*).
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape


def _strip_md_inline(text: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', text or '')
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'`(.+?)`', r'\1', s)
    # Strip any unbalanced/stray markdown markers like **title* or *title
    s = re.sub(r'\*{1,3}', '', s)
    s = s.replace('__', '').replace('`', '')
    return s


def _strip_analysis_wrapper(text: str) -> str:
    s = (text or '').replace('\r\n', '\n')
    s = re.sub(r'\[FULL-DOCUMENT ANALYSIS METADATA\][\s\S]*?(?:Detailed Readable Text[^\n]*\n+|={6,}\s*)', '', s, flags=re.IGNORECASE)
    return s.strip()


def _hex_to_rgb(hx: str | None, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    if not hx or not isinstance(hx, str) or not hx.startswith('#') or len(hx) != 7:
        return fallback
    try:
        return (int(hx[1:3], 16) / 255.0, int(hx[3:5], 16) / 255.0, int(hx[5:7], 16) / 255.0)
    except Exception:
        return fallback


def _clean_hex(hx: str | None, fallback: str) -> str:
    if hx and isinstance(hx, str) and hx.startswith('#') and len(hx) == 7:
        return hx[1:].upper()
    return fallback


def _parse_inline_runs(text: str) -> list[dict]:
    runs: list[dict] = []
    parts = re.split(r'(\*\*[^*]+\*\*)', text or '')
    for part in parts:
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            cleaned = re.sub(r'\*{1,3}', '', part[2:-2]).replace('`', '')
            if cleaned:
                runs.append({'text': cleaned, 'bold': True})
        else:
            cleaned = re.sub(r'\*{1,3}', '', part).replace('`', '').replace('__', '')
            if cleaned:
                runs.append({'text': cleaned, 'bold': False})
    return runs or [{'text': '', 'bold': False}]


def _is_table_sep(line: str) -> bool:
    s = line.strip().strip('|').strip()
    return bool(s) and bool(re.match(r'^[\s|:\-]+$', s)) and '-' in s


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [_strip_md_inline(c.strip()) for c in s.split('|')]


def parse_formatted_blocks(title: str, fixed_text: str) -> list[dict]:
    """Parses raw/markdown text into structured blocks: title, h1, h2, bullet, table, divider, para."""
    blocks: list[dict] = []
    clean_title = _strip_md_inline(re.sub(r'^#+\s*', '', (title or '').strip())).strip()
    if clean_title:
        blocks.append({'kind': 'title', 'runs': [{'text': clean_title, 'bold': True}]})

    lines = _strip_analysis_wrapper(fixed_text).split('\n')
    i = 0
    while i < len(lines):
        st = lines[i].strip()
        if not st:
            i += 1
            continue

        # Strip any literal Page 1 / Page 2 / [Page X of Y] markers; treat standalone --- as a page break / divider
        if re.match(r'^[\-\[\(\s]*Page\s+\d+(?:\s*(?:of|/)\s*\d+)?[\-\]\)\s]*$', st, re.IGNORECASE):
            i += 1
            continue
        if re.match(r'^-{3,}$', st):
            blocks.append({'kind': 'divider', 'runs': []})
            i += 1
            continue

        # Promote the document's own first line to title if no explicit title was prepended
        if not blocks and '|' not in st and len(st) <= 120:
            htxt = _strip_md_inline(re.sub(r'^#+\s*', '', st)).strip()
            if htxt:
                blocks.append({'kind': 'title', 'runs': [{'text': htxt, 'bold': True}]})
                i += 1
                continue

        # Markdown / pipe-delimited table block (2+ consecutive pipe lines)
        if '|' in st and (i + 1 < len(lines) and '|' in lines[i + 1]):
            tbl_rows: list[list[str]] = []
            while i < len(lines) and '|' in lines[i]:
                row_line = lines[i].strip()
                if not _is_table_sep(row_line):
                    cells = _split_table_row(row_line)
                    if any(cells):
                        tbl_rows.append(cells)
                i += 1
            if tbl_rows:
                blocks.append({'kind': 'table', 'rows': tbl_rows, 'runs': []})
            continue

        # Markdown headings (#, ##, ###)
        m_h = re.match(r'^(#{1,4})\s+(.+)$', st)
        if m_h:
            lvl = len(m_h.group(1))
            htxt = _strip_md_inline(m_h.group(2)).strip()
            if htxt and (i > 0 or htxt.lower() != clean_title.lower()):
                blocks.append({'kind': 'h1' if lvl <= 2 else 'h2', 'runs': [{'text': htxt, 'bold': True}]})
            i += 1
            continue

        # Standalone bold heading line like **1. Purpose** or **title*
        m_bhead = re.match(r'^\*\*([^*]{2,110})\*+[:\s]*$', st)
        if m_bhead:
            htxt = _strip_md_inline(m_bhead.group(1)).strip()
            if htxt and (i > 0 or htxt.lower() != clean_title.lower()):
                blocks.append({'kind': 'h2', 'runs': [{'text': htxt, 'bold': True}]})
            i += 1
            continue

        # Numbered / uppercase section heading
        if (len(st) < 85 and st.isupper() and any(c.isalpha() for c in st)) or re.match(
            r'^(?:\d+\.|SECTION|ARTICLE|PART)\s+[A-Z0-9]', st
        ):
            htxt = _strip_md_inline(st)
            if len(htxt) <= 100:
                blocks.append({'kind': 'h2', 'runs': [{'text': htxt, 'bold': True}]})
                i += 1
                continue

        # Bullet item
        m_bul = re.match(r'^(?:[•\-\*▪▸])\s+(.+)$', st)
        if m_bul:
            blocks.append({'kind': 'bullet', 'runs': _parse_inline_runs(m_bul.group(1).strip())})
            i += 1
            continue

        # Regular paragraph with inline bold runs
        blocks.append({'kind': 'para', 'runs': _parse_inline_runs(st)})
        i += 1

    return blocks


def _pdf_escape(s: str) -> str:
    safe = (s or '').encode('latin-1', 'replace').decode('latin-1')
    return safe.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def build_formatted_pdf_bytes(title: str, fixed_text: str, design: dict | None = None) -> bytes:
    """Builds a multi-page formatted PDF (%PDF-1.4) matching input font, colors, sizes, page size, and tables."""
    d = design or {}
    blocks = parse_formatted_blocks(title, fixed_text)

    page_w = float(d.get('page_width') or 595.28)
    page_h = float(d.get('page_height') or 841.89)
    margin_x = 52.0
    max_w = page_w - 2 * margin_x
    top_y = page_h - 56.0
    bottom_y = 52.0

    primary_rgb = _hex_to_rgb(d.get('primary_color'), (0.086, 0.227, 0.373))
    body_rgb = _hex_to_rgb(d.get('body_color'), (0.08, 0.11, 0.16))
    tbl_hdr_bg = _hex_to_rgb(d.get('table_header_bg'), (0.95, 0.96, 0.98))
    tbl_hdr_fg = _hex_to_rgb(d.get('table_header_fg'), primary_rgb)
    tbl_border = _hex_to_rgb(d.get('table_border_color'), (0.80, 0.84, 0.89))

    title_sz = float(d.get('title_size') or 18.0)
    h1_sz = float(d.get('heading_size') or 13.0)
    h2_sz = max(11.0, h1_sz - 1.5)
    body_sz = float(d.get('body_size') or 10.5)

    ff = d.get('font_family') or 'sans'
    if ff == 'serif':
        base_font, bold_font = 'Times-Roman', 'Times-Bold'
    elif ff == 'mono':
        base_font, bold_font = 'Courier', 'Courier-Bold'
    else:
        base_font, bold_font = 'Helvetica', 'Helvetica-Bold'

    pages: list[list[str]] = [[]]
    y = top_y

    def ensure_space(needed: float):
        nonlocal y
        if y - needed < bottom_y:
            pages.append([])
            y = top_y

    def emit_runs_line(x: float, size: float, runs_on_line: list[dict], color: tuple[float, float, float] = body_rgb):
        r, g, b = color
        parts = [f"BT {r:.3f} {g:.3f} {b:.3f} rg 1 0 0 1 {x:.2f} {y:.2f} Tm"]
        for seg in runs_on_line:
            font = 'F2' if seg['bold'] else 'F1'
            parts.append(f"/{font} {size:.1f} Tf ({_pdf_escape(seg['text'])}) Tj")
        parts.append("ET")
        pages[-1].append(" ".join(parts))

    def emit_line(x: float, font: str, size: float, text: str, color: tuple[float, float, float] = body_rgb):
        emit_runs_line(x, size, [{'text': text, 'bold': (font == 'F2')}], color)

    def wrap_runs(runs: list[dict], font_size: float, avail_w: float) -> list[list[dict]]:
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
        runs = blk.get('runs') or []
        if kind == 'title':
            wrapped = wrap_runs(runs, title_sz, max_w)
            ensure_space(len(wrapped) * (title_sz + 5.0) + 14.0)
            for ln in wrapped:
                txt = ''.join(r['text'] for r in ln)
                emit_line(margin_x, 'F2', title_sz, txt, primary_rgb)
                y -= (title_sz + 5.0)
            pages[-1].append(
                f"{primary_rgb[0]:.3f} {primary_rgb[1]:.3f} {primary_rgb[2]:.3f} RG 1.1 w "
                f"{margin_x:.2f} {y + 6:.2f} m {page_w - margin_x:.2f} {y + 6:.2f} l S"
            )
            y -= 10.0
        elif kind in ('h1', 'h2'):
            fsize = h1_sz if kind == 'h1' else h2_sz
            lead = fsize + 4.0
            wrapped = wrap_runs(runs, fsize, max_w)
            ensure_space(len(wrapped) * lead + 8.0)
            y -= 6.0
            for ln in wrapped:
                txt = ''.join(r['text'] for r in ln)
                emit_line(margin_x, 'F2', fsize, txt, primary_rgb)
                y -= lead
            y -= 2.0
        elif kind == 'divider':
            if y < top_y - 120.0:
                pages.append([])
                y = top_y
            else:
                y -= 10.0
        elif kind == 'table':
            rows = blk.get('rows') or []
            if not rows:
                continue
            num_cols = max((len(r) for r in rows), default=2) or 2
            col_w = max_w / num_cols
            row_h = 20.0
            ensure_space(min(len(rows), 4) * row_h + 10.0)
            for r_idx, row in enumerate(rows):
                ensure_space(row_h + 4.0)
                row_bottom = y - row_h + 6.0
                is_hdr = (r_idx == 0)
                x_cur = margin_x
                for c_idx in range(num_cols):
                    cell_txt = str(row[c_idx]) if c_idx < len(row) else ''
                    fill_rgb = tbl_hdr_bg if is_hdr else (1.0, 1.0, 1.0)
                    txt_rgb = tbl_hdr_fg if is_hdr else body_rgb
                    f_code = 'F2' if is_hdr else 'F1'
                    pages[-1].append(
                        f"{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg "
                        f"{tbl_border[0]:.3f} {tbl_border[1]:.3f} {tbl_border[2]:.3f} RG 0.6 w "
                        f"{x_cur:.2f} {row_bottom:.2f} {col_w:.2f} {row_h:.2f} re B"
                    )
                    max_c = max(8, int(col_w / 5.3))
                    prev_y = y
                    y = row_bottom + 6.0
                    emit_line(x_cur + 5.0, f_code, max(8.5, body_sz - 1.0), cell_txt[:max_c], txt_rgb)
                    y = prev_y
                    x_cur += col_w
                y -= row_h
            y -= 8.0
        elif kind == 'bullet':
            wrapped = wrap_runs(runs, body_sz, max_w - 16.0)
            lead = body_sz + 4.0
            ensure_space(len(wrapped) * lead + 4.0)
            for li, ln in enumerate(wrapped):
                if li == 0:
                    emit_line(margin_x + 4.0, 'F2', body_sz, '-', primary_rgb)
                emit_runs_line(margin_x + 16.0, body_sz, ln, body_rgb)
                y -= lead
            y -= 2.0
        else:
            wrapped = wrap_runs(runs, body_sz, max_w)
            lead = body_sz + 4.0
            ensure_space(len(wrapped) * lead + 5.0)
            for ln in wrapped:
                emit_runs_line(margin_x, body_sz, ln, body_rgb)
                y -= lead
            y -= 5.0

    objs: list[bytes] = []
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
    objs.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base_font} /Encoding /WinAnsiEncoding >>".encode('latin-1'))
    objs.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{bold_font} /Encoding /WinAnsiEncoding >>".encode('latin-1'))

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


def build_formatted_docx_bytes(title: str, fixed_text: str, design: dict | None = None) -> bytes:
    """Builds a valid .docx OOXML document matching input font, colors, sizes, and real Word tables."""
    d = design or {}
    blocks = parse_formatted_blocks(title, fixed_text)

    font_name = xml_escape(str(d.get('font_name') or 'Calibri'))
    primary_hex = _clean_hex(d.get('primary_color'), '163A5F')
    body_hex = _clean_hex(d.get('body_color'), '1E293B')
    tbl_hdr_bg = _clean_hex(d.get('table_header_bg'), 'F1F5F9')
    tbl_hdr_fg = _clean_hex(d.get('table_header_fg'), primary_hex)
    tbl_border = _clean_hex(d.get('table_border_color'), 'CBD5E1')
    title_hp = int(round(float(d.get('title_size') or 18.0) * 2))
    h1_hp = int(round(float(d.get('heading_size') or 13.0) * 2))
    h2_hp = max(22, h1_hp - 3)
    body_hp = int(round(float(d.get('body_size') or 10.5) * 2))
    rfonts = f'<w:rFonts w:ascii="{font_name}" w:hAnsi="{font_name}" w:cs="{font_name}"/>'

    para_xmls = []

    for blk in blocks:
        kind = blk['kind']
        if kind == 'divider':
            para_xmls.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            continue
        if kind == 'table':
            rows = blk.get('rows') or []
            if not rows:
                continue
            borders = (
                f'<w:tblBorders>'
                f'<w:top w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'<w:left w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'<w:bottom w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'<w:right w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'<w:insideH w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'<w:insideV w:val="single" w:sz="6" w:space="0" w:color="{tbl_border}"/>'
                f'</w:tblBorders>'
            )
            tr_xml = []
            for r_idx, row in enumerate(rows):
                tc_xml = []
                is_hdr = (r_idx == 0)
                c_bg = tbl_hdr_bg if is_hdr else 'FFFFFF'
                c_fg = tbl_hdr_fg if is_hdr else body_hex
                b_tag = '<w:b/>' if is_hdr else ''
                for cell in row:
                    esc_c = xml_escape(str(cell or ''))
                    tc_xml.append(
                        f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="{c_bg}"/></w:tcPr>'
                        f'<w:p><w:r><w:rPr>{rfonts}{b_tag}<w:sz w:val="{max(18, body_hp - 1)}"/><w:color w:val="{c_fg}"/></w:rPr>'
                        f'<w:t xml:space="preserve">{esc_c}</w:t></w:r></w:p></w:tc>'
                    )
                tr_xml.append(f'<w:tr>{"".join(tc_xml)}</w:tr>')
            para_xmls.append(f'<w:tbl><w:tblPr>{borders}</w:tblPr>{"".join(tr_xml)}</w:tbl><w:p/>')
            continue

        runs_xml = []
        for r in blk['runs']:
            txt = xml_escape(r['text'])
            if kind == 'title':
                runs_xml.append(f'<w:r><w:rPr>{rfonts}<w:b/><w:color w:val="{primary_hex}"/><w:sz w:val="{title_hp}"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            elif kind in ('h1', 'h2'):
                sz = h1_hp if kind == 'h1' else h2_hp
                runs_xml.append(f'<w:r><w:rPr>{rfonts}<w:b/><w:color w:val="{primary_hex}"/><w:sz w:val="{sz}"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            elif r['bold']:
                runs_xml.append(f'<w:r><w:rPr>{rfonts}<w:b/><w:color w:val="{body_hex}"/><w:sz w:val="{body_hp}"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')
            else:
                runs_xml.append(f'<w:r><w:rPr>{rfonts}<w:color w:val="{body_hex}"/><w:sz w:val="{body_hp}"/></w:rPr><w:t xml:space="preserve">{txt}</w:t></w:r>')

        if kind == 'bullet':
            bullet_prefix = f'<w:r><w:rPr>{rfonts}<w:b/><w:color w:val="{primary_hex}"/><w:sz w:val="{body_hp}"/></w:rPr><w:t xml:space="preserve">•  </w:t></w:r>'
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
