import os

# Tests run with DEBUG on so that a SECRET_KEY default is available locally and in CI.
os.environ.setdefault("DJANGO_DEBUG", "1")
