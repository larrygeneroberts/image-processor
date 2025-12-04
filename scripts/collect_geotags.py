#!/usr/bin/env python3
"""
Scan originals storage for geolocation info.

Checks (in order):
 - exiftool (if installed) for robust extraction from images and sidecars
 - Pillow EXIF GPSInfo parsing as fallback
 - Sidecar files (.xmp, .json, .aae) for lat/lon patterns
 - Optional DB lookup for common latitude/longitude columns in `photos` table

Outputs a CSV report (geotag_report.csv) with: path, lat, lon, source

Usage: python scripts/collect_geotags.py [--csv output.csv] [--use-db]

"""

import os
import re
import csv
import sys
import json
import subprocess
import shutil
from argparse import ArgumentParser

try:
    from storage_manager import get_storage
except Exception:
    get_storage = None

try:
    from PIL import Image, ExifTags
except Exception:
    Image = None

# Regex to loosely match decimal lat/lon in sidecars
DEC_COORD_RE = re.compile(r"([-+]?[0-9]{1,3}\.\d+)[,\s]+([-+]?[0-9]{1,3}\.\d+)")

EXTS = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.heif')
SIDECAR_EXTS = ('.xmp', '.json', '.aae')


def find_exiftool():
    return shutil.which('exiftool')


def exiftool_query(path, keys=None):
    """Run exiftool on path and return dict (JSON) or None"""
    exiftool = find_exiftool()
    if not exiftool:
        return None
    cmd = [exiftool, '-j']
    if keys:
        cmd = [exiftool, '-j'] + [f'-{k}' for k in keys]
    cmd.append(path)
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(out.decode('utf8'))
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception:
        return None


def parse_pillow_gps(exif):
    """Return (lat, lon) or None from Pillow EXIF mapping"""
    if not exif:
        return None
    # Map tag ids to names
    gps_tag = None
    for tag_id, name in ExifTags.TAGS.items():
        if name == 'GPSInfo':
            gps_tag = tag_id
            break
    if not gps_tag:
        return None
    gps = exif.get(gps_tag)
    if not gps:
        return None
    # gps is a dict-like mapping of tags -> values (small ints keys)
    # Robust conversion helpers to handle PIL rationals, Fractions, tuples, ints, floats
    def _rational_to_float(v):
        try:
            if v is None:
                return None
            # tuple (num, den)
            if isinstance(v, tuple) and len(v) == 2:
                n, d = v
                return float(n) / float(d) if d != 0 else None
            # Some types expose numerator/denominator
            if hasattr(v, 'numerator') and hasattr(v, 'denominator'):
                try:
                    return float(v.numerator) / float(v.denominator)
                except Exception:
                    return None
            # raw numeric
            if isinstance(v, (int, float)):
                return float(v)
            # bytes or string can't be parsed here
            return None
        except Exception:
            return None

    def _to_decimal(coord_val):
        # coord_val may be: ((d_n,d_d),(m_n,m_d),(s_n,s_d)) or similar
        try:
            # iterable of 3 parts
            if hasattr(coord_val, '__iter__'):
                parts = list(coord_val)
                if len(parts) >= 3:
                    d = _rational_to_float(parts[0])
                    m = _rational_to_float(parts[1])
                    s = _rational_to_float(parts[2])
                    if d is not None and m is not None and s is not None:
                        return d + (m / 60.0) + (s / 3600.0)
                # maybe a single rational
                if len(parts) == 1:
                    return _rational_to_float(parts[0])
        except Exception:
            pass
        return None

    lat = None
    lon = None
    lat_ref = gps.get(1) or gps.get('GPSLatitudeRef')
    lon_ref = gps.get(3) or gps.get('GPSLongitudeRef')
    lat_val = gps.get(2) or gps.get('GPSLatitude')
    lon_val = gps.get(4) or gps.get('GPSLongitude')
    if lat_val and lon_val:
        try:
            lat = _to_decimal(lat_val)
            lon = _to_decimal(lon_val)
            # normalize refs (bytes -> str)
            try:
                if isinstance(lat_ref, bytes):
                    lat_ref = lat_ref.decode('utf8', 'ignore')
                if isinstance(lon_ref, bytes):
                    lon_ref = lon_ref.decode('utf8', 'ignore')
            except Exception:
                pass
            if lat is not None and isinstance(lat_ref, str) and lat_ref.upper() == 'S':
                lat = -abs(lat)
            if lon is not None and isinstance(lon_ref, str) and lon_ref.upper() == 'W':
                lon = -abs(lon)
            if lat is not None and lon is not None:
                return (lat, lon)
        except Exception:
            return None
    return None


