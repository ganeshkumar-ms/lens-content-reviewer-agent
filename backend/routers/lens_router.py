import os
import sys
from pathlib import Path
from typing import Optional
import json
import uuid
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import lens_service, document_service, file_validation, viewer_service

router = APIRouter(prefix='/api')
UPLOADS_DIR = Path('/tmp/uploads') if os.path.exists('/tmp') else (BACKEND_DIR / 'uploads')
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_upload(filename: str) -> Path:
    safe = Path(filename).name
    file_path = UPLOADS_DIR / safe
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File not found. Please upload it again.')
    return file_path


def _display_name(stored: str) -> str:
    return stored.split('_', 1)[1] if len(stored) > 9 and stored[8] == '_' else stored


@router.get('/health')
def health():
    return {"status": "ok", "agent": "LENS", "service": "Content Reviewer & Consistency Auditor"}


@router.get('/document/{filename}/view')
def view_document(filename: str):
    """Opens the uploaded file inside the browser (PDF inline, fixed HTML direct, Excel/Word/CSV/TXT as HTML)."""
    file_path = _resolve_upload(filename)
    name = _display_name(file_path.name)
    if file_path.suffix.lower() == '.pdf':
        return FileResponse(path=file_path, media_type='application/pdf',
                            headers={'Content-Disposition': f'inline; filename="{name}"'})
    if file_path.name.startswith('fixed_') and file_path.suffix.lower() in ('.html', '.htm'):
        return HTMLResponse(file_path.read_text(encoding='utf-8', errors='ignore'))
    return HTMLResponse(viewer_service.render_html(file_path, name))


@router.get('/document/{filename}')
def get_document(filename: str):
    """Downloads the original or fixed file in its exact format."""
    file_path = _resolve_upload(filename)
    ext = file_path.suffix.lower()
    mtype = {
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.html': 'text/html; charset=utf-8',
        '.htm': 'text/html; charset=utf-8',
        '.txt': 'text/plain; charset=utf-8',
        '.md': 'text/markdown; charset=utf-8',
        '.csv': 'text/csv; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.xml': 'application/xml; charset=utf-8',
    }.get(ext)
    return FileResponse(path=file_path, media_type=mtype, filename=_display_name(file_path.name))


def _build_pdf_bytes_simple(title: str, text: str) -> bytes:
    """Pure-stdlib multi-page PDF 1.4 generator for fixed .pdf exports."""
    import textwrap
    safe_s = (text or '').replace('₹', 'Rs. ').replace('—', '-').replace('–', '-').replace('•', '*').replace('·', '-')
    safe_s = safe_s.encode('latin-1', errors='replace').decode('latin-1')
    safe_title = (title or 'Fixed Document').encode('latin-1', errors='replace').decode('latin-1')
    page_w, page_h, margin_x, top_y, bottom_y, line_h = 595, 842, 48, 790, 52, 15
    pages_cmds: list[list[str]] = [[]]
    y = top_y

    def add_line(ln: str, font: str = 'F1', size: int = 10, rgb=(0.12, 0.16, 0.22)):
        nonlocal y
        if y < bottom_y:
            pages_cmds.append([])
            y = top_y
        esc = ln.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        pages_cmds[-1].append(f"BT /{font} {size} Tf {rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f} rg {margin_x} {y} Td ({esc}) Tj ET")
        y -= line_h

    add_line(safe_title, font='F2', size=14, rgb=(0.04, 0.24, 0.48))
    y -= 6
    for raw_ln in safe_s.splitlines():
        if not raw_ln.strip():
            y -= 6
            continue
        for wln in (textwrap.wrap(raw_ln, width=88) or ['']):
            add_line(wln)

    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids, page_data, next_id = [], [], 5
    for cmds in pages_cmds:
        stream = '\n'.join(cmds).encode('latin-1', errors='replace')
        page_ids.append(next_id + 1)
        page_data.append((next_id, stream, next_id + 1))
        next_id += 2
    kids = ' '.join(f"{pid} 0 R" for pid in page_ids)
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode('latin-1'))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    for cid, stream, pid in page_data:
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode('latin-1') + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {cid} 0 R >>".encode('latin-1'))

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objs, 1):
        offsets.append(len(buf))
        buf.extend(f"{i} 0 obj\n".encode('latin-1') + obj + b"\nendobj\n")
    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode('latin-1'))
    for off in offsets[1:]:
        buf.extend(f"{off:010d} 00000 n \n".encode('latin-1'))
    buf.extend(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode('latin-1'))
    return bytes(buf)


