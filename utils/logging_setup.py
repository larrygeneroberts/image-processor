import logging
import os
from copy import deepcopy
from typing import Any, Iterable, Union


def init_logging(level: Union[str, int] = None, default_format: Union[str, None] = None) -> None:
    """Initialize global logging configuration from environment.

    Accepts keyword `level` for backward compatibility with callers that pass
    `level=`. Reads LOG_LEVEL and LOG_FORMAT from env when arguments omitted.
    """
    # Accept both string names like 'INFO' and numeric levels
    lvl_in = level if level is not None else os.environ.get('LOG_LEVEL', 'INFO')
    if isinstance(lvl_in, str):
        try:
            lvl = getattr(logging, lvl_in.upper())
        except Exception:
            lvl = logging.INFO
    else:
        lvl = lvl_in or logging.INFO

    fmt = default_format or os.environ.get('LOG_FORMAT', '%(asctime)s %(levelname)s %(name)s: %(message)s')

    root = logging.getLogger()
    # If we've already configured logging, update level and ensure any
    # requested file handler is present (tests set LOG_FILE dynamically).
    if getattr(root, '_configured_by_logging_setup', False):
        root.setLevel(lvl)
        # If a LOG_FILE is requested and no file handler exists, add one.
        log_file = os.environ.get('LOG_FILE')
        if log_file:
            # Check whether a handler already writes to the requested log file.
            has_file_for_path = any(getattr(h, 'baseFilename', None) == log_file for h in root.handlers)
            if not has_file_for_path:
                try:
                    from logging.handlers import RotatingFileHandler
                    max_bytes = int(os.environ.get('LOG_MAX_BYTES', 5 * 1024 * 1024))
                    backup_count = int(os.environ.get('LOG_BACKUP_COUNT', 5))
                    fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
                except Exception:
                    fh = logging.FileHandler(log_file)
                fh.setLevel(lvl)
                formatter = logging.Formatter(fmt=fmt, datefmt=os.environ.get('LOG_DATEFMT'))
                fh.setFormatter(formatter)
                root.addHandler(fh)
        return

    root.setLevel(lvl)
    ch = logging.StreamHandler()
    ch.setLevel(lvl)
    formatter = logging.Formatter(fmt=fmt, datefmt=os.environ.get('LOG_DATEFMT'))
    ch.setFormatter(formatter)
    root.addHandler(ch)

    log_file = os.environ.get('LOG_FILE')
    if log_file:
        try:
            # Use a rotating file handler to avoid unbounded log files. Configure
            # via env vars: LOG_MAX_BYTES and LOG_BACKUP_COUNT
            try:
                from logging.handlers import RotatingFileHandler
                max_bytes = int(os.environ.get('LOG_MAX_BYTES', 5 * 1024 * 1024))
                backup_count = int(os.environ.get('LOG_BACKUP_COUNT', 5))
                fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
            except Exception:
                fh = logging.FileHandler(log_file)
            fh.setLevel(lvl)
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except Exception:
            root.exception('Failed to create file handler for logging file: %s', log_file)

    root._configured_by_logging_setup = True


def get_logger(name: Union[str, None] = None) -> logging.Logger:
    return logging.getLogger(name if name else __name__)


def _redact_value(v: Any, placeholder: str = 'REDACTED') -> Any:
    try:
        if isinstance(v, str):
            if len(v) > 64:
                return f"{placeholder} (len={len(v)})"
    except Exception:
        pass
    return placeholder


DEFAULT_SENSITIVE_KEYS = {'password', 'passwd', 'secret', 'token', 'api_key', 'access_key', 'secret_key', 'db_password', 'authorization'}


def redact_dict(obj: Any, keys_to_redact: Union[Iterable[str], None] = None, placeholder: str = 'REDACTED') -> Any:
    """Deep-redact sensitive keys in nested dicts/lists.

    Keys are matched case-insensitively. The function is defensive and will
    return a shallow copy if deep-redaction fails.
    """
    if keys_to_redact is None:
        keys = {k.lower() for k in DEFAULT_SENSITIVE_KEYS}
    else:
        keys = {k.lower() for k in keys_to_redact}

    def _walk(o: Any):
        try:
            if o is None:
                return None
            if isinstance(o, dict):
                out = {}
                for k, v in o.items():
                    try:
                        if isinstance(k, str) and k.lower() in keys:
                            out[k] = _redact_value(v, placeholder)
                        else:
                            out[k] = _walk(v)
                    except Exception:
                        out[k] = 'REDACT-ERROR'
                return out
            elif isinstance(o, (list, tuple)):
                seq = [_walk(x) for x in o]
                return type(o)(seq)
            else:
                return deepcopy(o)
        except Exception:
            return 'REDACT-ERROR'

    try:
        return _walk(obj)
    except Exception:
        try:
            return deepcopy(obj)
        except Exception:
            return obj
