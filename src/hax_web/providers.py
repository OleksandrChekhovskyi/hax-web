from __future__ import annotations

import os
from typing import Final, Optional

from . import Provider, WebError, codex, deepseek, exa

PROVIDER_ENV: Final = "HAX_WEB_PROVIDER"

# Auto-detection picks the first available provider in this order.
PROVIDERS: Final[dict[str, Provider]] = {"exa": exa, "deepseek": deepseek, "codex": codex}


def requested_provider(flag: Optional[str]) -> Optional[str]:
    """The provider named by --provider or else the environment, or None to auto-detect."""
    name = flag or os.environ.get(PROVIDER_ENV)
    if name and name not in PROVIDERS:
        choices = ", ".join(PROVIDERS)
        raise WebError(f"{PROVIDER_ENV}: unknown provider '{name}' (choose from {choices})")
    return name or None


def unavailable_reasons() -> dict[str, Optional[str]]:
    return {name: provider.unavailable() for name, provider in PROVIDERS.items()}


def first_available(reasons: dict[str, Optional[str]]) -> Optional[str]:
    return next((name for name, reason in reasons.items() if reason is None), None)


def select_provider(flag: Optional[str]) -> Provider:
    """Resolve the provider to use. An explicitly named one is returned even when unavailable, so
    its own error explains what is missing."""
    name = requested_provider(flag)
    if name is None:
        reasons = unavailable_reasons()
        name = first_available(reasons)
        if name is None:
            details = "; ".join(f"{other}: {reason}" for other, reason in reasons.items())
            raise WebError(f"no provider is available ({details})")
    return PROVIDERS[name]


def describe_providers() -> str:
    requested = requested_provider(None)
    reasons = unavailable_reasons()
    width = max(map(len, PROVIDERS))
    lines = [f"{name:<{width}}  {reason or 'ready'}" for name, reason in reasons.items()]
    if requested is not None:
        lines.extend(["", f"Selected: {requested} (from {PROVIDER_ENV})"])
    elif (available := first_available(reasons)) is not None:
        lines.extend(["", f"Selected: {available} (auto-detected)"])
    else:
        lines.extend(["", "No provider is available."])
    return "\n".join(lines) + "\n"
