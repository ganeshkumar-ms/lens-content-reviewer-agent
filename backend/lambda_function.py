import base64
import json
import os
import re
import tempfile
import uuid
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from urllib.parse import quote, unquote

import boto3
from botocore.config import Config
from services import lens_service, document_service, file_validation, viewer_service

TMP_UPLOADS = Path(tempfile.gettempdir()) / 'uploads'
TMP_UPLOADS.mkdir(parents=True, exist_ok=True)
S3_BUCKET = os.environ.get('LENS_S3_BUCKET', 'lens-ui-984625844016')
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

s3_client = boto3.client(
    's3',
    region_name=REGION,
    endpoint_url=f'https://s3.{REGION}.amazonaws.com',
    config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'})
)

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': '*',
}


def _json_response(status_code: int, payload: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {**CORS_HEADERS, 'Content-Type': 'application/json'},
        'body': json.dumps(payload),
    }


def _parse_multipart(body_bytes: bytes, content_type: str) -> dict:
    raw_msg = b'Content-Type: ' + content_type.encode('utf-8') + b'\r\nMIME-Version: 1.0\r\n\r\n' + body_bytes
    msg = BytesParser(policy=default_email_policy).parsebytes(raw_msg)
    fields = {}
    file_info = None
    if msg.is_multipart():
        for part in msg.iter_parts():
            cd = part.get('Content-Disposition', '')
            if not cd:
                continue
            name = part.get_param('name', header='content-disposition')
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b''
            if filename:
                file_info = {'filename': filename, 'bytes': payload}
            elif name:
                fields[name] = payload.decode('utf-8', errors='replace')
    return {'fields': fields, 'file': file_info}


def _display_name(stored: str) -> str:
    return stored.split('_', 1)[1] if len(stored) > 9 and stored[8] == '_' else stored


def _sanitize_filename(filename: str) -> str:
    name = Path(filename or 'document').name
    return re.sub(r'[^\w.\- ()+\[\]]', '_', name) or 'document'


def _get_s3_size(s3_key: str) -> int:
    try:
        head = s3_client.head_object(Bucket=S3_BUCKET, Key=s3_key)
        return int(head.get('ContentLength', 0))
    except Exception:
        return -1


def _resolve_upload(filename: str) -> Path:
    safe = Path(unquote(filename)).name
    local_path = TMP_UPLOADS / safe
    if not local_path.exists():
        try:
            obj = s3_client.get_object(Bucket=S3_BUCKET, Key=f'uploads/{safe}')
            local_path.write_bytes(obj['Body'].read())
        except Exception:
            return None
    return local_path


