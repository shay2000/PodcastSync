"""PodcastSync test suite.

This file makes `tests` a package, which does two things: it lets test modules
share helpers via `from tests.conftest import ...`, and it makes pytest put the
project root on sys.path so `import backend` works under a bare `pytest` call
as well as `python -m pytest`.
"""
