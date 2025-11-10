


#!/usr/bin/env python3
"""
Simple Photo Database Admin Panel
Clean Flask application showing database statistics and file information
"""

import os
from database_config import get_db_config, get_db_connection, return_db_connection
import logging
logger = logging.getLogger(__name__)
# centralized logging initializer (Option B)
try:
    from utils.logging_setup import init_logging, redact_dict
except Exception:
    # init_logging/redact_dict may not be available during some tests; provide
    # a lightweight local fallback so callers can rely on init_logging()/redact_dict
    def init_logging(level=os.environ.get('LOG_LEVEL', 'INFO')):
        try:
            lvl = getattr(logging, level.upper()) if isinstance(level, str) else level
        except Exception:
            lvl = logging.INFO
        logging.basicConfig(level=lvl)

    def redact_dict(d, keys_to_redact=None):
        return d
# Ensure logging is configured as early as possible. Prefer the centralized
# init_logging from utils.logging_setup; fall back to basicConfig if it fails.
init_logging(level=os.environ.get('LOG_LEVEL', 'INFO'))
from storage_manager import get_storage
import io
import hashlib
import time
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
import re
from functools import wraps
import base64
import json
from typing import Optional, Tuple

# Simple admin token decorator: if ADMIN_TOKEN is set in the environment,
# require callers to provide it via the X-Admin-Token header or the
# form/json field `admin_token`. In development (FLASK_DEBUG=1) this check
# is relaxed to avoid blocking local testing when a token isn't configured.
def require_admin_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        admin_token = os.environ.get('ADMIN_TOKEN')
        debug = os.environ.get('FLASK_DEBUG', '0') == '1'
        # If user has a valid session flag, allow access
        if session.get('is_admin'):
            return fn(*args, **kwargs)

        if not admin_token:
            if debug:
                # Allow admin access in debug mode when no token is set
                return fn(*args, **kwargs)
            # If the client expects JSON (XHR/API) return JSON error; otherwise
            # redirect browser users to the admin login prompt so they can enter
            # a simple password to get a session cookie.
            accept = request.headers.get('Accept', '')
            is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            wants_json = 'application/json' in accept or is_xhr or request.is_json
            if wants_json:
                return jsonify({'error': 'admin token not configured'}), 403
            else:
                return redirect(url_for('admin_login', next=request.path))

        # Look for token in header, JSON body, or form field
        header = request.headers.get('X-Admin-Token')
        candidate = None
        if header:
            candidate = header
        else:
            try:
                if request.is_json:
                    candidate = request.json.get('admin_token')
            except Exception:
                candidate = None
            if not candidate:
                candidate = request.form.get('admin_token')

        if candidate and candidate == admin_token:
            # set session so browser users don't need to send header on every request
            try:
                session['is_admin'] = True
            except Exception:
                pass
            return fn(*args, **kwargs)
        # If request expects JSON return JSON error, otherwise redirect to login
        accept = request.headers.get('Accept', '')
        is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        wants_json = 'application/json' in accept or is_xhr or request.is_json
        if wants_json:
            return jsonify({'error': 'unauthorized'}), 401
        else:
            return redirect(url_for('admin_login', next=request.path))
    return wrapper








def _encode_cursor(effective_dt, pid: str) -> str:
    """Encode a cursor containing an ISO datetime and id into a URL-safe string."""
    try:
        payload = {'d': effective_dt.isoformat() if hasattr(effective_dt, 'isoformat') else str(effective_dt), 'id': pid}
        b = json.dumps(payload).encode('utf-8')
        return base64.urlsafe_b64encode(b).decode('ascii')
    except Exception:
        return ''


def _decode_cursor(cursor: str) -> Optional[Tuple[str, str]]:
    """Decode a cursor produced by _encode_cursor. Returns (date_iso, id) or None on failure."""
    try:
        b = base64.urlsafe_b64decode(cursor.encode('ascii'))
        payload = json.loads(b.decode('utf-8'))
        return payload.get('d'), payload.get('id')
    except Exception:
        return None

# Initialize Flask app
app = Flask(__name__)

# Load secret key from environment; require a real secret in production.
secret = os.environ.get('FLASK_SECRET') or os.environ.get('SECRET_KEY')
if secret:
    app.secret_key = secret
else:
    # Development fallback — printed so devs notice. Do NOT use in production.
    app.secret_key = 'dev-secret'
    logger.warning("Using insecure development Flask secret key. Set FLASK_SECRET in production.")

# Limit upload size. Default changed to allow much larger uploads while
# remaining configurable via the MAX_CONTENT_LENGTH environment variable.
# Value is in bytes. You can override this in production via env vars.
# Default chosen here: 200 MB to accommodate large image batches or high-
# resolution images. Set MAX_CONTENT_LENGTH in the environment to change it.
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 200 * 1024 * 1024))

# Global upload limits (number of files per request)
DEFAULT_MAX_UPLOAD_FILES = int(os.environ.get('MAX_UPLOAD_FILES', 50))


@app.context_processor
def inject_upload_limits():
    """Inject upload-related limits into all templates so client-side scripts
    can read them (e.g. to prevent selecting too many files).
    """
    try:
        max_bytes = app.config.get('MAX_CONTENT_LENGTH', 50 * 1024 * 1024)
        return {'max_upload_files': DEFAULT_MAX_UPLOAD_FILES, 'max_upload_bytes': max_bytes}
    except Exception:
        return {'max_upload_files': 50, 'max_upload_bytes': 50 * 1024 * 1024}

# Initialize CSRF protection if available. This is optional: if the
# environment doesn't have Flask-WTF installed, we warn and continue.
try:
    from flask_wtf import CSRFProtect
    csrf = CSRFProtect()
    csrf.init_app(app)
    logger.info('CSRF protection enabled via Flask-WTF')
except Exception:
    logger.warning('Flask-WTF (CSRFProtect) not available; admin forms will not have CSRF protection. Install flask-wtf to enable.')


# Simple admin login/logout routes (browser-friendly password prompt)
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    next_url = request.args.get('next') or request.form.get('next') or url_for('admin_functions')
    admin_token = os.environ.get('ADMIN_TOKEN')
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    if request.method == 'POST':
        password = request.form.get('password', '')
        if admin_token:
            if password == admin_token:
                session['is_admin'] = True
                flash('Signed in to admin.', 'success')
                return redirect(next_url)
            else:
                flash('Invalid password.', 'danger')
                return redirect(url_for('admin_login', next=next_url))
        else:
            if debug:
                session['is_admin'] = True
                flash('Signed in to admin (debug mode).', 'success')
                return redirect(next_url)
            # Admin token not set in production: present the login page (no flash)
            return redirect(url_for('admin_login', next=next_url))

    return render_template('admin_login.html', next=next_url)


@app.route('/admin/logout')
def admin_logout():
    try:
        session.pop('is_admin', None)
    except Exception:
        pass
    flash('Signed out of admin session.', 'info')
    return redirect(url_for('main_dashboard'))

