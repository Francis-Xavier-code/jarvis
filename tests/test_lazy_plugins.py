"""Tests for lazy plugin loading: stubs registered at startup, real load on first call."""
from __future__ import annotations

from pathlib import Path

from jarvis.kernel import Kernel


def _make_lazy_plugin(plugins: Path, name: str = 'lazy-demo') -> None:
    d = plugins / name
    d.mkdir()
    (d / 'plugin.toml').write_text(
        '[plugin]\n'
        f'name = \"{name}\"\n'
        'kind = \"tool\"\n'
        'entry = \"plugin.py\"\n'
        'hot_reload = true\n'
        'lazy = true\n'
        '\n'
        '[provides]\n'
        'tools = [{ name = \"lazy_demo.hello\", description = \"say hello lazily\", parameters = {} }]\n'
    )
    (d / 'plugin.py').write_text(
        'from jarvis.types import KernelApi\n'
        'def setup(kernel):\n'
        '    @kernel.tool(\"lazy_demo.hello\", \"real hello\", {})\n'
        '    def hello(name=\"world\"): return \"hello \" + name\n'
    )


def test_lazy_plugin_stub_then_first_call_loads(tmp_path: Path) -> None:
    plugins = tmp_path / 'plugins'
    plugins.mkdir()
    _make_lazy_plugin(plugins)
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / 'data'))
    k.load()

    plugin = k.manager.plugins['lazy-demo']
    assert plugin.module is None  # not loaded at startup
    spec = k._tools['lazy_demo.hello']
    assert spec.description == 'say hello lazily'  # stub uses the declared description

    out = spec.handler(name='JARVIS')  # first call -> real load
    assert out == 'hello JARVIS'
    assert plugin.module is not None
    # stub replaced by the real tool definition
    assert k._tools['lazy_demo.hello'].description == 'real hello'


def test_lazy_plugin_load_failure_reports_error(tmp_path: Path) -> None:
    plugins = tmp_path / 'plugins'
    plugins.mkdir()
    d = plugins / 'broken-lazy'
    d.mkdir()
    (d / 'plugin.toml').write_text(
        '[plugin]\nname = \"broken-lazy\"\nkind = \"tool\"\nentry = \"plugin.py\"\nhot_reload = true\nlazy = true\n'
        '\n[provides]\ntools = [\"broken_lazy.x\"]\n'
    )
    (d / 'plugin.py').write_text('this is not valid python !!!')
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / 'data'))
    k.load()
    out = k._tools['broken_lazy.x'].handler()
    assert 'failed to load' in out


def test_non_lazy_plugins_unaffected(tmp_path: Path) -> None:
    plugins = tmp_path / 'plugins'
    plugins.mkdir()
    _make_lazy_plugin(plugins)
    d = plugins / 'eager-demo'
    d.mkdir()
    (d / 'plugin.toml').write_text('[plugin]\nname = \"eager-demo\"\nkind = \"tool\"\nentry = \"plugin.py\"\nhot_reload = true\n')
    (d / 'plugin.py').write_text('from jarvis.types import KernelApi\ndef setup(kernel):\n    @kernel.tool(\"eager.ready\", \"r\", {})\n    def ready(): return \"ok\"\n')
    k = Kernel(plugins_dir=str(plugins), data_dir=str(tmp_path / 'data'))
    k.load()
    assert k.manager.plugins['eager-demo'].module is not None  # eager loaded
    assert k.manager.plugins['lazy-demo'].module is None
