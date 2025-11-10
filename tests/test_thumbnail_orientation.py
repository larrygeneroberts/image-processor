import io
import os
import sys
from PIL import Image, ImageOps

# Ensure project root on sys.path for test discovery when running from repo root
_HERE = os.path.abspath(os.path.dirname(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from local_thumbnail_generator import generate_thumbnail


def _make_jpeg_with_exif_orientation(size=(400, 200), orientation=6, color=(123, 234, 45)):
    """Create JPEG bytes with an EXIF Orientation tag set.

    Uses Pillow's Exif interface so no extra deps are required.
    """
    b = io.BytesIO()
    im = Image.new('RGB', size, color)
    exif = im.getexif()
    # EXIF orientation tag id is 274
    exif[274] = orientation
    im.save(b, format='JPEG', exif=exif.tobytes())
    return b.getvalue()


def test_generate_thumbnail_respects_exif_orientation():
    # Create an image that is wider than tall and give it an orientation
    img_bytes = _make_jpeg_with_exif_orientation(size=(400, 200), orientation=6)

    # Run the project's thumbnail generator
    thumb_bytes = generate_thumbnail(img_bytes, max_size=(300, 300))
    assert thumb_bytes is not None

    # Open thumbnail produced by generator
    thumb_img = Image.open(io.BytesIO(thumb_bytes))

    # Now compute expected result by manually applying the same operations
    src = Image.open(io.BytesIO(img_bytes))
    src_transposed = ImageOps.exif_transpose(src)
    # Ensure conversion to RGB and thumbnailing like the generator
    if src_transposed.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', src_transposed.size, (255, 255, 255))
        bg.paste(src_transposed, mask=src_transposed.split()[-1])
        src_transposed = bg
    elif src_transposed.mode != 'RGB':
        src_transposed = src_transposed.convert('RGB')

    src_transposed.thumbnail((300, 300), Image.LANCZOS)

    # Sizes should match if orientation was honored
    assert thumb_img.size == src_transposed.size