def _build_docx_bytes_simple(title: str, text: str) -> bytes:
    """Pure-stdlib minimal valid .docx generator for fixed .docx exports."""
    import io, zipfile, html as html_lib
    paras = [f"<w:p><w:r><w:rPr><w:b/><w:sz w:val=\"28\"/></w:rPr><w:t>{html_lib.escape(title or 'Fixed Document')}</w:t></w:r></w:p>"]
    for ln in (text or '').splitlines():
        paras.append(f"<w:p><w:r><w:t xml:space=\"preserve\">{html_lib.escape(ln)}</w:t></w:r></w:p>")
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(paras)}<w:sectPr/></w:body></w:document>'
    )
    ct_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    rels_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', ct_xml)
        zf.writestr('_rels/.rels', rels_xml)
        zf.writestr('word/document.xml', doc_xml)
    return buf.getvalue()


@router.post('/review')
async def review(
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    conversation_history: Optional[str] = Form('[]')
):
    try:
        history = json.loads(conversation_history or '[]')
    except json.JSONDecodeError:
        history = []

    doc_meta = None
    stored_name = None
    raw_doc_text = None
    combined_text = text or ''
    file_name = ''

    if file:
        file_name = file.filename or 'document'
        file_bytes = await file.read()
        pre_rej = file_validation.validate_file_pre_extract(file_name, file_bytes)
        if pre_rej:
            return {
                'type': 'chat',
                'message': pre_rej['message'],
                'rejected': True,
                'guardrail_status': 'BLOCKED',
                'guardrails': {
                    'status': 'BLOCKED',
                    'action': 'BLOCKED_SENSITIVE_CREDENTIALS',
                    'triggered_rule': 'Zero-Password & Secret Credential Policy (AWS / API Keys)',
                    'rejection_reason': pre_rej.get('title', 'Authentication Credentials / Access Keys Rejected')
                },
                'rejection_details': pre_rej,
                'document_metadata': {'filename': file_name, 'size_bytes': len(file_bytes)},
            }
        stored_name = f"{uuid.uuid4().hex[:8]}_{Path(file_name).name}"
        try:
            (UPLOADS_DIR / stored_name).write_bytes(file_bytes)
        except Exception:
            stored_name = None

        extracted = document_service.extract_text(file_bytes, file_name)
        doc_meta = extracted.get('metadata', {})
        if stored_name:
            q = quote(stored_name)
            doc_meta['stored_name'] = stored_name
            doc_meta['url'] = f'/api/document/{q}'
            doc_meta['view_url'] = f'/api/document/{q}/view'

        user_text = (text or '').strip()

        post_rej = file_validation.validate_file_post_extract(file_name, file_bytes, extracted.get('text', ''), meta=doc_meta)
        if post_rej or doc_meta.get('is_empty', False) or len(file_bytes) == 0:
            return {
                'type': 'chat',
                'message': post_rej['message'] if post_rej else f"File Not Accepted: '{file_name}' is empty.",
                'rejected': True,
                'rejection_details': post_rej,
                'document_metadata': doc_meta,
            }

        file_content = extracted.get('text', '')
        raw_doc_text = file_content
        combined_text = (
            f"[ATTACHED DOCUMENT FOR REVIEW: {file_name}]\n"
            f"==================== DOCUMENT CONTENT ====================\n"
            f"{file_content}\n"
            f"==========================================================\n"
        )
        if user_text:
            combined_text += f"\nAuthor's Notes / Review Focus: {user_text}\n"

    if not combined_text.strip():
        raise HTTPException(status_code=400, detail='Please provide content or upload a document to review.')

    result = lens_service.review_content(
        combined_text,
        file_name=file_name,
        conversation_history=history,
        raw_document_text=raw_doc_text
    )
    if doc_meta:
        result['document_metadata'] = doc_meta

    if result.get('modified_document'):
        mod = result['modified_document']
        fixed_html = mod.get('fixed_html') or ''
        fixed_txt = mod.get('fixed_text') or ''
        base_id = stored_name or uuid.uuid4().hex[:8]
        orig_ext = Path(file_name).suffix.lower() if file_name else '.txt'
        if not orig_ext:
            orig_ext = '.txt'
        orig_stem = Path(file_name).stem if file_name else Path(base_id).stem
        out_name = f"fixed_{Path(base_id).stem}{orig_ext}"
        try:
            out_path = UPLOADS_DIR / out_name
            if orig_ext == '.pdf':
                out_path.write_bytes(_build_pdf_bytes_simple(f"{orig_stem} (Fixed)", fixed_txt))
            elif orig_ext == '.docx':
                out_path.write_bytes(_build_docx_bytes_simple(f"{orig_stem} (Fixed)", fixed_txt))
            elif orig_ext in ('.html', '.htm'):
                out_path.write_text(fixed_html or f"<html><body><pre>{fixed_txt}</pre></body></html>", encoding='utf-8')
            else:
                out_path.write_text(fixed_txt, encoding='utf-8')
            q = quote(out_name)
            mod['filename'] = f"{orig_stem}_Fixed{orig_ext}"
            mod['original_ext'] = orig_ext
            mod['download_url'] = f"/api/document/{q}"
            mod['view_url'] = f"/api/document/{q}/view"
        except Exception:
            pass

    return result

