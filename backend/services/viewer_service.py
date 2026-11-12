import base64
import html
import io
import zipfile
from pathlib import Path

STYLE = """
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 20px 22px; background: #07080d; color: #e4e6ee;
         font-family: Inter, "Segoe UI", system-ui, sans-serif; font-size: 14px; line-height: 1.6; }
  h1.docTitle { font-size: 15px; letter-spacing: .5px; color: #b9aefc; margin: 0 0 16px; font-weight: 700;
                display: flex; align-items: center; justify-content: space-between; gap: 10px; word-break: break-word; }
  .badge { font-size: 11px; padding: 3px 8px; border-radius: 6px; background: rgba(140,119,255,0.15);
           color: #c5baff; border: 1px solid rgba(140,119,255,0.3); font-weight: 600; flex-shrink: 0; }
  h2.sheet { font-size: 13px; letter-spacing: 1.2px; text-transform: uppercase; color: #64dbff;
             margin: 24px 0 10px; font-weight: 700; }
  .tableWrap { overflow: auto; border: 1px solid #ffffff14; border-radius: 10px; margin-bottom: 18px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border-bottom: 1px solid #ffffff10; border-right: 1px solid #ffffff0a;
           padding: 7px 10px; text-align: left; vertical-align: top; white-space: pre-wrap; }
  th { background: #12141e; color: #cfc6ff; position: sticky; top: 0; font-weight: 650; }
  tr:nth-child(even) td { background: #ffffff04; }
  tr:hover td { background: #8c77ff14; }
  p { margin: 0 0 10px; }
  .h { color: #fff; font-weight: 700; margin: 18px 0 8px; }
  pre { white-space: pre-wrap; word-break: break-word; font-family: Consolas, Monaco, "Courier New", monospace;
        margin: 0 0 14px; background: #0c0e17; padding: 16px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08);
        font-size: 13px; line-height: 1.55; color: #d6daf0; overflow-x: auto; }
  .empty { color: #8a90a2; font-style: italic; }
  .tabBtn { background: #121420; color: #a8aebb; border: 1px solid rgba(255,255,255,0.1);
            padding: 6px 14px; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; transition: 0.2s; }
  .tabBtn:hover, .tabBtn.active { background: #8c77ff22; color: #fff; border-color: #8c77ff66; }
  .imgWrap { display: flex; flex-direction: column; align-items: center; justify-content: center;
             background: #0c0e17; padding: 18px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.08); }
  .imgWrap img { max-width: 100%; max-height: 78vh; border-radius: 8px; object-fit: contain; }
  .slideCard { background: #0c0e17; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; }
</style>
"""


def _page(title: str, body: str, badge: str = '') -> str:
    badge_html = f"<span class='badge'>{html.escape(badge)}</span>" if badge else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"{STYLE}</head><body><h1 class='docTitle'><span>📄 {html.escape(title)}</span>{badge_html}</h1>{body}</body></html>")


def _df_html(df) -> str:
    df = df.fillna('')
    return "<div class='tableWrap'>" + df.to_html(index=False, border=0, escape=True) + "</div>"