def lambda_handler(event, context):
    method = (
        event.get('requestContext', {}).get('http', {}).get('method')
        or event.get('httpMethod')
        or 'GET'
    ).upper()

    raw_path = (
        event.get('requestContext', {}).get('http', {}).get('path')
        or event.get('rawPath')
        or event.get('path')
        or '/'
    )

    if method == 'OPTIONS':
        return {'statusCode': 204, 'headers': CORS_HEADERS, 'body': ''}

    if raw_path in ('/api/health', '/health'):
        return _json_response(200, {
            'status': 'ok',
            'agent': 'LENS',
            'eyebrow': 'CONTENT REVIEWER & CONSISTENCY AUDITOR',
            'aws_account': '984625844016',
        })

    if raw_path.startswith('/api/document/') and method == 'GET':
        tail = raw_path[len('/api/document/'):]
        is_view = tail.endswith('/view')
        fname = tail[:-len('/view')] if is_view else tail
        safe_stored = Path(unquote(fname)).name
        disp = _display_name(safe_stored)
        s3_size = _get_s3_size(f'uploads/{safe_stored}')

        if s3_size > 4_000_000 and (not is_view or safe_stored.lower().endswith('.pdf')):
            params = {
                'Bucket': S3_BUCKET,
                'Key': f'uploads/{safe_stored}',
                'ResponseContentDisposition': f'{"inline" if is_view else "attachment"}; filename="{disp}"',
            }
            if is_view and safe_stored.lower().endswith('.pdf'):
                params['ResponseContentType'] = 'application/pdf'
            presigned = s3_client.generate_presigned_url(
                ClientMethod='get_object',
                Params=params,
                ExpiresIn=3600,
            )
            return {'statusCode': 302, 'headers': {**CORS_HEADERS, 'Location': presigned}, 'body': ''}

        file_path = _resolve_upload(fname)
        if not file_path or not file_path.exists():
            return _json_response(404, {'detail': 'File not found. Please upload it again.'})

        if is_view:
            if file_path.suffix.lower() == '.pdf':
                return {
                    'statusCode': 200,
                    'headers': {
                        **CORS_HEADERS,
                        'Content-Type': 'application/pdf',
                        'Content-Disposition': f'inline; filename="{disp}"',
                    },
                    'isBase64Encoded': True,
                    'body': base64.b64encode(file_path.read_bytes()).decode('ascii'),
                }
            html_out = viewer_service.render_html(file_path, disp)
            return {
                'statusCode': 200,
                'headers': {**CORS_HEADERS, 'Content-Type': 'text/html; charset=utf-8'},
                'body': html_out,
            }
        else:
            return {
                'statusCode': 200,
                'headers': {
                    **CORS_HEADERS,
                    'Content-Type': 'application/octet-stream',
                    'Content-Disposition': f'attachment; filename="{disp}"',
                },
                'isBase64Encoded': True,
                'body': base64.b64encode(file_path.read_bytes()).decode('ascii'),
            }

    if raw_path in ('/api/review', '/api/lens/review') and method == 'POST':
        headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
        ct = headers.get('content-type', '')
        body_raw = event.get('body') or ''
        body_bytes = base64.b64decode(body_raw) if event.get('isBase64Encoded') else body_raw.encode('utf-8')

        text = ''
        conversation_history = '[]'
        file_obj = None

        if 'multipart/form-data' in ct:
            parsed_mp = _parse_multipart(body_bytes, ct)
            text = parsed_mp['fields'].get('text', '')
            conversation_history = parsed_mp['fields'].get('conversation_history', '[]')
            file_obj = parsed_mp['file']
        else:
            try:
                j = json.loads(body_bytes.decode('utf-8'))
                text = j.get('text', '')
                ch = j.get('conversation_history', [])
                conversation_history = ch if isinstance(ch, str) else json.dumps(ch)
            except Exception:
                pass

        try:
            history = json.loads(conversation_history or '[]')
        except Exception:
            history = []

        doc_meta = None
        file_name = ''
        combined_text = text or ''

        if file_obj:
            file_name = file_obj['filename']
            file_bytes = file_obj['bytes']
            pre_rej = file_validation.validate_file_pre_extract(file_name, file_bytes)
            if pre_rej:
                return _json_response(200, {
                    'type': 'chat',
                    'message': pre_rej['message'],
                    'rejected': True,
                    'rejection_details': pre_rej,
                    'document_metadata': {'filename': file_name, 'size_bytes': len(file_bytes)},
                })
            stored_name = f"{uuid.uuid4().hex[:8]}_{_sanitize_filename(file_name)}"

            try:
                (TMP_UPLOADS / stored_name).write_bytes(file_bytes)
                s3_client.put_object(Bucket=S3_BUCKET, Key=f'uploads/{stored_name}', Body=file_bytes)
            except Exception:
                pass

            extracted = document_service.extract_text(file_bytes, file_name)
            doc_meta = extracted.get('metadata', {})
            q = quote(stored_name)
            doc_meta['stored_name'] = stored_name
            doc_meta['url'] = f'/api/document/{q}'
            doc_meta['view_url'] = f'/api/document/{q}/view'

            user_text = (text or '').strip()
            post_rej = file_validation.validate_file_post_extract(file_name, file_bytes, extracted.get('text', ''), meta=doc_meta)
            if post_rej or doc_meta.get('is_empty', False) or len(file_bytes) == 0:
                msg = post_rej['message'] if post_rej else f"File Not Accepted: '{file_name}' is empty."
                return _json_response(200, {
                    'type': 'chat',
                    'message': msg,
                    'rejected': True,
                    'rejection_details': post_rej,
                    'document_metadata': doc_meta,
                })

            file_content = extracted.get('text', '')
            combined_text = (
                f"[ATTACHED DOCUMENT FOR REVIEW: {file_name}]\n"
                f"==================== DOCUMENT CONTENT ====================\n"
                f"{file_content}\n"
                f"==========================================================\n"
            )
            if user_text:
                combined_text += f"\nAuthor's Notes / Review Focus: {user_text}\n"

        if not combined_text.strip():
            return _json_response(400, {'detail': 'Please provide content or upload a document to review.'})

        try:
            result = lens_service.review_content(combined_text, file_name=file_name, conversation_history=history)
        except Exception as e:
            import traceback
            traceback.print_exc()
            result = {
                'type': 'chat',
                'message': "I'm ready to assist. Please share the content, draft, SOP, or contract you would like to audit for consistency and publish readiness.",
            }

        if doc_meta:
            result['document_metadata'] = doc_meta

        return _json_response(200, result)

    return _json_response(404, {'detail': f'Not found: {raw_path}'})

