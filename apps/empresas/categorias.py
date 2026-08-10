"""Regras compartilhadas para categorias financeiras."""

import unicodedata

from django.db.models import Q


CATEGORIAS_TRANSFERENCIA = (
    "Entrada de Transferencia",
    "Entrada de Transfer\u00eancia",
    "Saida de Transferencia",
    "Sa\u00edda de Transfer\u00eancia",
)
CATEGORIAS_TRANSFERENCIA_NORMALIZADAS = {
    "entrada de transferencia",
    "saida de transferencia",
}


def normalizar_nome_categoria(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = texto.encode("ascii", "ignore").decode("ascii")
    return " ".join(texto.casefold().split())


def eh_categoria_transferencia(categoria):
    return bool(getattr(categoria, "transferencia", False)) or (
        normalizar_nome_categoria(getattr(categoria, "descricao", ""))
        in CATEGORIAS_TRANSFERENCIA_NORMALIZADAS
    )


def filtro_categorias_transferencia(prefixo=""):
    filtro = Q(**{f"{prefixo}transferencia": True})
    for nome in CATEGORIAS_TRANSFERENCIA:
        filtro |= Q(**{f"{prefixo}descricao__iexact": nome})
    return filtro


def excluir_categorias_transferencia(queryset):
    return queryset.exclude(filtro_categorias_transferencia())
