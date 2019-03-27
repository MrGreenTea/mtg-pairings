import os

os.environ.setdefault('DJANGO_SECRET_KEY', 'TEST_KEY')
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', '')
os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/test_sqlite.db')

from .settings import *