def try_sidecar_for_coords(basepath):
    """Look for sidecar files with same basename and try to extract decimal coords"""
    base, _ = os.path.splitext(basepath)
    for ext in SIDECAR_EXTS:
        p = base + ext
        if os.path.exists(p):
            try:
                txt = open(p, 'rb').read().decode('utf8', 'ignore')
                # Try exiftool on the sidecar if available
                ex = find_exiftool()
                if ex:
                    res = exiftool_query(p, keys=['GPSLatitude', 'GPSLongitude'])
                    if res:
                        lat = res.get('GPSLatitude')
                        lon = res.get('GPSLongitude')
                        # exiftool may return as strings; try to coerce
                        try:
                            return (float(str(lat)), float(str(lon)), 'sidecar-exiftool')
                        except Exception:
                            pass
                # Fallback: regex search for decimal pair
                m = DEC_COORD_RE.search(txt)
                if m:
                    return (float(m.group(1)), float(m.group(2)), f'sidecar:{ext}')
                # Search for separate lat/lon tokens
                # find any lat-looking number and then lon after it
                nums = re.findall(r"[-+]?\d{1,3}\.\d+", txt)
                if len(nums) >= 2:
                    return (float(nums[0]), float(nums[1]), f'sidecar:{ext}')
            except Exception:
                continue
    return None