def render_html(file_path: Path, display_name: str) -> str:
    ext = file_path.suffix.lower()
    try:
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
            raw = file_path.read_bytes()
            mime_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.bmp': 'image/bmp',
            }
            mime = mime_map.get(ext, 'image/jpeg')
            b64 = base64.b64encode(raw).decode('ascii')
            kb = len(raw) / 1024
            size_lbl = f"{kb:.1f} KB" if kb < 1024 else f"{kb/1024:.2f} MB"
            body = (
                f"<div class='imgWrap'>"
                f"<img src='data:{mime};base64,{b64}' alt='{html.escape(display_name)}' />"
                f"<div style='margin-top:10px;font-size:12px;color:#8a90a2'>{html.escape(display_name)} · {size_lbl}</div>"
                f"</div>"
            )
            return _page(display_name, body, badge=ext.lstrip('.').upper())

        if ext == '.zip':
            from services.document_service import _extract_zip_stdlib
            raw = file_path.read_bytes()
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith('__MACOSX/')]
                rows_html = ''.join(
                    f"<tr><td>{html.escape(i.filename)}</td>"
                    f"<td>{html.escape(Path(i.filename).suffix.lower() or 'file')}</td>"
                    f"<td>{i.file_size:,} B</td></tr>"
                    for i in infos[:150]
                )
            _, full_txt = _extract_zip_stdlib(raw, display_name)
            body = (
                f"<h2 class='sheet'>ZIP Archive Contents ({len(infos)} files)</h2>"
                f"<div class='tableWrap'><table><thead><tr><th>File Path</th><th>Type</th><th>Size</th></tr></thead>"
                f"<tbody>{rows_html}</tbody></table></div>"
                f"<h2 class='sheet'>Extracted Content Preview</h2>"
                f"<pre>{html.escape(full_txt)}</pre>"
            )
            return _page(display_name, body, badge='ZIP ARCHIVE')

        if ext in ('.pptx', '.ppt'):
            from services.document_service import _extract_pptx_stdlib
            slides_count, txt = _extract_pptx_stdlib(file_path.read_bytes())
            blocks = [b for b in txt.split('\n\n') if b.strip()]
            cards = ''.join(f"<div class='slideCard'><pre style='margin:0;border:0;padding:0'>{html.escape(b)}</pre></div>" for b in blocks)
            return _page(display_name, cards or "<p class='empty'>No slide text found</p>", badge=f'PPTX · {slides_count} SLIDES')

        if ext in ('.xlsx', '.xls'):
            try:
                import pandas as pd
                sheets = pd.read_excel(file_path, sheet_name=None)
                parts = []
                for name, df in sheets.items():
                    parts.append(f"<h2 class='sheet'>Sheet · {html.escape(str(name))}</h2>")
                    parts.append(_df_html(df) if not df.empty else "<p class='empty'>Empty sheet</p>")
                return _page(display_name, ''.join(parts), badge='EXCEL')
            except Exception:
                from services.document_service import _extract_xlsx_stdlib
                _, txt = _extract_xlsx_stdlib(file_path.read_bytes())
                parts = []
                for block in txt.split('\n\n'):
                    lines = [ln for ln in block.splitlines() if ln.strip()]
                    if not lines:
                        continue
                    header = lines[0]
                    rows = [ln.split('\t') for ln in lines[1:]]
                    parts.append(f"<h2 class='sheet'>{html.escape(header)}</h2>")
                    if rows:
                        thead = '<tr>' + ''.join(f'<th>{html.escape(c)}</th>' for c in rows[0]) + '</tr>'
                        tbody = ''.join('<tr>' + ''.join(f'<td>{html.escape(c)}</td>' for c in r) + '</tr>' for r in rows[1:])
                        parts.append(f"<div class='tableWrap'><table><thead>{thead}</thead><tbody>{tbody}</tbody></table></div>")
                return _page(display_name, ''.join(parts) or f"<pre>{html.escape(txt)}</pre>", badge='EXCEL')

        if ext == '.csv':
            try:
                import pandas as pd
                return _page(display_name, _df_html(pd.read_csv(file_path)), badge='CSV')
            except Exception:
                import csv
                raw = file_path.read_bytes().decode('utf-8', errors='ignore')
                rows = list(csv.reader(io.StringIO(raw)))
                if not rows:
                    return _page(display_name, "<p class='empty'>Empty CSV</p>", badge='CSV')
                thead = '<tr>' + ''.join(f'<th>{html.escape(c)}</th>' for c in rows[0]) + '</tr>'
                tbody = ''.join('<tr>' + ''.join(f'<td>{html.escape(c)}</td>' for c in r) + '</tr>' for r in rows[1:])
                return _page(display_name, f"<div class='tableWrap'><table><thead>{thead}</thead><tbody>{tbody}</tbody></table></div>", badge='CSV')

        if ext in ('.docx', '.doc'):
            try:
                from docx import Document
                doc = Document(str(file_path))
                parts = []
                for p in doc.paragraphs:
                    if not p.text.strip():
                        continue
                    cls = " class='h'" if (p.style is not None and p.style.name.lower().startswith('heading')) else ''
                    parts.append(f"<p{cls}>{html.escape(p.text)}</p>")
                for t in doc.tables:
                    rows = ''.join(
                        '<tr>' + ''.join(f'<td>{html.escape(c.text)}</td>' for c in r.cells) + '</tr>'
                        for r in t.rows
                    )
                    parts.append(f"<div class='tableWrap' style='margin:14px 0'><table>{rows}</table></div>")
                return _page(display_name, ''.join(parts) or "<p class='empty'>No readable content</p>", badge='DOCX')
            except Exception:
                from services.document_service import _extract_docx_stdlib
                txt = _extract_docx_stdlib(file_path.read_bytes())
                paras = ''.join(f'<p>{html.escape(line)}</p>' for line in txt.splitlines() if line.strip())
                return _page(display_name, paras or "<p class='empty'>No readable content</p>", badge='DOCX')

        if ext in ('.html', '.htm'):
            raw_html = file_path.read_bytes().decode('utf-8', errors='ignore')
            body = f"""
            <div style="margin-bottom:14px; display:flex; gap:8px;">
                <button class="tabBtn active" id="btnCode" onclick="document.getElementById('viewCode').style.display='block';document.getElementById('viewPreview').style.display='none';this.classList.add('active');document.getElementById('btnPrev').classList.remove('active');">Source Code</button>
                <button class="tabBtn" id="btnPrev" onclick="document.getElementById('viewCode').style.display='none';document.getElementById('viewPreview').style.display='block';this.classList.add('active');document.getElementById('btnCode').classList.remove('active');">Rendered HTML</button>
            </div>
            <div id="viewCode"><pre>{html.escape(raw_html)}</pre></div>
            <div id="viewPreview" style="display:none;background:#ffffff;border-radius:10px;padding:12px;color:#111">
                <iframe srcdoc="{html.escape(raw_html)}" style="width:100%;height:75vh;border:0;border-radius:6px;background:#fff"></iframe>
            </div>
            """
            return _page(display_name, body, badge='HTML')

        from services.document_service import CODE_LANGS
        badge = CODE_LANGS.get(ext, ext.upper().replace('.', '') if ext else 'TEXT')
        text = file_path.read_bytes().decode('utf-8', errors='ignore')
        return _page(display_name, f"<pre>{html.escape(text)}</pre>", badge=badge)
    except Exception as e:
        return _page(display_name, f"<p class='empty'>Could not render this file: {html.escape(str(e))}</p>")
