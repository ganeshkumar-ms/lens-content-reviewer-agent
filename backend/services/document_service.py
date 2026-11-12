import collections
import csv
import io
import re
import sys
import types
import zipfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}

# Common source-code / markup extensions -> readable language name
CODE_LANGS = {
    '.py': 'Python', '.java': 'Java', '.js': 'JavaScript', '.jsx': 'JavaScript (React)',
    '.ts': 'TypeScript', '.tsx': 'TypeScript (React)', '.html': 'HTML', '.htm': 'HTML',
    '.css': 'CSS', '.scss': 'SCSS', '.c': 'C', '.h': 'C header', '.cpp': 'C++', '.cs': 'C#',
    '.go': 'Go', '.rb': 'Ruby', '.php': 'PHP', '.rs': 'Rust', '.kt': 'Kotlin', '.swift': 'Swift',
    '.sql': 'SQL', '.sh': 'Shell', '.ps1': 'PowerShell', '.bat': 'Batch', '.json': 'JSON',
    '.xml': 'XML', '.yaml': 'YAML', '.yml': 'YAML', '.md': 'Markdown', '.ipynb': 'Jupyter Notebook',
    '.r': 'R', '.scala': 'Scala', '.dart': 'Dart', '.vue': 'Vue', '.svg': 'SVG', '.toml': 'TOML',
    '.ini': 'INI config', '.env': 'Env config', '.log': 'Log file',
}


def _ensure_pdfminer_ready():
    """Allows pure-Python pdfminer to import on AWS Lambda without C-extension cryptography."""
    try:
        import cryptography  # noqa: F401
    except Exception:
        m = types.ModuleType('cryptography')
        m.default_backend = lambda: None
        m.Cipher = None
        m.algorithms = None
        m.modes = None
        for mod_name in (
            'cryptography',
            'cryptography.hazmat',
            'cryptography.hazmat.backends',
            'cryptography.hazmat.primitives',
            'cryptography.hazmat.primitives.ciphers',
            'cryptography.hazmat.primitives.ciphers.algorithms',
            'cryptography.hazmat.primitives.ciphers.modes',
        ):
            sys.modules[mod_name] = m


def is_binary(data: bytes) -> bool:
    """Heuristic: null bytes or many non-text bytes in the first 4 KB means binary."""
    sample = data[:4096]
    if not sample:
        return False
    if b'\x00' in sample:
        return True
    text_chars = bytes(range(32, 127)) + b'\n\r\t\f\b'
    non_text = sum(1 for b in sample if b not in text_chars and b < 128)
    return non_text / len(sample) > 0.30


