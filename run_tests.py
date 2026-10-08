"""Run the regression suite with this package's optional WeChat dependencies."""
import pathlib
import sys
import unittest

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='backslashreplace')

root = pathlib.Path(__file__).resolve().parent
packages = root / '.wechat-packages'
if packages.is_dir():
    sys.path.insert(0, str(packages))
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