def try_db_for_coords(db_cfg, photo_path):
    """Attempt to find coordinates in DB for a given photo_path. This is best-effort.

    Tries common column names in `photos` table: gps_latitude, gps_longitude, latitude, longitude, lat, lon
    Looks up by original filename or relative path.
    """
    try:
        from database_config import get_db_connection, get_db_config
    except Exception:
        return None
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cur = conn.cursor()
        # find candidate columns
        cols = ['gps_latitude', 'gps_longitude', 'latitude', 'longitude', 'lat', 'lon']
        # inspect photos table columns
        # sqlite: PRAGMA table_info(photos)
        db_cfg_local = get_db_config()
        kind = db_cfg_local.get_database_type()
        existing = set()
        try:
            if kind == 'local':
                cur.execute("PRAGMA table_info(photos);")
                rows = cur.fetchall()
                for r in rows:
                    if isinstance(r, tuple):
                        existing.add(r[1])
                    else:
                        existing.add(r.get('name'))
            else:
                # Postgres: use information_schema
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='photos';")
                for r in cur.fetchall():
                    existing.add(r[0] if isinstance(r, tuple) else r.get('column_name'))
        except Exception:
            pass
        want = [c for c in cols if c in existing]
        if not want:
            return None
        # Try to match by filename or relative path
        fname = os.path.basename(photo_path)
        # Query trying a few match columns
        for col_lat, col_lon in [('gps_latitude','gps_longitude'), ('latitude','longitude'), ('lat','lon')]:
            if col_lat in existing and col_lon in existing:
                q = None
                params = None
                # Try matching by original_filename
                try:
                    cur.execute("SELECT {0}, {1} FROM photos WHERE original_filename = %s LIMIT 1".format(col_lat, col_lon), (fname,))
                    row = cur.fetchone()
                    if row and row[0] is not None and row[1] is not None:
                        return (float(row[0]), float(row[1]), 'db')
                except Exception:
                    try:
                        # sqlite paramstyle
                        cur.execute("SELECT {0}, {1} FROM photos WHERE original_filename = ? LIMIT 1".format(col_lat, col_lon), (fname,))
                        row = cur.fetchone()
                        if row and row[0] is not None and row[1] is not None:
                            return (float(row[0]), float(row[1]), 'db')
                    except Exception:
                        pass
        return None
    except Exception:
        return None
    finally:
        try:
            if conn:
                from database_config import return_db_connection
                return_db_connection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def main(argv):
    p = ArgumentParser()
    p.add_argument('--csv', default='geotag_report.csv')
    p.add_argument('--no-progress', action='store_true', help='disable console progress meter')
    p.add_argument('--use-db', action='store_true', help='also query DB for coords (best-effort)')
    args = p.parse_args(argv[1:])

    storage = None
    if get_storage:
        try:
            storage = get_storage()
            root = storage.originals_path
        except Exception:
            storage = None
    if not get_storage or storage is None:
        # Fallback: assume repository layout and look for photo_storage/originals
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        candidate = os.path.join(repo_root, 'photo_storage', 'originals')
        if os.path.exists(candidate):
            root = candidate
            print('get_storage not available; falling back to', root)
        else:
            print('get_storage not available and fallback path not found; pass a path or fix imports')
            sys.exit(1)

    exiftool = find_exiftool()
    if exiftool:
        print('Using exiftool at', exiftool)
    else:
        print('exiftool not found; falling back to Pillow + sidecar heuristics')

    # Build list of candidate files first so we can report total and show progress
    rows = []
    candidates = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(EXTS):
                continue
            candidates.append(os.path.join(dirpath, fn))

    total = len(candidates)
    geo_count = 0
    errors = 0

    progress_enabled = not getattr(args, 'no_progress', False)
    last_percent = -1

    # Prefer tqdm for a rich progress bar when available
    try:
        from tqdm import tqdm
        has_tqdm = True
    except Exception:
        has_tqdm = False

    if has_tqdm and progress_enabled:
        iterator = enumerate(tqdm(candidates, desc='Scanning', unit='files', total=total), start=1)
    else:
        iterator = enumerate(candidates, start=1)

    for idx, fp in iterator:
        found = None
        # 1) exiftool
        if exiftool:
            try:
                res = exiftool_query(fp, keys=['GPSLatitude','GPSLongitude'])
                if res:
                    lat = res.get('GPSLatitude')
                    lon = res.get('GPSLongitude')
                    # exiftool may return string like '37 deg 48'... or decimal
                    if lat and lon:
                        try:
                            lat_f = float(str(lat))
                            lon_f = float(str(lon))
                            found = (lat_f, lon_f, 'exiftool')
                        except Exception:
                            # exiftool sometimes returns like "37 deg 48' 30.12\" N"; try to re-run for decimal
                            dec = exiftool_query(fp, keys=['-gpslatitude#','-gpslongitude#'])
                            if dec:
                                try:
                                    lat_f = float(dec.get('GPSLatitude#'))
                                    lon_f = float(dec.get('GPSLongitude#'))
                                    found = (lat_f, lon_f, 'exiftool')
                                except Exception:
                                    pass
            except Exception:
                pass
        # 2) Pillow EXIF
        if not found and Image is not None:
            try:
                with Image.open(fp) as img:
                    try:
                        exif = img._getexif()
                    except Exception:
                        exif = None
                    coords = parse_pillow_gps(exif) if exif else None
                    if coords:
                        found = (coords[0], coords[1], 'pillow')
                    else:
                        # If full numeric coords couldn't be parsed, still
                        # treat presence of GPSInfo as geotagged (no numeric)
                        try:
                            gps_tag = None
                            for tag_id, name in ExifTags.TAGS.items():
                                if name == 'GPSInfo':
                                    gps_tag = tag_id
                                    break
                            if exif and gps_tag and exif.get(gps_tag):
                                # mark as geotagged but without numeric coords
                                found = (None, None, 'pillow-gpsinfo')
                        except Exception:
                            pass
            except Exception:
                errors += 1
        # 3) Sidecars
        if not found:
            side = try_sidecar_for_coords(fp)
            if side:
                found = (side[0], side[1], side[2])
        # 4) DB
        if not found and args.use_db:
            dbcoords = try_db_for_coords(None, fp)
            if dbcoords:
                found = dbcoords

        if found:
            geo_count += 1
            rows.append({'path': fp, 'lat': found[0], 'lon': found[1], 'source': found[2]})
        else:
            rows.append({'path': fp, 'lat': '', 'lon': '', 'source': ''})

        # Update fallback progress display only when tqdm is not used
        if (not has_tqdm) and progress_enabled and total > 0:
            percent = int((idx / total) * 100)
            # print when percent increases or every 100 files
            if percent != last_percent or (idx % 100 == 0):
                last_percent = percent
                print(f"Processed {idx}/{total} ({percent}%) - geotagged={geo_count} errors={errors}", end='\r', flush=True)

    # If fallback progress printed, ensure newline
    if (not has_tqdm) and progress_enabled:
        print('')

    # Write CSV
    out = args.csv
    with open(out, 'w', newline='', encoding='utf8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['path','lat','lon','source'])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print('\nDone. Scanned:', total)
    print('Geotagged found:', geo_count)
    print('Report written to', out)


if __name__ == '__main__':
    main(sys.argv)
