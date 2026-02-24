"""
adapters/__init__.py
Registro central de adapters por nome de fonte.
"""

from .base import AdapterBase
from adapters.planalto import AdapterPlanalto
from adapters.senado import AdapterSenado
from adapters.camara import AdapterCamara

_REGISTRY: dict[str, type[AdapterBase]] = {
    "planalto": AdapterPlanalto,
    "senado":   AdapterSenado,
    "camara":   AdapterCamara,
}


def get_adapter(fonte: str) -> AdapterBase:
    cls = _REGISTRY.get(fonte.lower())
    if cls is None:
        fontes_disponiveis = ", ".join(_REGISTRY.keys())
        raise ValueError(
            f"Fonte '{fonte}' não reconhecida. "
            f"Disponíveis: {fontes_disponiveis}"
        )
    return cls()


def listar_fontes() -> list[str]:
    return list(_REGISTRY.keys())