def _decode(data: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-16', 'latin-1'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode('utf-8', errors='ignore')


def file_kind(filename: str, data: bytes = b'') -> str:
    ext = Path(filename).suffix.lower()
    if ext == '.pdf':
        return 'pdf'
    if ext == '.zip':
        return 'zip'
    if ext in ('.pptx', '.ppt'):
        return 'pptx'
    if ext in ('.xls', '.xlsx'):
        return 'excel'
    if ext in ('.doc', '.docx'):
        return 'word'
    if ext == '.csv':
        return 'csv'
    if ext in IMAGE_EXTS:
        return 'image'
    if ext in CODE_LANGS:
        return 'code'
    if data and is_binary(data):
        return 'binary'
    return 'text'


def _extract_docx_stdlib(file_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        xml_bytes = z.read('word/document.xml')
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for p in root.iter():
        if p.tag.endswith('}p'):
            texts = [t.text for t in p.iter() if t.tag.endswith('}t') and t.text]
            if texts:
                paragraphs.append(''.join(texts))
    return '\n'.join(paragraphs)


def _extract_pptx_stdlib(file_bytes: bytes) -> tuple:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        slide_files = sorted(
            n for n in z.namelist()
            if n.startswith('ppt/slides/slide') and n.endswith('.xml')
        )
        slides_out = []
        for idx, sf in enumerate(slide_files, 1):
            root = ET.fromstring(z.read(sf))
            texts = [el.text.strip() for el in root.iter() if el.tag.endswith('}t') and el.text and el.text.strip()]
            if texts:
                slides_out.append(f'[Slide {idx}]\n' + '\n'.join(texts))
        return len(slide_files), '\n\n'.join(slides_out)


def _extract_xlsx_stdlib(file_bytes: bytes) -> tuple:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            s_root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in s_root.iter():
                if si.tag.endswith('}si'):
                    shared.append(''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t')))
        sheet_files = sorted(n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))
        sheets_out = []
        sheet_names = []
        for idx, sf in enumerate(sheet_files, 1):
            s_name = f'Sheet{idx}'
            sheet_names.append(s_name)
            w_root = ET.fromstring(z.read(sf))
            rows_txt = []
            for row in w_root.iter():
                if row.tag.endswith('}row'):
                    vals = []
                    for c in row:
                        if not c.tag.endswith('}c'):
                            continue
                        t_attr = c.attrib.get('t', '')
                        v_val = ''
                        for child in c:
                            if child.tag.endswith('}v') and child.text is not None:
                                v_val = child.text
                            elif child.tag.endswith('}is'):
                                v_val = ''.join(x.text or '' for x in child.iter() if x.tag.endswith('}t'))
                        if t_attr == 's' and v_val.isdigit() and int(v_val) < len(shared):
                            v_val = shared[int(v_val)]
                        vals.append(v_val)
                    if any(vals):
                        rows_txt.append('\t'.join(vals))
            sheets_out.append(f'[Sheet: {s_name}]\n' + '\n'.join(rows_txt))
        return sheet_names, '\n\n'.join(sheets_out)


def _extract_zip_stdlib(file_bytes: bytes, filename: str) -> tuple:
    """Inspects a .zip archive and extracts file manifest plus content from readable files inside."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        infos = [info for info in z.infolist() if not info.is_dir() and not info.filename.startswith('__MACOSX/')]
        file_list = [info.filename for info in infos]
        summary_lines = [
            f"[ZIP Archive: {filename} | Total files: {len(infos)}]",
            "Files in archive:"
        ]
        for info in infos[:80]:
            summary_lines.append(f"  - {info.filename} ({info.file_size} bytes)")
        if len(infos) > 80:
            summary_lines.append(f"  ... and {len(infos) - 80} more files")

        extracted_snippets = []
        total_extracted_chars = 0
        skip_dirs = ('node_modules/', '.git/', 'dist/', 'build/', '__pycache__/', '.venv/', 'venv/')

        for info in infos:
            if total_extracted_chars >= 20000:
                break
            if any(part in info.filename for part in skip_dirs):
                continue
            if info.file_size == 0 or info.file_size > 4 * 1024 * 1024:
                continue
            inner_ext = Path(info.filename).suffix.lower()
            try:
                raw_inner = z.read(info.filename)
                inner_text = ''
                if inner_ext == '.docx':
                    inner_text = _extract_docx_stdlib(raw_inner)
                elif inner_ext == '.xlsx':
                    _, inner_text = _extract_xlsx_stdlib(raw_inner)
                elif inner_ext == '.pptx':
                    _, inner_text = _extract_pptx_stdlib(raw_inner)
                elif inner_ext in CODE_LANGS or inner_ext in ('.txt', '.csv', '.rst', '.cfg', '.conf', '.properties') or not is_binary(raw_inner):
                    inner_text = _decode(raw_inner)
                if inner_text and inner_text.strip():
                    snippet = inner_text.strip()[:3000]
                    extracted_snippets.append(f"--- [File: {info.filename}] ---\n{snippet}")
                    total_extracted_chars += len(snippet)
            except Exception:
                continue

        full_text = '\n'.join(summary_lines)
        if extracted_snippets:
            full_text += '\n\nExtracted File Contents:\n' + '\n\n'.join(extracted_snippets)
        return file_list, full_text


def _ocr_with_textract(file_bytes: bytes) -> str:
    """Uses AWS Textract OCR to extract text from single-page PDFs or images."""
    if len(file_bytes) == 0 or len(file_bytes) > 5_000_000:
        return ''
    try:
        import boto3, os
        region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1'
        tx = boto3.client('textract', region_name=region)
        res = tx.detect_document_text(Document={'Bytes': file_bytes})
        lines = [blk['Text'] for blk in res.get('Blocks', []) if blk.get('BlockType') == 'LINE' and blk.get('Text')]
        return '\n'.join(lines)
    except Exception:
        return ''


def _detect_image_format(file_bytes: bytes, ext: str) -> str:
    if file_bytes.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if file_bytes.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBP':
        return 'webp'
    clean = ext.lower().lstrip('.')
    if clean in ('jpg', 'jpeg'):
        return 'jpeg'
    if clean in ('png', 'gif', 'webp'):
        return clean
    return 'jpeg'


def _analyze_image_with_bedrock(file_bytes: bytes, ext: str) -> str:
    """Uses Amazon Bedrock Nova Pro Vision to read and describe images, photos, ID cards, diagrams, or screenshots."""
    if len(file_bytes) == 0 or len(file_bytes) > 4_800_000:
        return ''
    try:
        import boto3, os
        region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1'
        br = boto3.client('bedrock-runtime', region_name=region)
        fmt = _detect_image_format(file_bytes, ext)
        res = br.converse(
            modelId='us.amazon.nova-pro-v1:0',
            messages=[{
                'role': 'user',
                'content': [
                    {'image': {'format': fmt, 'source': {'bytes': file_bytes}}},
                    {'text': (
                        'Examine this image thoroughly. '
                        '1) Transcribe ALL visible text, labels, headings, numbers, IDs, code snippets, or table contents verbatim. '
                        '2) Describe clearly what this image/document is so it can be classified with 100% accuracy.'
                    )}
                ]
            }],
            inferenceConfig={'maxTokens': 2500, 'temperature': 0.0}
        )
        return res['output']['message']['content'][0]['text'].strip()
    except Exception:
        return ''


def _extract_pdf_with_bedrock(file_bytes: bytes) -> str:
    """Uses Amazon Bedrock Nova Pro native PDF document support for multi-page or scanned PDFs <= 4.5 MB."""
    if len(file_bytes) == 0 or len(file_bytes) > 4_500_000:
        return ''
    try:
        import boto3, os
        region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1'
        br = boto3.client('bedrock-runtime', region_name=region)
        res = br.converse(
            modelId='us.amazon.nova-pro-v1:0',
            messages=[{
                'role': 'user',
                'content': [
                    {'document': {'format': 'pdf', 'name': 'uploaded_document', 'source': {'bytes': file_bytes}}},
                    {'text': (
                        'Read ALL pages of this PDF document from start to finish (do not stop after page 1 or 2). '
                        '1) State the exact title, author/issuer, industry/domain, and true document/artifact nature. '
                        '2) List all section/chapter headings across the entire document. '
                        '3) Transcribe detailed readable text, concepts, definitions, data, code, and tables from the beginning, middle, and end pages verbatim.'
                    )}
                ]
            }],
            inferenceConfig={'maxTokens': 2000, 'temperature': 0.0}
        )
        return res['output']['message']['content'][0]['text'].strip()
    except Exception:
        return ''


def _extract_large_pdf_with_bedrock_images(file_bytes: bytes) -> str:
    """
    For large PDFs (> 4.5 MB, such as 43 MB scanned study materials/books) that exceed Bedrock's inline PDF byte limit:
    Samples embedded JPEG/PNG page images across the beginning (cover/title/TOC), 20%, 40%, 60%, 80%, and end of the PDF,
    and sends up to 6 representative pages in a single multimodal Bedrock Nova Pro Vision call.
    """
    if len(file_bytes) == 0:
        return ''
    try:
        total_len = len(file_bytes)
        window_size = min(2_200_000, total_len)
        offsets = [0]
        if total_len > window_size:
            for frac in (0.15, 0.35, 0.55, 0.75, 0.90):
                off = int(total_len * frac)
                if off + window_size > total_len:
                    off = max(0, total_len - window_size)
                if off - offsets[-1] > 400_000:
                    offsets.append(off)

        sampled_images = []
        total_img_bytes = 0
        seen_hashes = set()

        for off in offsets:
            chunk = file_bytes[off:off + window_size]
            # Find embedded JPEG streams (> 12 KB so we skip tiny icons/thumbnails and get full pages)
            for m in re.finditer(b'\xff\xd8\xff.*?\xff\xd9', chunk, re.DOTALL):
                jpg = m.group(0)
                if 12_000 <= len(jpg) <= 900_000:
                    sig = (len(jpg), jpg[:64], jpg[-64:])
                    if sig not in seen_hashes and total_img_bytes + len(jpg) <= 3_600_000:
                        seen_hashes.add(sig)
                        sampled_images.append(('jpeg', jpg))
                        total_img_bytes += len(jpg)
                        break
            if len(sampled_images) >= 6:
                break

        # If we found fewer than 2 images from offsets, scan the first 4 MB for up to 5 page JPEGs
        if len(sampled_images) < 2:
            for m in re.finditer(b'\xff\xd8\xff.*?\xff\xd9', file_bytes[:4_500_000], re.DOTALL):
                jpg = m.group(0)
                if 12_000 <= len(jpg) <= 900_000:
                    sig = (len(jpg), jpg[:64], jpg[-64:])
                    if sig not in seen_hashes and total_img_bytes + len(jpg) <= 3_600_000:
                        seen_hashes.add(sig)
                        sampled_images.append(('jpeg', jpg))
                        total_img_bytes += len(jpg)
                        if len(sampled_images) >= 5:
                            break

        if not sampled_images:
            return ''

        import boto3, os
        region = os.getenv('AWS_DEFAULT_REGION') or os.getenv('AWS_REGION') or 'us-east-1'
        br = boto3.client('bedrock-runtime', region_name=region)
        content_blocks = [
            {'image': {'format': fmt, 'source': {'bytes': img_b}}}
            for fmt, img_b in sampled_images
        ]
        content_blocks.append({
            'text': (
                f'These {len(sampled_images)} page images are sampled from the beginning, middle, and end '
                'of a multi-page PDF document. '
                '1) Transcribe the exact Document/Book Title, Subtitle, Author/Issuer, and Table of Contents/Headings visible on these pages. '
                '2) Transcribe all text, concepts, data, diagrams, tables, and details visible across each of these pages in detail. '
                '3) Clearly state the true industry, subject matter, and overall artifact type of the document.'
            )
        })
        res = br.converse(
            modelId='us.amazon.nova-pro-v1:0',
            messages=[{'role': 'user', 'content': content_blocks}],
            inferenceConfig={'maxTokens': 2000, 'temperature': 0.0}
        )
        return res['output']['message']['content'][0]['text'].strip()
    except Exception:
        return ''


def _extract_pdf_digital_text(file_bytes: bytes, total_pages_hint: int = 1) -> tuple:
    """
    Extracts digital text across the ENTIRE PDF (start, middle, end pages) using pdfplumber or pure-Python pdfminer.
    Returns (page_count, full_extracted_text).
    """
    pages_count = total_pages_hint
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_count = len(pdf.pages)
            if pages_count <= 45:
                indices = list(range(pages_count))
            else:
                mid_step = max(1, (pages_count - 20) // 25)
                indices = sorted(set(
                    list(range(min(10, pages_count)))
                    + list(range(10, max(10, pages_count - 10), mid_step))[:25]
                    + list(range(max(0, pages_count - 10), pages_count))
                ))
            page_texts = []
            for i in indices:
                pt = (pdf.pages[i].extract_text() or '').strip()
                if pt:
                    page_texts.append(f"[Page {i + 1} of {pages_count}]\n{pt}")
            joined = '\n\n'.join(page_texts)
            if len(joined.strip()) >= 150:
                return pages_count, joined
    except Exception:
        pass

    try:
        _ensure_pdfminer_ready()
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        if pages_count <= 45:
            extracted = pdfminer_extract_text(io.BytesIO(file_bytes))
        else:
            mid_step = max(1, (pages_count - 20) // 25)
            indices = sorted(set(
                list(range(min(10, pages_count)))
                + list(range(10, max(10, pages_count - 10), mid_step))[:25]
                + list(range(max(0, pages_count - 10), pages_count))
            ))
            extracted = pdfminer_extract_text(io.BytesIO(file_bytes), page_numbers=indices)
        if extracted and len(extracted.strip()) >= 150:
            return pages_count, extracted.strip()
    except Exception:
        pass

    return pages_count, ''


def _count_pdf_pages_stdlib(file_bytes: bytes) -> int:
    try:
        matches = re.findall(rb'/Type\s*/Page\b', file_bytes)
        return max(1, len(matches))
    except Exception:
        return 1


def _build_deep_document_representation(text: str, meta: dict) -> str:
    """
    Ensures the AI reads a massive amount of text across the ENTIRE document (up to 45,000 chars / ~7,500+ words)
    from beginning, 25%, 50%, 75%, and end—plus a document-wide term frequency profile—so it NEVER judges early
    from introductory business framing on page 1.
    """
    clean = (text or '').strip()
    if not clean:
        return ''

    words = re.findall(r'[A-Za-z][A-Za-z0-9_+#.\-]{2,}', clean)
    meta['word_count'] = len(words)

    header_profile = (
        f"[FULL-DOCUMENT ANALYSIS METADATA]\n"
        f"- Total Extracted Words: {len(words):,} words ({len(clean):,} characters)\n"
        f"- Total Pages / Sections: {meta.get('pages') or meta.get('slides') or meta.get('sheets') or 1}\n"
        f"- Instruction: Read all sections below from beginning to end before classifying. Do NOT judge early from page 1 alone.\n"
        f"====================================================================\n"
    )

    max_chars = 44000
    if len(clean) <= max_chars:
        return header_profile + clean

    # Stratified multi-section sampling across 0%, 25%, 50%, 75%, and 100% of the entire document
    sec_len = max_chars // 5
    n = len(clean)
    s1 = clean[0:sec_len]
    s2 = clean[int(n * 0.22):int(n * 0.22) + sec_len]
    s3 = clean[int(n * 0.45):int(n * 0.45) + sec_len]
    s4 = clean[int(n * 0.68):int(n * 0.68) + sec_len]
    s5 = clean[max(0, n - sec_len):n]

    return (
        header_profile
        + f"\n[SECTION 1: DOCUMENT BEGINNING / TITLE / TOC (0% - 20%)]\n{s1}\n"
        + f"\n[SECTION 2: EARLY CHAPTERS / BODY (20% - 40%)]\n{s2}\n"
        + f"\n[SECTION 3: MIDDLE CORE CHAPTERS (40% - 65%)]\n{s3}\n"
        + f"\n[SECTION 4: ADVANCED / LATER CHAPTERS (65% - 85%)]\n{s4}\n"
        + f"\n[SECTION 5: FINAL CHAPTERS & CONCLUSION (85% - 100%)]\n{s5}\n"
    )


def extract_text(file_bytes: bytes, filename: str, total_size_override: int = None) -> dict:
    """Extracts deep text across the entire document. Never raises: unreadable files get a note instead."""
    ext = Path(filename).suffix.lower()
    kind = file_kind(filename, file_bytes)
    actual_size = total_size_override if total_size_override is not None else len(file_bytes)
    meta = {'filename': filename, 'type': ext or 'unknown', 'kind': kind, 'size_bytes': actual_size}
    if kind == 'code':
        meta['language'] = CODE_LANGS[ext]

    text = ''
    note = ''
    try:
        if kind == 'pdf':
            est_pages = _count_pdf_pages_stdlib(file_bytes)
            pages_count, digital_text = _extract_pdf_digital_text(file_bytes, est_pages)
            meta['pages'] = pages_count
            text = digital_text

            if len(text.strip()) < 150 and len(file_bytes) > 0:
                if len(file_bytes) <= 4_500_000 and actual_size <= 4_500_000:
                    br_text = _extract_pdf_with_bedrock(file_bytes)
                    if br_text.strip():
                        text = br_text
                if len(text.strip()) < 150:
                    # Large or scanned PDF: extract multiple page images across start, middle, and end via Bedrock Vision
                    large_vision_text = _extract_large_pdf_with_bedrock_images(file_bytes)
                    if large_vision_text.strip():
                        text = large_vision_text
                if len(text.strip()) < 100 and len(file_bytes) <= 5_000_000:
                    tx_text = _ocr_with_textract(file_bytes)
                    if tx_text.strip():
                        text = tx_text
        elif kind == 'zip':
            file_list, text = _extract_zip_stdlib(file_bytes, filename)
            meta['files_count'] = len(file_list)
            meta['files'] = file_list[:60]
        elif kind == 'pptx':
            slides_count, text = _extract_pptx_stdlib(file_bytes)
            meta['slides'] = slides_count
        elif kind == 'word':
            try:
                from docx import Document
                doc = Document(io.BytesIO(file_bytes))
                text = '\n'.join(p.text for p in doc.paragraphs)
            except Exception:
                text = _extract_docx_stdlib(file_bytes)
        elif kind == 'excel':
            try:
                import pandas as pd
                sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
                meta['sheets'] = list(sheets.keys())
                text = '\n\n'.join(f'[Sheet: {n}]\n{df.to_string()}' for n, df in sheets.items())
            except Exception:
                s_names, text = _extract_xlsx_stdlib(file_bytes)
                meta['sheets'] = s_names
        elif kind == 'csv':
            try:
                import pandas as pd
                text = pd.read_csv(io.BytesIO(file_bytes)).to_string()
            except Exception:
                decoded = _decode(file_bytes)
                reader = csv.reader(io.StringIO(decoded))
                text = '\n'.join('\t'.join(r) for r in reader)
        elif kind == 'image':
            if len(file_bytes) > 0:
                ocr_text = _ocr_with_textract(file_bytes)
                vision_text = _analyze_image_with_bedrock(file_bytes, ext)
                if ocr_text.strip() and len(ocr_text.strip()) >= 40 and vision_text.strip():
                    text = f"[Image Visual Analysis]\n{vision_text}\n\n[Extracted OCR Text]\n{ocr_text}"
                elif vision_text.strip():
                    text = f"[Image Visual Analysis]\n{vision_text}"
                elif ocr_text.strip():
                    text = ocr_text
            if not text.strip():
                note = f'This is an image file ({ext or "image"}).'
        elif kind == 'binary':
            note = f'This is a binary file ({ext or "no extension"}); no text could be extracted.'
        else:  # code / text / unknown text-like
            text = _decode(file_bytes)
            meta['lines'] = text.count('\n') + 1
    except Exception as e:
        if not is_binary(file_bytes):
            text = _decode(file_bytes)
        else:
            note = f'Could not read this {ext or "unknown"} file ({e}).'

    meta['char_count'] = len(text)
    meta['is_empty'] = (actual_size == 0 or (kind in ('text', 'code') and len(text.strip()) == 0))
    meta['preview'] = text[:6000] if text else (note or '[Empty file - 0 bytes]')

    if meta['is_empty']:
        ai_text = '[FILE CONTENT IS EMPTY (0 BYTES)]'
    else:
        if text:
            ai_text = _build_deep_document_representation(text, meta)
        else:
            ai_text = f'[{note} Classify using the file name and type only.]'
        if kind == 'code':
            ai_text = f'[Source code file, language: {meta["language"]}]\n{ai_text}'

    return {'text': ai_text, 'metadata': meta}
