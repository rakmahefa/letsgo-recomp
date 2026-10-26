# PyInstaller spec: the game code generator (tools/gen.py and its modules) as a standalone onedir helper, so the start
# screen's setup can build the game code on the player's machine without Python (runtime/gamebuild.c).
# `make gen-helper` -> build/helper/lasgen/ (lasgen[.exe] + _internal/). Same command line as gen.py.
import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

TOOLS = os.path.normpath(SPECPATH)

# collect_dynamic_libs only picks unversioned names (libcapstone.so, ...): unicorn's library is versioned
# (libunicorn.so.2 on Linux, libunicorn.2.dylib on macOS, unicorn.dll on Windows), so add it by hand, where the
# package's loader looks for it (importlib.resources files('unicorn')/'lib'; LIBUNICORN_PATH overrides it)
_uc_lib_dir = os.path.join(os.path.dirname(importlib.util.find_spec('unicorn').origin), 'lib')
_uc_versioned = (glob.glob(os.path.join(_uc_lib_dir, 'libunicorn.so*'))  # (not libunicorn.a: static, unused)
                 + glob.glob(os.path.join(_uc_lib_dir, 'libunicorn.*.dylib'))
                 + glob.glob(os.path.join(_uc_lib_dir, 'unicorn.dll')))

a = Analysis(
    [os.path.join(TOOLS, 'gen.py')],
    pathex=[TOOLS],
    binaries=collect_dynamic_libs('capstone') + collect_dynamic_libs('unicorn')
             + [(p, 'unicorn/lib') for p in _uc_versioned],
    datas=[],
    # Unicorn 2.1.2 resolves its bundled libunicorn through pkg_resources at import time.
    # Keep pkg_resources and its dynamic submodules in the frozen app; excluding it makes the
    # native runtime compile successfully but crashes the packaged helper before --help.
    hiddenimports=collect_submodules('unicorn') + collect_submodules('pkg_resources'),
    # setuptools >= 71 exposes jaraco.text via setuptools._vendor; PyInstaller's pkg_resources hook aliases
    # that module to the vendored copy. Keep setuptools available so the alias resolves in the frozen helper.
    # This is a non-interactive CLI helper; excluding readline avoids an unnecessary host
    # libreadline dependency from Python's optional interactive shell support.
    excludes=['tkinter', 'pydoc', 'doctest', 'unittest', 'pdb', 'IPython', 'numpy', '_distutils_hack',
              'readline', 'rlcompleter',
              'ssl', '_ssl', '_hashlib', '_multibytecodec', '_codecs_cn', '_codecs_hk',
              '_codecs_iso2022', '_codecs_jp', '_codecs_kr', '_codecs_tw', '_decimal'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [('hash_seed=0', None, 'OPTION')],  # (the same output every run)
    exclude_binaries=True,
    name='lasgen',
    console=True,  # stderr = the progress lines the runtime reads (no window: CREATE_NO_WINDOW)
    strip=sys.platform == 'darwin',
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=sys.platform == 'darwin', upx=False, name='lasgen')
