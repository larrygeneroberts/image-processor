"""Compatibility shim for older imports.

Some tests import `regenerate_thumbnails` as a top-level module. The
implementation lives under `scripts/regenerate_thumbnails.py` so provide a
small shim here that re-exports the public API.
"""
"""
Prefer to expose the real module object from `scripts.regenerate_thumbnails`
as the top-level `regenerate_thumbnails` module so code/tests that
`import regenerate_thumbnails` get the actual implementation module and
monkeypatching (module attributes) works as expected.
"""
import importlib
import sys

try:
    real = importlib.import_module('scripts.regenerate_thumbnails')
    # Ensure top-level name points to the real module object
    sys.modules['regenerate_thumbnails'] = real
    # Re-export symbols for convenience
    globals().update({k: getattr(real, k) for k in dir(real) if not k.startswith('_')})
except Exception:
    # Last-resort: try the relative import path
    try:
        real = importlib.import_module('.scripts.regenerate_thumbnails', package=__package__)
        sys.modules['regenerate_thumbnails'] = real
        globals().update({k: getattr(real, k) for k in dir(real) if not k.startswith('_')})
    except Exception:
        raise
