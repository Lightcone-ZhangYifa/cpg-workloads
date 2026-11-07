"""One concrete environment shared by the original ELF gate and real execution."""
from pathlib import Path
import os


def runtime_path(runtime, relative, *, directory=True):
    value = Path(relative)
    if value.is_absolute() or '..' in value.parts:
        raise RuntimeError('Runtime configuration has an escaping path')
    path = (runtime / value).resolve()
    if not path.is_relative_to(runtime.resolve()) or not path.exists():
        raise RuntimeError('Missing or escaping private runtime path: ' + relative)
    if directory and not path.is_dir():
        raise RuntimeError('Expected a private runtime directory: ' + relative)
    return path


def build_environment(runtime, config, run_dir, temporary):
    clear = ('LD_', 'RUST', 'CARGO_', 'CREUSOT_', 'WHY3', 'CAML_', 'OCAML', 'OPAM',
             'CPG_CREUSOT_')
    environment = {key: value for key, value in os.environ.items()
                   if not any(key.startswith(prefix) for prefix in clear)}
    libraries = [runtime_path(runtime, name) for name in config['private_library_dirs']]
    binaries = [runtime_path(runtime, name) for name in config['private_bin_dirs']]
    for name in ('cargo-home', 'xdg-cache', 'xdg-config'):
        (run_dir / name).mkdir(exist_ok=True)
    selected = {
        'PATH': ':'.join(map(str, binaries)) + ':/usr/bin:/bin',
        'LD_LIBRARY_PATH': ':'.join(map(str, libraries)),
        'CAML_LD_LIBRARY_PATH': str(runtime_path(runtime, 'ocaml-runtime/stublibs')),
        'WHY3LIB': str(runtime_path(runtime, 'why3-static/lib/why3')),
        'WHY3DATA': str(runtime_path(runtime, config['why3_data_dir'])),
        'RUSTUP_HOME': str(runtime_path(runtime, 'rustup-home')),
        'RUSTUP_AUTO_INSTALL': '0',
        'RUSTUP_TOOLCHAIN': config['rust_toolchain'],
        'CARGO_HOME': str(run_dir / 'cargo-home'),
        'CARGO_NET_OFFLINE': 'true',
        'CARGO_INCREMENTAL': '0',
        'XDG_CACHE_HOME': str(run_dir / 'xdg-cache'),
        'XDG_CONFIG_HOME': str(run_dir / 'xdg-config'),
        'TMPDIR': str(temporary),
        'CPG_CREUSOT_TMP': str(temporary),
        'CPG_CREUSOT_RUN_DIR': str(run_dir),
        'LC_ALL': 'C.UTF-8',
    }
    environment.update(selected)
    return environment, selected
