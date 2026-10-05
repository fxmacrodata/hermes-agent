"""Computer-use backend registry: :class:`tools.computer_use.backend.ComputerUseProvider` factories registered by
plugins via :meth:`PluginContext.register_computer_use_provider` and selected by ``computer_use.backend``
(read per call, so each profile gets its own). The built-in cua-driver provider is registered here first; a
plugin registering the same name replaces it in that plugin's profile. There is no fallback: a configured name
that nothing registered raises ``LookupError`` naming the available backends.
"""

from __future__ import annotations

import logging

from agent.provider_registry import ProviderRegistry, lower_key
from tools.computer_use.backend import ComputerUseProvider
from tools.computer_use.cua_backend_driver import CuaDriverProvider

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = "cua"
# The built-in already has a hand-written ``hermes tools`` row (with its install post-setup).
_BUILTIN_NAMES = frozenset({DEFAULT_BACKEND})

_registry: ProviderRegistry[ComputerUseProvider] = ProviderRegistry(
    label="Computer use", provider_cls=ComputerUseProvider, logger=logger, normalize=lower_key,
)
_registry.export(globals())
_registry.register(CuaDriverProvider())


def configured_backend_name() -> str:
    """``computer_use.backend`` from the active profile's config.yaml (``cua`` when unset)."""
    from hermes_cli.config import load_config_readonly

    raw = ((load_config_readonly() or {}).get("computer_use") or {}).get("backend")
    return lower_key(raw) if isinstance(raw, str) and raw.strip() else DEFAULT_BACKEND


def get_active_provider() -> ComputerUseProvider:
    """The provider ``computer_use.backend`` names; ``LookupError`` when none is registered under it."""
    name = configured_backend_name()
    provider = _registry.get_provider(name)
    if provider is None:
        from hermes_cli.plugins import _ensure_plugins_discovered

        _ensure_plugins_discovered()  # CLI paths (doctor/status) may reach here before discovery ran
        provider = _registry.get_provider(name)
    if provider is None:
        available = ", ".join(p.name for p in _registry.list_providers())
        raise LookupError(
            f"computer_use.backend is {name!r}, but no computer-use backend is registered under that name "
            f"(available: {available}). Enable the plugin that provides it (`hermes plugins enable <plugin>`) "
            "or pick a backend with `hermes tools`.")
    return provider
