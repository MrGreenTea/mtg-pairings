#!/usr/bin/env python
import logging
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost")
    logger = logging.getLogger(__name__)
    secret_key = os.environ.get("DJANGO_SECRET_KEY")
    if not secret_key:
        logger.warning("DJANGO_SECRET_KEY not set. will default to value 'NO_KEY_YET'")
        os.environ["DJANGO_SECRET_KEY"] = "NO_KEY_YET"

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
