"""Start coverage in EVERY Python process that inherits PYTHONPATH.

Python imports `sitecustomize` automatically at interpreter startup, before
user code. coverage.process_startup() is a no-op unless COVERAGE_PROCESS_START
names a config file, so this file is inert outside a measured run -- it is on
PYTHONPATH only for the length of one command, and nothing in venv/ is touched.
"""
import coverage

coverage.process_startup()