@app.route('/upload', methods=['POST'])
def upload_photos():
    """Simple upload handler: store uploaded photos and generate thumbnails.

    This implementation is intentionally small and defensive so the app can start
    reliably. It uses the project's StorageManager to write files to disk and
    creates JPEG thumbnails using Pillow when possible.
    """
    files = request.files.getlist('photos')

    # Enforce a maximum number of files per upload to avoid overloading the
    # server (configured via MAX_UPLOAD_FILES env var or DEFAULT_MAX_UPLOAD_FILES).
    max_files = int(os.environ.get('MAX_UPLOAD_FILES', DEFAULT_MAX_UPLOAD_FILES))
    if files and len(files) > max_files:
        msg = f'Cannot upload more than {max_files} files at once. You selected {len(files)}.'
        logger.warning('Upload rejected: too many files selected (%d > %d)', len(files), max_files)
        if wants_json := ('application/json' in request.headers.get('Accept', '') or request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
            return jsonify({'success': False, 'message': msg, 'error': 'too_many_files', 'limit': max_files}), 413
        else:
            flash(msg, 'danger')
            return redirect(url_for('main_dashboard'))

    # Determine if the client expects JSON early so we can return a JSON
    # error instead of an HTML redirect when using the UI's import-path flow.
    accept = request.headers.get('Accept', '')
    wants_json = 'application/json' in accept or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # Support a server-side "import from path" flow: the client may send an
    # `import_path` field instead of uploading files directly. When provided
    # and confirmed, walk the given directory and build an in-memory file list
    # so the rest of the upload pipeline can proceed unchanged.
    import_path = request.form.get('import_path') or None
    import_confirmed = request.form.get('confirmed') == 'true'

    if not files and import_path:
        # If the client didn't confirm, respond with a clear JSON error when
        # the client expects JSON, otherwise redirect with a flash message.
        if not import_confirmed:
            if wants_json:
                return jsonify({'success': False, 'message': 'Server-side import not confirmed', 'error': 'confirm import by setting confirmed=true'}), 400
            else:
                flash('You must confirm server-side import before proceeding.', 'danger')
                return redirect(url_for('main_dashboard'))

        storage = get_storage()
        # Resolve the requested path to an absolute path and ensure it's
        # under the storage base path to avoid importing arbitrary system files.
        try:
            abs_req = os.path.abspath(import_path)
            base = os.path.abspath(storage.base_path)
            # Safety: require the requested path to be within storage.base_path
            if not os.path.commonpath([abs_req, base]) == base:
                if wants_json:
                    return jsonify({'success': False, 'message': 'Import path must be inside storage base path', 'error': 'import_path out of allowed base'}), 403
                else:
                    flash('Import path must be inside the storage base path.', 'danger')
                    return redirect(url_for('main_dashboard'))

            if not os.path.isdir(abs_req):
                if wants_json:
                    return jsonify({'success': False, 'message': 'Import path not found or not a directory', 'error': 'import_path not found'}), 404
                else:
                    flash('Import path not found or not a directory.', 'danger')
                    return redirect(url_for('main_dashboard'))

            # Build a small in-memory file-like list with .read() and .filename
            class _LocalFile:
                def __init__(self, data, filename):
                    self._data = data
                    self.filename = filename
                def read(self):
                    return self._data

            files = []
            for entry in sorted(os.listdir(abs_req)):
                fp = os.path.join(abs_req, entry)
                if os.path.isfile(fp):
                    try:
                        with open(fp, 'rb') as fh:
                            b = fh.read()
                        files.append(_LocalFile(b, entry))
                    except Exception:
                        logger.exception('Failed to read file during import: %s', fp)
                        # skip unreadable files
                        continue
        except Exception as e:
            logger.exception('Server-side import failed for path %s: %s', import_path, e)
            if wants_json:
                return jsonify({'success': False, 'message': 'Import failed', 'error': str(e)}), 500
            else:
                flash(f'Import failed: {e}', 'danger')
                return redirect(url_for('main_dashboard'))

    if not files:
        # No files provided via upload or import. Respect client's expectation
        # for JSON vs HTML when returning the error.
        if wants_json:
            return jsonify({'success': False, 'message': 'No files selected for upload', 'error': 'no_files'}), 400
        else:
            flash('No files selected for upload.', 'danger')
            return redirect(url_for('main_dashboard'))

    storage = get_storage()
    saved = 0
    results = []

    for file in files:
        raw_filename = file.filename or 'unnamed'
        # Keep the raw filename (it may include a relative path when the
        # client selected a directory). For display and DB fields, use a
        # sanitized basename, but pass the original relative path to
        # storage so subdirectory structure can be preserved.
        try:
            display_basename = secure_filename(os.path.basename(raw_filename)) or 'unnamed'
        except Exception:
            display_basename = 'unnamed'
        # Keep a compatible name used throughout the function
        safe_filename = display_basename
        try:
            data = file.read()

            # If a single uploaded file exceeds the configured per-file limit,
            # save it to a review directory (processed/too_large) for manual
            # inspection instead of attempting normal processing which may
            # fail or consume excessive resources. This avoids losing the
            # file while keeping the upload flow robust.
            per_file_limit = int(os.environ.get('MAX_FILE_SIZE_BYTES', app.config.get('MAX_CONTENT_LENGTH', 12 * 1024 * 1024)))
            if data and len(data) > per_file_limit:
                try:
                    storage = get_storage()
                    rel_review = storage.store_review_file(data, raw_filename)
                    results.append({
                        'filename': safe_filename,
                        'success': True,
                        'message': 'Saved for manual review: file too large',
                        'photo_id': None,
                        'local_path': rel_review,
                        'too_large': True
                    })
                    # Skip normal processing for this file
                    continue
                except Exception as e:
                    logger.exception("Failed to save too-large file for review %s: %s", raw_filename, e)
                    results.append({'filename': safe_filename, 'success': False, 'message': f'Failed to save too-large file: {e}', 'photo_id': None, 'local_path': None})
                    continue

            # Pre-compute hash so we can check duplicates before writing files
            photo_id = hashlib.sha256(data).hexdigest()

            # Compute a normalized image hash (content-based) to detect
            # duplicates that differ only by metadata or minor re-encoding.
            def compute_normalized_hash(img_bytes):
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(img_bytes))
                    # Normalize: convert to RGB, resize to fixed size, remove
                    # metadata by using raw pixel data
                    im = im.convert('RGB')
                    im = im.resize((256, 256), resample=Image.Resampling.LANCZOS)
                    return hashlib.sha256(im.tobytes()).hexdigest()
                except Exception:
                    return None

            normalized_hash = compute_normalized_hash(data)

            # Check DB for duplicate first — reuse a single DB connection for both
            # exact-id and content_hash lookups to avoid consuming multiple
            # mocked connections in tests and to be more efficient.
            is_duplicate = False
            duplicate_type = None
            conn_for_checks = None
            try:
                db_cfg = get_db_config()
                conn_for_checks = get_db_connection()
                if conn_for_checks:
                    try:
                        if db_cfg.get_database_type() == 'postgres':
                            from psycopg2.extras import RealDictCursor
                            cur = conn_for_checks.cursor(cursor_factory=RealDictCursor)
                            cur.execute('SELECT local_path FROM photos WHERE id = %s', (photo_id,))
                            row = cur.fetchone()
                            if row:
                                is_duplicate = True
                                duplicate_type = 'exact'
                                existing_local_path = row.get('local_path') if isinstance(row, dict) else (row[0] if row and len(row) > 0 else None)
                        else:
                            cur = conn_for_checks.cursor()
                            cur.execute('SELECT local_path FROM photos WHERE id = ?', (photo_id,))
                            row = cur.fetchone()
                            if row:
                                is_duplicate = True
                                duplicate_type = 'exact'
                                existing_local_path = row[0] if len(row) > 0 else None
                    except Exception:
                        logger.exception("Duplicate id check failed for %s", raw_filename)
            except Exception as e:
                logger.exception("Duplicate check setup failed for %s: %s", raw_filename, e)

            if is_duplicate:
                # Verify that the reported local_path actually exists on disk. Some
                # test doubles/mock setups return a path-like value; prefer to
                # treat as duplicate only when the file exists to avoid false
                # positives.
                try:
                    storage = get_storage()
                    exists_on_disk = False
                    if existing_local_path:
                        try:
                            # If the DB returned an absolute path, check it directly
                            if os.path.isabs(existing_local_path):
                                exists_on_disk = os.path.exists(existing_local_path)
                            else:
                                # Treat as relative to storage.base_path
                                abs_path = storage.get_photo_path(existing_local_path)
                                exists_on_disk = os.path.exists(abs_path)
                        except Exception:
                            exists_on_disk = False
                    if not exists_on_disk:
                        # Treat as not-duplicate if the file isn't present
                        is_duplicate = False
                        duplicate_type = None
                        existing_local_path = None
                    else:
                        # Don't write duplicate files to disk; report as informational duplicate
                        db_result = {
                            'filename': safe_filename,
                            'success': True,
                            'message': 'Photo already exists (duplicate)',
                            'photo_id': photo_id,
                            'local_path': existing_local_path,
                            'duplicate_type': duplicate_type,
                            'duplicate': True
                        }
                except Exception:
                    # If anything goes wrong during existence check, err on the
                    # side of allowing the upload to proceed.
                    is_duplicate = False
                    duplicate_type = None
                    existing_local_path = None
                # Return the connection now that we're done with checks
                try:
                    if conn_for_checks:
                        return_db_connection(conn_for_checks)
                except Exception:
                    pass
                if is_duplicate:
                    results.append(db_result)
                    continue

            # If normalized hashing succeeded, try a content-based duplicate check
            if normalized_hash:
                # Prefer querying the database for existing content_hash. Reuse
                # the earlier `conn_for_checks` connection when available so we
                # don't open multiple connections during a single upload.
                try:
                    db_cfg = get_db_config()
                    found = None
                    used_conn = conn_for_checks
                    conn_ch = None
                    try:
                        if used_conn is None:
                            # Fall back to opening a separate connection if needed
                            conn_ch = get_db_connection()
                            used_conn = conn_ch

                        if used_conn:
                            try:
                                if db_cfg.get_database_type() == 'postgres':
                                    from psycopg2.extras import RealDictCursor
                                    cur_ch = used_conn.cursor(cursor_factory=RealDictCursor)
                                    cur_ch.execute('SELECT local_path FROM photos WHERE content_hash = %s LIMIT 1', (normalized_hash,))
                                    row_ch = cur_ch.fetchone()
                                    if row_ch:
                                        found = row_ch.get('local_path') if isinstance(row_ch, dict) else (row_ch[0] if row_ch and len(row_ch) > 0 else None)
                                else:
                                    cur_ch = used_conn.cursor()
                                    cur_ch.execute('SELECT local_path FROM photos WHERE content_hash = ? LIMIT 1', (normalized_hash,))
                                    row_ch = cur_ch.fetchone()
                                    if row_ch:
                                        found = row_ch[0] if len(row_ch) > 0 else None
                            except Exception:
                                # DB content-hash lookup failed; set found to None
                                found = None
                    finally:
                        # If we opened a separate connection for this check, return it
                        if conn_ch:
                            try:
                                return_db_connection(conn_ch)
                            except Exception:
                                pass

                    if found:
                        is_duplicate = True
                        duplicate_type = 'content'
                        existing_local_path = found
                        db_result = {
                            'filename': safe_filename,
                            'success': True,
                            'message': 'Photo appears to be a duplicate (content match)',
                            'photo_id': photo_id,
                            'local_path': existing_local_path,
                            'duplicate_type': duplicate_type,
                            'duplicate': True
                        }
                        # If we have a shared connection, return it now
                        try:
                            if conn_for_checks and used_conn is conn_for_checks:
                                return_db_connection(conn_for_checks)
                        except Exception:
                            pass
                        results.append(db_result)
                        continue

                except Exception:
                    # If DB check fails entirely, fall back to scanning files on disk
                    try:
                        # Build a quick cache of normalized hashes for existing originals
                        if not hasattr(upload_photos, '_normalized_cache'):
                            upload_photos._normalized_cache = {}
                            storage_scan_root = storage.originals_path
                            for dirpath, dirnames, filenames in os.walk(storage_scan_root):
                                for fn in filenames:
                                    try:
                                        fp = os.path.join(dirpath, fn)
                                        with open(fp, 'rb') as f:
                                            b = f.read()
                                        h = compute_normalized_hash(b)
                                        if h:
                                            upload_photos._normalized_cache[h] = os.path.relpath(fp, storage.base_path)
                                    except Exception:
                                        pass

                        if normalized_hash in upload_photos._normalized_cache:
                            is_duplicate = True
                            duplicate_type = 'content'
                            existing_local_path = upload_photos._normalized_cache.get(normalized_hash)
                            db_result = {
                                'filename': safe_filename,
                                'success': True,
                                'message': 'Photo appears to be a duplicate (content match)',
                                'photo_id': photo_id,
                                'local_path': existing_local_path,
                                'duplicate_type': duplicate_type,
                                'duplicate': True
                            }
                            results.append(db_result)
                            continue
                    except Exception:
                        # If content-based fallback fails, don't block the upload
                        pass

            # Ensure any temporary DB connections used for duplicate checks are returned
            try:
                if conn_for_checks:
                    try:
                        return_db_connection(conn_for_checks)
                    except Exception:
                        pass
                    conn_for_checks = None
            except Exception:
                pass

            # Try to extract taken date and image object
            taken_date = None
            img = None
            image_width = None
            image_height = None
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(data))
                image_width, image_height = img.size
                exif = img.getexif()
                if exif:
                    for tag in (36867, 306, 36868):
                        if tag in exif:
                            raw = exif.get(tag)
                            if isinstance(raw, str):
                                try:
                                    taken_date = datetime.strptime(raw, '%Y:%m:%d %H:%M:%S')
                                except Exception:
                                    taken_date = None
                            break
            except Exception:
                img = None

            # If EXIF didn't provide a taken date, attempt to parse it from the
            # filename using common camera naming conventions like
            # YYYYMMDD, YYYY-MM-DD, YYYY_MM_DD, YYYYMMDD_HHMMSS, IMG_YYYYMMDD_HHMMSS, etc.
            def _parse_date_from_filename(name):
                try:
                    # Common regex patterns to try in order
                    patterns = [
                        # 20231103T121212 or 20231103121212
                        r'(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})(?P<H>\d{2})(?P<M>\d{2})(?P<S>\d{2})',
                        # 2023-11-03 12:12:12 or 2023.11.03-12.12.12 or 2023_11_03-12_12_12
                        r'(?P<y>\d{4})[-_.](?P<m>\d{2})[-_.](?P<d>\d{2})[T_\- ](?P<H>\d{2})[:._-](?P<M>\d{2})[:._-](?P<S>\d{2})',
                        # 2023-11-03 or 2023_11_03 or 2023.11.03
                        r'(?P<y>\d{4})[-_.](?P<m>\d{2})[-_.](?P<d>\d{2})',
                        # contiguous YYYYMMDD
                        r'(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})'
                    ]

                    for pat in patterns:
                        m = re.search(pat, name)
                        if m:
                            gd = m.groupdict()
                            y = int(gd.get('y'))
                            mo = int(gd.get('m'))
                            d = int(gd.get('d'))
                            H = int(gd.get('H')) if gd.get('H') else 0
                            Mi = int(gd.get('M')) if gd.get('M') else 0
                            S = int(gd.get('S')) if gd.get('S') else 0
                            try:
                                return datetime(y, mo, d, H, Mi, S)
                            except Exception:
                                continue
                except Exception:
                    return None
                return None

            if taken_date is None:
                try:
                    parsed = _parse_date_from_filename(safe_filename)
                    if parsed:
                        taken_date = parsed
                except Exception:
                    pass

            # Store original photo on disk (use sanitized filename)
            try:
                # Pass the raw filename (which may contain subdirs) to storage
                # so it can create subdirectories under the date folder. Use
                # display_basename for logs/messages.
                rel_path = storage.store_photo(data, raw_filename, taken_date=taken_date)
            except Exception as e:
                logger.exception("Failed to store photo %s: %s", raw_filename, e)
                db_result = {'filename': raw_filename, 'success': False, 'message': f'Failed to store: {e}', 'photo_id': photo_id, 'local_path': None}
                results.append(db_result)
                continue

            # Create thumbnail bytes (best-effort)
            thumb_bytes = None
            thumb_created = False
            try:
                if img:
                    from PIL import Image
                    try:
                        # Apply EXIF orientation so thumbnails have correct rotation
                        from PIL import ImageOps
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        # If Pillow/ImageOps isn't available or exif_transpose fails,
                        # continue without changing orientation.
                        pass
                    thumb = img.copy()
                    thumb.thumbnail((300, 300))
                    # Convert images with alpha/transparency to RGB with white
                    # background before saving as JPEG. This avoids the
                    # "cannot write mode RGBA as JPEG" OSError for images with
                    # alpha channels.
                    try:
                        info = getattr(thumb, 'info', {}) or {}
                        if thumb.mode in ('RGBA', 'LA') or (thumb.mode == 'P' and 'transparency' in info):
                            background = Image.new('RGB', thumb.size, (255, 255, 255))
                            try:
                                alpha = thumb.split()[-1]
                                background.paste(thumb, mask=alpha)
                                thumb = background
                            except Exception:
                                # Fallback to a direct conversion if pasting fails
                                thumb = thumb.convert('RGB')
                        else:
                            thumb = thumb.convert('RGB')
                    except Exception:
                        # If anything goes wrong with conversion, ensure we
                        # at least have an RGB image for JPEG saving.
                        try:
                            thumb = thumb.convert('RGB')
                        except Exception:
                            pass

                    buf = io.BytesIO()
                    thumb.save(buf, format='JPEG', quality=85)
                    thumb_bytes = buf.getvalue()
                    # persist thumbnail to disk as well using precomputed photo_id
                    storage.store_thumbnail(thumb_bytes, photo_id, taken_date=taken_date)
                    thumb_created = True
            except Exception as e:
                # Diagnostic logging: capture image properties and save raw bytes
                try:
                    img_info = {}
                    if 'img' in locals() and img is not None:
                        try:
                            img_info['format'] = getattr(img, 'format', None)
                            img_info['mode'] = getattr(img, 'mode', None)
                            img_info['size'] = getattr(img, 'size', None)
                            img_info['info_keys'] = list(getattr(img, 'info', {}).keys())
                            try:
                                exif = img.getexif()
                                img_info['exif_tags'] = list(exif.keys())[:10] if exif else None
                            except Exception:
                                img_info['exif_tags'] = 'exif-read-failed'
                        except Exception as ie:
                            img_info['read_error'] = str(ie)
                    else:
                        img_info['img'] = 'not available'

                    logger.error("Thumbnail generation failed for %s: %s; image_info=%s", raw_filename, e, img_info)

                    # Save raw bytes to a diagnostics file for offline inspection
                    try:
                        diag_dir = os.path.join(storage.processed_path, 'diagnostics')
                        os.makedirs(diag_dir, exist_ok=True)
                        # Use photo_id and safe filename to avoid collisions
                        ext = os.path.splitext(safe_filename)[1] or '.bin'
                        diag_name = f"{photo_id}{ext}"
                        diag_path = os.path.join(diag_dir, diag_name)
                        with open(diag_path, 'wb') as df:
                            df.write(data)
                        logger.info("Wrote diagnostic image bytes to %s", diag_path)
                    except Exception as de:
                        logger.exception("Failed to write diagnostic file for %s: %s", raw_filename, de)
                except Exception:
                    logger.exception("Unexpected error while diagnosing thumbnail failure for %s", raw_filename)
            # Record successful store for this file
            try:
                # Insert a record into the photos table so the gallery can show it
                try:
                    db_cfg = get_db_config()
                    conn_ins = get_db_connection()
                    if conn_ins:
                        try:
                            if db_cfg.get_database_type() == 'postgres':
                                cur_ins = conn_ins.cursor()
                                # Use psycopg2 Binary for thumbnail bytes when present
                                try:
                                    from psycopg2 import Binary as _PgBinary
                                    thumb_val = _PgBinary(thumb_bytes) if thumb_bytes else None
                                except Exception:
                                    thumb_val = thumb_bytes
                                q = ("INSERT INTO photos (id, original_filename, local_path, file_path, file_size, content_hash, "
                                     "upload_timestamp, photo_taken_date, image_width, image_height, thumbnail) "
                                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
                                params = (
                                    photo_id, safe_filename, rel_path, rel_path, len(data) if data else None,
                                    normalized_hash, datetime.now(timezone.utc), taken_date, image_width, image_height, thumb_val
                                )
                                cur_ins.execute(q, params)
                                conn_ins.commit()
                            else:
                                cur_ins = conn_ins.cursor()
                                q = ("INSERT OR REPLACE INTO photos (id, original_filename, local_path, file_path, file_size, content_hash, "
                                     "upload_timestamp, photo_taken_date, image_width, image_height, thumbnail) "
                                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
                                params = (
                                    photo_id, safe_filename, rel_path, rel_path, len(data) if data else None,
                                    normalized_hash, datetime.now(timezone.utc).isoformat(), taken_date.isoformat() if taken_date else None,
                                    image_width, image_height, thumb_bytes
                                )
                                cur_ins.execute(q, params)
                                conn_ins.commit()
                        except Exception:
                            logger.exception("Failed to insert photo record for %s", safe_filename)
                        finally:
                            try:
                                if conn_ins:
                                    return_db_connection(conn_ins)
                            except Exception:
                                pass
                except Exception:
                    logger.exception("Unexpected error during DB insert for %s", safe_filename)

                saved += 1
                results.append({
                    'filename': safe_filename,
                    'success': True,
                    'message': 'Stored',
                    'photo_id': photo_id,
                    'local_path': rel_path,
                    'thumbnail_created': thumb_created
                })
            except Exception:
                # Best-effort: avoid letting result construction crash the upload loop
                results.append({'filename': safe_filename or 'unnamed', 'success': True, 'message': 'Stored', 'photo_id': photo_id, 'local_path': rel_path, 'thumbnail_created': thumb_created})
        except Exception as e:
            logger.exception("Error processing upload %s: %s", raw_filename, e)
            # Record failure for this file so client gets structured feedback
            try:
                results.append({'filename': secure_filename(raw_filename) or 'unnamed', 'success': False, 'message': str(e), 'photo_id': None, 'local_path': None})
            except Exception:
                # Best-effort; avoid raising from the exception handler
                results.append({'filename': 'unnamed', 'success': False, 'message': 'Unknown error', 'photo_id': None, 'local_path': None})

    # If client expects JSON (fetch/ajax), return JSON summary; otherwise flash and redirect
    accept = request.headers.get('Accept', '')
    wants_json = 'application/json' in accept or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # Compute duplicates count from results
    duplicates = sum(1 for r in results if r.get('message') and 'duplicate' in r.get('message').lower())
    summary = {'inserted': saved, 'submitted': len(files), 'duplicates': duplicates}

    if wants_json:
        # Compatibility: ensure older clients that expect `error` or
        # top-level `message` still receive useful fields. For each result,
        # copy `message` into `error` when a failure occurred. Also expose
        # a top-level `message` when the overall response is not successful.
        try:
            for r in results:
                # Copy message to error for older clients if this is a true failure
                if not r.get('success') and 'error' not in r and 'message' in r:
                    r['error'] = r['message']
        except Exception:
            pass

        # Consider duplicates informational: only treat non-duplicate failures as errors
        hard_failures = sum(1 for r in results if not r.get('success') and not r.get('duplicate'))

        top_message = None
        if hard_failures > 0 and results:
            # Prefer the first hard failure message as a top-level message
            for r in results:
                if not r.get('success') and not r.get('duplicate') and r.get('message'):
                    top_message = r.get('message')
                    break

        overall_success = (hard_failures == 0) and (saved > 0 or summary.get('duplicates', 0) > 0)

        payload = {'success': overall_success, 'summary': summary, 'results': results}
        if top_message:
            payload['message'] = top_message
        return jsonify(payload)
    else:
        flash(f'Saved {saved} file(s).', 'success')
        return redirect(url_for('main_dashboard'))

# S3 integration removed — this function intentionally omitted.

@app.route('/')
def main_dashboard():
    """Main page for photo uploads and a small dashboard.

    This produces a minimal `stats` dictionary used by the templates so the
    app can start even if richer database helpers are missing.
    """
    storage = get_storage()

    # Gather storage paths and sizes
    storage_paths = {
        'base': storage.base_path,
        'originals': storage.originals_path,
        'thumbnails': storage.thumbnails_path,
        'processed': storage.processed_path
    }
    # Prefer counting photos from the database (unique records). Fall back to
    # scanning the originals folder if the DB query fails for any reason.
    total_photos = 0
    total_bytes = 0
    try:
        db_cfg = get_db_config()
        conn = get_db_connection()
        if conn:
            try:
                if db_cfg.get_database_type() == 'postgres':
                    from psycopg2.extras import RealDictCursor
                    cur = conn.cursor(cursor_factory=RealDictCursor)
                    cur.execute('SELECT COUNT(*) AS cnt, COALESCE(SUM(file_size), 0) AS total_bytes FROM photos')
                    row = cur.fetchone()
                    total_photos = int(row['cnt'] or 0)
                    total_bytes = int(row['total_bytes'] or 0)
                else:
                    cur = conn.cursor()
                    # SQLite: COALESCE works here as well
                    cur.execute('SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM photos')
                    row = cur.fetchone()
                    total_photos = int(row[0] or 0)
                    total_bytes = int(row[1] or 0)
            except Exception as e:
                logger.exception("DB stats query failed in main_dashboard(): %s", e)
            finally:
                try:
                    if conn:
                        return_db_connection(conn)
                except Exception:
                    pass
    except Exception as e:
        logger.exception("Error getting DB stats in main_dashboard(): %s", e)

    # Fallback to filesystem scan if DB did not yield values
    if not total_photos:
        def _get_dir_size_and_count(path):
            total = 0
            count = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.isfile(fp):
                        try:
                            total += os.path.getsize(fp)
                            count += 1
                        except Exception:
                            pass
            return total, count

        total_bytes, total_photos = _get_dir_size_and_count(storage.originals_path)

    total_size_gb = round(total_bytes / (1024.0 ** 3), 2)
    avg_size_mb = round((total_bytes / total_photos) / (1024.0 ** 2), 2) if total_photos else 0

    stats = {
        'total_photos': total_photos,
        'total_size_gb': total_size_gb,
        'avg_size_mb': avg_size_mb
    }

    return render_template('index.html', stats=stats, storage_paths=storage_paths)

@app.route('/admin')
@require_admin_token
def admin_functions():
    """Separate admin page for admin functions"""
    
    # Calculate database file size (for SQLite)
    db_size = None
    db_config = get_db_config()
    db_info = db_config.get_database_info()
    # Redact any sensitive keys before logging
    try:
        redacted = dict(db_info)
        cfg = redacted.get('config', {}) or {}
        if isinstance(cfg, dict) and 'password' in cfg:
            cfg = dict(cfg)
            cfg['password'] = 'REDACTED'
            redacted['config'] = cfg
        logger.debug("admin db_info: %s", redacted)
    except Exception:
        logger.debug("admin db_info: (failed to redact)")
    if db_config.get_database_type() == 'local':
        db_path = db_info.get('config', {}).get('path')
        logger.debug("admin db_path: %s", db_path)
        if db_path and os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
    # Calculate storage size
    storage = get_storage()
    def get_dir_size(path):
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
        return total
    storage_size = get_dir_size(storage.base_path)
    return render_template('admin_functions.html', db_size=db_size, storage_size=storage_size, db_info=db_info)


@app.route('/gallery')
def gallery():
    """Gallery view: list photos from the database (or fallback to stored files).

    Supports optional year/month filtering and simple pagination.
    """
    db_config = get_db_config()
    conn = get_db_connection()
    page = request.args.get('page', default=1, type=int)
    per_page = 24
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)

    photos = []
    available_periods = []
    selected_period = None
    pagination = {
        'total': 0,
        'page': page,
        'per_page': per_page,
        'total_pages': 0,
        'has_prev': False,
        'has_next': False,
        'prev_num': None,
        'next_num': None
    }

    # Ensure these are defined for both keyset and offset pagination flows
    next_cursor = None
    total = 0

    try:
        if db_config.get_database_type() == 'postgres':
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            # available periods
            cursor.execute("""
                SELECT EXTRACT(YEAR FROM photo_taken_date) AS year,
                       EXTRACT(MONTH FROM photo_taken_date) AS month,
                       COUNT(*) AS photo_count
                FROM photos
                WHERE photo_taken_date IS NOT NULL
                GROUP BY year, month
                ORDER BY year DESC, month DESC
            """)
            for row in cursor.fetchall():
                yr = int(row['year'])
                mo = int(row['month'])
                available_periods.append({
                    'year': yr,
                    'month': mo,
                    'display_name': f"{yr}-{str(mo).zfill(2)}",
                    'photo_count': row['photo_count']
                })

            # build photos query
            where = []
            params = []
            if year and month:
                # Filter by the effective date (taken date, or upload timestamp)
                where.append("EXTRACT(YEAR FROM COALESCE(photo_taken_date, upload_timestamp)) = %s AND EXTRACT(MONTH FROM COALESCE(photo_taken_date, upload_timestamp)) = %s")
                params.extend([year, month])
                try:
                    selected_period = {'year': year, 'month': month, 'month_name': datetime(int(year), int(month), 1).strftime('%B')}
                except Exception:
                    selected_period = {'year': year, 'month': month, 'month_name': None}
            # Support keyset pagination via ?cursor=<base64> and preserve
            # offset pagination (page) for backwards compatibility.
            cursor_param = request.args.get('cursor')
            if cursor_param:
                # Keyset pagination: fetch per_page+1 rows to detect next cursor
                where_clause = 'WHERE ' + ' AND '.join(where) if where else ''

                # Build keyset condition
                decoded = _decode_cursor(cursor_param)
                keyset_cond = ""
                params_keyset = list(params)
                if decoded:
                    cur_date, cur_id = decoded
                    # Use COALESCE(photo_taken_date, upload_timestamp) as effective date
                    keyset_cond = "(COALESCE(photo_taken_date, upload_timestamp) < %s OR (COALESCE(photo_taken_date, upload_timestamp) = %s AND id < %s))"
                    # For Postgres, pass the ISO string / timestamp; driver will parse
                    params_keyset.extend([cur_date, cur_date, cur_id])
                else:
                    # If decode failed, treat as no cursor (fallback to newest)
                    keyset_cond = None

                if keyset_cond:
                    if where_clause:
                        full_where = where_clause + ' AND ' + keyset_cond
                    else:
                        full_where = 'WHERE ' + keyset_cond
                else:
                    full_where = where_clause

                q = ("SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp, "
                     "COALESCE(photo_taken_date, upload_timestamp) AS effective_date "
                     f"FROM photos {full_where} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC, id DESC LIMIT %s")
                params_keyset.append(per_page + 1)
                cursor.execute(q, params_keyset)
                rows = cursor.fetchall()
                # Determine next cursor
                next_cursor = None
                if rows and len(rows) > per_page:
                    # There is another page; take the last row of the returned page
                    page_rows = rows[:per_page]
                    last = page_rows[-1]
                    eff = last.get('effective_date')
                    last_id = last.get('id')
                    next_cursor = _encode_cursor(eff, last_id)
                    rows = page_rows
                else:
                    next_cursor = None
            else:
                where_clause = 'WHERE ' + ' AND '.join(where) if where else ''
                count_q = f"SELECT COUNT(*) FROM photos {where_clause}"
                cursor.execute(count_q, params)
                # cursor.fetchone() may return a mapping (RealDictCursor) or a tuple.
                row = cursor.fetchone()
                if not row:
                    total = 0
                elif isinstance(row, dict):
                    # take the first column value regardless of its name
                    try:
                        total = int(next(iter(row.values())) or 0)
                    except Exception:
                        total = 0
                else:
                    total = int(row[0] or 0)

                offset = (page - 1) * per_page
                q = f"SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp FROM photos {where_clause} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC LIMIT %s OFFSET %s"
                cursor.execute(q, params + [per_page, offset])
                rows = cursor.fetchall()
                # If there are more rows than one page and this is the first
                # page, compute a keyset `next_cursor` so clients can opt-in to
                # cursor-based navigation without providing a cursor.
                if page == 1 and total > per_page:
                    try:
                        q2 = ("SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp, "
                              "COALESCE(photo_taken_date, upload_timestamp) AS effective_date "
                              f"FROM photos {where_clause} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC, id DESC LIMIT %s")
                        cursor.execute(q2, params + [per_page + 1])
                        rows2 = cursor.fetchall()
                        if rows2 and len(rows2) > per_page:
                            last = rows2[per_page - 1]
                            # RealDictCursor returns mapping
                            eff = last.get('effective_date') if isinstance(last, dict) else None
                            last_id = last.get('id') if isinstance(last, dict) else (last[0] if len(last) > 0 else None)
                            if eff and last_id:
                                next_cursor = _encode_cursor(eff, last_id)
                    except Exception:
                        # Non-fatal: leave next_cursor as None
                        pass

        else:
            cursor = conn.cursor()
            # available periods (SQLite)
            # Use COALESCE(photo_taken_date, upload_timestamp) so photos without
            # EXIF taken date are grouped by their upload timestamp instead.
            cursor.execute("""
                SELECT strftime('%Y', COALESCE(photo_taken_date, upload_timestamp)) AS year,
                       strftime('%m', COALESCE(photo_taken_date, upload_timestamp)) AS month,
                       COUNT(*) AS photo_count
                FROM photos
                WHERE COALESCE(photo_taken_date, upload_timestamp) IS NOT NULL
                GROUP BY year, month
                ORDER BY year DESC, month DESC
            """)
            for row in cursor.fetchall():
                if row[0]:
                    yr = int(row[0])
                    mo = int(row[1])
                    available_periods.append({
                        'year': yr,
                        'month': mo,
                        'display_name': f"{yr}-{str(mo).zfill(2)}",
                        'photo_count': row[2]
                    })

            where = []
            params = []
            if year and month:
                # Filter by the effective date (taken date, or upload timestamp)
                where.append("strftime('%Y', COALESCE(photo_taken_date, upload_timestamp)) = ? AND strftime('%m', COALESCE(photo_taken_date, upload_timestamp)) = ?")
                params.extend([str(year).zfill(4), str(month).zfill(2)])
                try:
                    selected_period = {'year': year, 'month': month, 'month_name': datetime(year, month, 1).strftime('%B')}
                except Exception:
                    selected_period = {'year': year, 'month': month, 'month_name': None}

            # Support keyset pagination (cursor) while keeping offset pagination
            cursor_param = request.args.get('cursor')
            if cursor_param:
                where_clause = 'WHERE ' + ' AND '.join(where) if where else ''
                decoded = _decode_cursor(cursor_param)
                params_keyset = list(params)
                if decoded:
                    cur_date, cur_id = decoded
                    keyset_cond = "(COALESCE(photo_taken_date, upload_timestamp) < ? OR (COALESCE(photo_taken_date, upload_timestamp) = ? AND id < ?))"
                    params_keyset.extend([cur_date, cur_date, cur_id])
                else:
                    keyset_cond = None

                if keyset_cond:
                    if where_clause:
                        full_where = where_clause + ' AND ' + keyset_cond
                    else:
                        full_where = 'WHERE ' + keyset_cond
                else:
                    full_where = where_clause

                q = ("SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp, "
                     "COALESCE(photo_taken_date, upload_timestamp) AS effective_date "
                     f"FROM photos {full_where} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC, id DESC LIMIT ?")
                params_keyset.append(per_page + 1)
                cursor.execute(q, params_keyset)
                rows = cursor.fetchall()
                next_cursor = None
                if rows and len(rows) > per_page:
                    page_rows = rows[:per_page]
                    last = page_rows[-1]
                    # sqlite row is a tuple
                    eff = last[6] if len(last) > 6 else None
                    last_id = last[0]
                    next_cursor = _encode_cursor(eff, last_id)
                    rows = page_rows
                else:
                    next_cursor = None
            else:
                where_clause = 'WHERE ' + ' AND '.join(where) if where else ''
                count_q = f"SELECT COUNT(*) FROM photos {where_clause}"
                cursor.execute(count_q, params)
                row = cursor.fetchone()
                if not row:
                    total = 0
                elif isinstance(row, dict):
                    try:
                        total = int(next(iter(row.values())) or 0)
                    except Exception:
                        total = 0
                else:
                    total = int(row[0] or 0)

                offset = (page - 1) * per_page
                q = f"SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp FROM photos {where_clause} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC LIMIT ? OFFSET ?"
                cursor.execute(q, params + [per_page, offset])
                rows = cursor.fetchall()
                # Compute keyset next_cursor for first page when more rows exist
                if page == 1 and total > per_page:
                    try:
                        q2 = ("SELECT id, original_filename, photo_taken_date, image_width, image_height, upload_timestamp, "
                              "COALESCE(photo_taken_date, upload_timestamp) AS effective_date "
                              f"FROM photos {where_clause} ORDER BY COALESCE(photo_taken_date, upload_timestamp) DESC, id DESC LIMIT ?")
                        cursor.execute(q2, params + [per_page + 1])
                        rows2 = cursor.fetchall()
                        if rows2 and len(rows2) > per_page:
                            last = rows2[per_page - 1]
                            eff = last[6] if len(last) > 6 else None
                            last_id = last[0]
                            if eff and last_id:
                                next_cursor = _encode_cursor(eff, last_id)
                    except Exception:
                        pass

        # Normalize rows into photo dicts
        for r in rows:
            if db_config.get_database_type() == 'postgres':
                pid = r['id']
                original_filename = r['original_filename']
                ptd = r['photo_taken_date']
                upload_ts = r['upload_timestamp']
                width = r.get('image_width')
                height = r.get('image_height')
            else:
                pid = r[0]
                original_filename = r[1]
                ptd = r[2]
                width = r[3]
                height = r[4]
                upload_ts = r[5] if len(r) > 5 else None

            # Convert date strings to datetime when possible
            try:
                if isinstance(ptd, str):
                    ptd_val = datetime.fromisoformat(ptd)
                else:
                    ptd_val = ptd
            except Exception:
                ptd_val = None

            try:
                if isinstance(upload_ts, str):
                    upload_val = datetime.fromisoformat(upload_ts)
                else:
                    upload_val = upload_ts
            except Exception:
                upload_val = None

            photos.append({
                'id': pid,
                'original_filename': original_filename,
                'photo_taken_date': ptd_val,
                'upload_timestamp': upload_val,
                'image_width': width,
                'image_height': height
            })

        # Pagination metadata
        if next_cursor is not None:
            # Keyset pagination: total pages are unknown; expose next_cursor for the client
            pagination['total'] = None
            pagination['total_pages'] = None
            pagination['has_prev'] = page > 1
            pagination['has_next'] = True if next_cursor else False
            pagination['prev_num'] = None
            pagination['next_num'] = None
            pagination['next_cursor'] = next_cursor
        else:
            pagination['total'] = total
            pagination['total_pages'] = max(1, (total + per_page - 1) // per_page)
            pagination['has_prev'] = page > 1
            pagination['has_next'] = page < pagination['total_pages']
            pagination['prev_num'] = page - 1 if pagination['has_prev'] else None
            pagination['next_num'] = page + 1 if pagination['has_next'] else None

    except Exception as e:
        logger.exception("Error loading gallery: %s", e)
    finally:
        if conn:
            return_db_connection(conn)

    # Compute simple stats from the database (unique photo records). Fall
    # back to filesystem scanning if DB is not available.
    total_photos = 0
    total_bytes = 0
    try:
        db_cfg = get_db_config()
        conn_stats = get_db_connection()
        if conn_stats:
            try:
                if db_cfg.get_database_type() == 'postgres':
                    from psycopg2.extras import RealDictCursor
                    cur = conn_stats.cursor(cursor_factory=RealDictCursor)
                    cur.execute('SELECT COUNT(*) AS cnt, COALESCE(SUM(file_size), 0) AS total_bytes FROM photos')
                    row = cur.fetchone()
                    total_photos = int(row['cnt'] or 0)
                    total_bytes = int(row['total_bytes'] or 0)
                else:
                    cur = conn_stats.cursor()
                    cur.execute('SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM photos')
                    row = cur.fetchone()
                    total_photos = int(row[0] or 0)
                    total_bytes = int(row[1] or 0)
            except Exception as e:
                logger.exception("DB stats query failed in gallery(): %s", e)
            finally:
                try:
                    if conn_stats:
                        return_db_connection(conn_stats)
                except Exception:
                    pass
    except Exception as e:
        logger.exception("Error getting DB stats in gallery(): %s", e)

    # Fallback to filesystem if DB had no data
    if not total_photos:
        storage = get_storage()
        def _get_dir_size_and_count(path):
            total = 0
            count = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.isfile(fp):
                        try:
                            total += os.path.getsize(fp)
                            count += 1
                        except Exception:
                            pass
            return total, count
        total_bytes, total_photos = _get_dir_size_and_count(storage.originals_path)

    stats = {
        'total_photos': total_photos,
        'total_size_gb': round(total_bytes / (1024.0 ** 3), 2),
        'avg_size_mb': round((total_bytes / total_photos) / (1024.0 ** 2), 2) if total_photos else 0
    }

    return render_template('gallery.html', stats=stats, available_periods=available_periods,
                           photos=photos, selected_period=selected_period, pagination=pagination)

@app.route('/api/stats')
def api_stats():
    """API endpoint for statistics"""
    # Use the database_config helper to get DB info (connection status, version, etc.)
    try:
        from database_config import get_database_info
        db_stats = get_database_info()
    except Exception:
        db_stats = {'status': 'unknown'}

    return jsonify({
        'database': db_stats,
        'timestamp': datetime.now().isoformat()
    })



@app.route('/photo/<photo_id>/thumbnail')
def serve_thumbnail(photo_id):
    """Serve thumbnail for a photo with proper headers and error handling"""
    
    # Try multiple times in case of temporary connectivity issues
    max_retries = 3
    for attempt in range(max_retries):
        conn = get_db_connection()
        if not conn:
            if attempt < max_retries - 1:
                time.sleep(1)  # Brief delay before retry
                continue
            return '', 503  # Service unavailable
        
        try:
            db_config = get_db_config()
            if db_config.get_database_type() == 'postgres':
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('SELECT thumbnail, original_filename FROM photos WHERE id = %s', (photo_id,))
            else:
                cursor = conn.cursor()
                cursor.execute('SELECT thumbnail, original_filename FROM photos WHERE id = ?', (photo_id,))
            
            result = cursor.fetchone()
            
            if result:
                if db_config.get_database_type() == 'postgres':
                    thumbnail_data = result['thumbnail']
                    filename = result['original_filename']
                else:
                    thumbnail_data = result[0]
                    filename = result[1]
                
                if thumbnail_data:
                    import base64
                    from flask import Response
                    
                    # Handle escaped hex string or bytes-like thumbnail data
                    try:
                        from flask import Response

                        binary_thumbnail = None

                        # Common cases: bytes/bytearray
                        if isinstance(thumbnail_data, (bytes, bytearray)):
                            binary_thumbnail = bytes(thumbnail_data)
                        # memoryview or other objects exposing tobytes()
                        elif hasattr(thumbnail_data, 'tobytes'):
                            try:
                                binary_thumbnail = thumbnail_data.tobytes()
                            except Exception:
                                # Fall through to other decoding attempts
                                binary_thumbnail = None
                        # Escaped Postgres hex string representation
                        elif isinstance(thumbnail_data, str) and thumbnail_data.startswith('\\x'):
                            hex_string = thumbnail_data.replace('\\x', '')
                            binary_thumbnail = bytes.fromhex(hex_string)
                        # Base64-encoded string (handle missing padding)
                        elif isinstance(thumbnail_data, str):
                            try:
                                s = thumbnail_data
                                # Add padding if necessary
                                padding = len(s) % 4
                                if padding:
                                    s += '=' * (4 - padding)
                                binary_thumbnail = base64.b64decode(s)
                            except Exception:
                                binary_thumbnail = None
                        else:
                            # Try a last-ditch conversion to bytes
                            try:
                                binary_thumbnail = bytes(thumbnail_data)
                            except Exception:
                                binary_thumbnail = None

                        if not binary_thumbnail:
                            raise ValueError('Could not decode thumbnail data')

                        response = Response(binary_thumbnail, mimetype='image/jpeg')
                        response.headers['Cache-Control'] = 'public, max-age=3600'
                        # Sanitize filename for Content-Disposition
                        try:
                            safe_name = secure_filename(filename) if filename else None
                        except Exception:
                            safe_name = None
                        if not safe_name:
                            safe_name = f"{photo_id}.jpg"
                        response.headers['Content-Disposition'] = f'inline; filename="{safe_name}"'
                        return response

                    except Exception as decode_error:
                        logger.exception("Thumbnail decode error for %s: %s", photo_id, decode_error)
                        return '', 500
                # If DB thumbnail not present or decode failed, try filesystem thumbnails
            # Try to find thumbnail file on disk (storage thumbnails folder)
            try:
                storage = get_storage()
                thumb_name = f"{photo_id}.jpg"
                for root, dirs, files in os.walk(storage.thumbnails_path):
                    if thumb_name in files:
                        thumb_path = os.path.join(root, thumb_name)
                        with open(thumb_path, 'rb') as f:
                            data = f.read()
                        from flask import Response
                        resp = Response(data, mimetype='image/jpeg')
                        resp.headers['Cache-Control'] = 'public, max-age=3600'
                        try:
                            safe_name = secure_filename(thumb_name) if thumb_name else None
                        except Exception:
                            safe_name = None
                        if not safe_name:
                            safe_name = f"{photo_id}.jpg"
                        resp.headers['Content-Disposition'] = f'inline; filename="{safe_name}"'
                        return resp
            except Exception as fs_err:
                logger.exception("Filesystem thumbnail lookup failed for %s: %s", photo_id, fs_err)
            
            # No thumbnail found, return 404
            return '', 404
            
        except Exception as e:
            logger.exception("Error serving thumbnail for photo %s (attempt %d): %s", photo_id, attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(1)  # Brief delay before retry
                continue
            return '', 500  # Internal server error
        finally:
            # Always return the connection
            if conn:
                return_db_connection(conn)
    
    return '', 503  # Service unavailable after all retries


@app.route('/photo/<photo_id>')
def serve_full_photo(photo_id):
    """Serve the full original image for a photo id.

    Looks up the photo record in the DB to find the stored local path. Falls
    back to returning 404 if the DB record or file is missing.
    """
    # Try multiple times in case of transient DB issues
    max_retries = 2
    for attempt in range(max_retries):
        conn = get_db_connection()
        if not conn:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return '', 503

        try:
            db_config = get_db_config()
            if db_config.get_database_type() == 'postgres':
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('SELECT local_path, file_path, original_filename FROM photos WHERE id = %s', (photo_id,))
                row = cursor.fetchone()
            else:
                cursor = conn.cursor()
                cursor.execute('SELECT local_path, file_path, original_filename FROM photos WHERE id = ?', (photo_id,))
                row = cursor.fetchone()

            local_path = None
            filename = None
            if row:
                if db_config.get_database_type() == 'postgres':
                    local_path = row.get('local_path') or row.get('file_path')
                    filename = row.get('original_filename')
                else:
                    local_path = row[0] or row[1]
                    filename = row[2] if len(row) > 2 else None

            storage = get_storage()

            # If DB path found, try to read it
            if local_path:
                try:
                    data = storage.read_photo(local_path)
                    # Attempt to normalize image orientation using EXIF info so full images display correctly
                    try:
                        from PIL import Image, ImageOps
                        import io as _io
                        img = Image.open(_io.BytesIO(data))
                        img = ImageOps.exif_transpose(img)
                        out_io = _io.BytesIO()
                        # Preserve format when possible
                        fmt = img.format or 'JPEG'
                        img.save(out_io, format=fmt, quality=92)
                        out_bytes = out_io.getvalue()
                        data = out_bytes
                        # adjust mime if format detected
                        if fmt.lower() == 'png':
                            mime = 'image/png'
                        else:
                            mime = 'image/jpeg'
                    except Exception:
                        # If Pillow isn't available or processing fails, fall back to raw bytes
                        pass
                    # detect mime type
                    # try to detect image type; fall back to filename extension or jpeg
                    try:
                        import imghdr
                        img_type = imghdr.what(None, data)
                    except Exception:
                        img_type = None

                    mime = 'image/jpeg'
                    if img_type:
                        if img_type == 'jpeg':
                            mime = 'image/jpeg'
                        else:
                            mime = f'image/{img_type}'
                    else:
                        # fallback to extension-based guess if filename provided
                        try:
                            import mimetypes
                            if filename:
                                mt, _ = mimetypes.guess_type(filename)
                                if mt:
                                    mime = mt
                        except Exception:
                            pass
                    from flask import Response
                    resp = Response(data, mimetype=mime)
                    resp.headers['Cache-Control'] = 'public, max-age=86400'
                    try:
                        safe_name = secure_filename(filename) if filename else None
                    except Exception:
                        safe_name = None
                    if not safe_name:
                        # Use id-based fallback and preserve extension guess
                        ext = '.jpg'
                        if mime == 'image/png':
                            ext = '.png'
                        safe_name = f"{photo_id}{ext}"
                    resp.headers['Content-Disposition'] = f'inline; filename="{safe_name}"'
                    return resp
                except FileNotFoundError:
                    # fall through to 404
                    pass
                except Exception as e:
                    logger.exception("Error reading stored photo for %s: %s", photo_id, e)
                    return '', 500

            # If we reach here, DB record missing or file not found
            return '', 404

        finally:
            if conn:
                return_db_connection(conn)

    return '', 503

@app.route('/test-timeline')
def test_timeline():
    """Simple timeline test page"""
    return render_template('simple_timeline_test.html')

@app.route('/test-thumbnails')
def test_thumbnails():
    """Direct thumbnail test page"""
    return render_template('test_thumbnails_direct.html')

@app.route('/test-thumbnails-retry')
def test_thumbnails_retry():
    """Thumbnail test page with retry logic"""
    return render_template('test_thumbnails_with_retry.html')

@app.route('/monthly-thumbnail-test')
def monthly_thumbnail_test():
    """Monthly thumbnail validation page"""
    return render_template('monthly_thumbnail_test.html')

@app.route('/health')
def health_check():
    """Health check endpoint"""
    
    # Test database connection
    conn = get_db_connection()
    if conn:
        return_db_connection(conn)
        db_status = 'connected'
    else:
        db_status = 'disconnected'
    

    return jsonify({
        'status': 'healthy' if db_status == 'connected' else 'unhealthy',
        'database': db_status,
        'timestamp': datetime.now().isoformat()
    })



# Place this before the main block so the route is registered
@app.route('/admin/clear', methods=['POST'])
@require_admin_token
def admin_clear_database():
    from database_config import get_db_connection, return_db_connection, get_db_config
    from storage_manager import get_storage
    import shutil
    # Danger: This will delete all photos and thumbnails!
    confirm = request.form.get('confirm')
    if confirm != 'YES':
        flash('You must type YES to confirm database cleanup.', 'danger')
        return redirect(url_for('admin_functions'))
    # Delete all DB records
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM photos')
        conn.commit()
        flash('All photo records deleted from database.', 'success')
    except Exception as e:
        flash(f'Error clearing database: {e}', 'danger')
    finally:
        return_db_connection(conn)
    # Delete all files in storage (safer: remove children only, with checks)
    storage = get_storage()
    try:
        base = os.path.abspath(storage.base_path)
        # Basic safety checks to avoid accidental deletion of root or unexpected locations
        if base in ('/', '') or 'photo_storage' not in base:
            flash('Refusing to delete storage: unexpected base path', 'danger')
            return redirect(url_for('admin_functions'))

        for entry in os.listdir(base):
            path = os.path.join(base, entry)
            try:
                if os.path.islink(path) or os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path)
            except Exception as e_inner:
                logger.warning("Failed to remove %s: %s", path, e_inner)

        # Ensure directory structure exists
        storage._ensure_directories()
        flash('All files deleted from storage (children only).', 'success')
    except Exception as e:
        flash(f'Error clearing storage: {e}', 'danger')
    return redirect(url_for('admin_functions'))


@app.route('/admin/thumbnail/regenerate', methods=['POST'])
def admin_regenerate_thumbnail():
    """Admin endpoint: regenerate and store thumbnail for a single photo id.

    Expects form or JSON body with 'photo_id'. Returns JSON with status.
    """
    photo_id = None
    try:
        if request.is_json:
            photo_id = request.json.get('photo_id')
        if not photo_id:
            photo_id = request.form.get('photo_id')
    except Exception:
        photo_id = request.form.get('photo_id')

    if not photo_id:
        return jsonify({'error': 'photo_id required'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'database unavailable'}), 503

    try:
        db_cfg = get_db_config()
        # Lookup photo record
        if db_cfg.get_database_type() == 'postgres':
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute('SELECT local_path, photo_taken_date FROM photos WHERE id = %s', (photo_id,))
            row = cur.fetchone()
            if row:
                local_path = row.get('local_path') or None
                taken_date = row.get('photo_taken_date')
            else:
                return jsonify({'error': 'photo not found'}), 404
        else:
            cur = conn.cursor()
            cur.execute('SELECT local_path, photo_taken_date FROM photos WHERE id = ?', (photo_id,))
            row = cur.fetchone()
            if row:
                local_path = row[0]
                taken_date = row[1] if len(row) > 1 else None
            else:
                return jsonify({'error': 'photo not found'}), 404

        storage = get_storage()
        try:
            photo_data = storage.read_photo(local_path)
        except FileNotFoundError:
            return jsonify({'error': 'stored photo file not found'}), 404
        except Exception as e:
            logger.exception('Error reading photo for %s: %s', photo_id, e)
            return jsonify({'error': 'could not read photo'}), 500

        try:
            # import generator locally to avoid top-level cycles
            from local_thumbnail_generator import generate_thumbnail
            thumb_data = generate_thumbnail(photo_data)
            if not thumb_data:
                return jsonify({'error': 'thumbnail generation failed'}), 500
        except Exception as e:
            logger.exception('Thumbnail generation failed for %s: %s', photo_id, e)
            return jsonify({'error': 'thumbnail generation error'}), 500

        # Store thumbnail file on disk
        try:
            storage.store_thumbnail(thumb_data, photo_id, taken_date)
        except Exception:
            logger.exception('Failed to store thumbnail file for %s', photo_id)

        # Update DB
        try:
            if db_cfg.get_database_type() == 'postgres':
                ucur = conn.cursor()
                ucur.execute('UPDATE photos SET thumbnail = %s, processed = TRUE WHERE id = %s', (thumb_data, photo_id))
            else:
                ucur = conn.cursor()
                ucur.execute('UPDATE photos SET thumbnail = ?, processed = 1 WHERE id = ?', (thumb_data, photo_id))
            conn.commit()
        except Exception as e:
            logger.exception('Failed to update DB thumbnail for %s: %s', photo_id, e)
            try:
                conn.rollback()
            except Exception:
                pass
            return jsonify({'error': 'failed to update database'}), 500

        return jsonify({'status': 'ok', 'photo_id': photo_id}), 200

    finally:
        if conn:
            return_db_connection(conn)
@app.route('/admin/storage/usage')
@require_admin_token
def admin_storage_usage():
    """Return JSON with storage usage: total bytes and file count under storage.base_path."""
    try:
        storage = get_storage()
        base = storage.base_path
        # Basic safety: ensure base looks like the app storage root
        if not base or not os.path.isdir(base):
            return jsonify({'error': 'storage base path not found'}), 404

        total_bytes = 0
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(base):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if os.path.isfile(fp):
                        file_count += 1
                        total_bytes += os.path.getsize(fp)
                except Exception:
                    # skip files we cannot stat
                    continue

        return jsonify({'total_bytes': total_bytes, 'file_count': file_count})
    except Exception as e:
        logger.exception('Error computing storage usage: %s', e)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("🚀 Starting Simple Photo Database Admin Panel")
    logger.info("%s", "=" * 50)
    logger.info("📊 Admin Dashboard: http://localhost:5001")
    logger.info(" API Stats: http://localhost:5001/api/stats")
    logger.info("❤️  Health Check: http://localhost:5001/health")
    logger.info("%s", "=" * 50)
    # Configure logging level from environment using centralized initializer
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    # If DB_TYPE is not explicitly set (or set to auto), prefer Postgres when
    # Postgres environment variables are present. This allows the running
    # application to use the Postgres backend by default when a Postgres
    # instance is available without requiring the caller to set DB_TYPE.
    try:
        db_type_env = os.environ.get('DB_TYPE', 'auto').lower()
        # Look for common Postgres env vars — if present and DB_TYPE is not
        # explicitly 'local', switch to Postgres at startup.
        pg_env_present = any(os.environ.get(k) for k in ('DB_HOST', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'PG_DSN', 'DATABASE_URL'))
        if db_type_env in ('', 'auto') and pg_env_present:
            try:
                # Import here to avoid top-level import cycles during testing
                from database_config import switch_database, init_database
                switched = switch_database('postgres')
                if switched:
                    init_database()
                    logger.info('Auto-switched database to Postgres based on environment.')
            except Exception:
                logger.exception('Failed to auto-configure Postgres at startup — continuing with configured DB type.')
    except Exception:
        # Protect startup from any unexpected environ parsing errors
        logger.exception('Unexpected error while detecting DB environment')

    init_logging(level=log_level)
    logging.info('Flask app is starting on http://localhost:5001')
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5001, debug=debug_mode)


# Global error handler: return JSON for large payload errors when client expects JSON/XHR
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(error):
    """Handle Werkzeug's RequestEntityTooLarge (413) and return JSON for XHR/JSON clients.

    This avoids the browser-side JSON.parse error when Flask/Werkzeug returns the
    default HTML error page for oversized multipart bodies.
    """
    accept = request.headers.get('Accept', '')
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    wants_json = 'application/json' in accept or is_xhr or request.is_json

    # Log sizes to help debugging oversized uploads
    try:
        req_len = request.content_length
    except Exception:
        req_len = None
    max_b = app.config.get('MAX_CONTENT_LENGTH')
    logger.warning('RequestEntityTooLarge: content_length=%s, MAX_CONTENT_LENGTH=%s', req_len, max_b)

    msg = 'Uploaded data is too large. Please upload fewer files or increase server limits.'
    if wants_json:
        return jsonify({'success': False, 'message': msg, 'error': 'request_entity_too_large'}), 413
    else:
        # Return a minimal HTML response so normal form submissions get a readable page
        html = f"""<!doctype html><title>Request Entity Too Large</title>
        <h1>413 Request Entity Too Large</h1>
        <p>{msg}</p>
        <p><a href=\"{url_for('main_dashboard')}\">Return to dashboard</a></p>"""
        return html, 413

