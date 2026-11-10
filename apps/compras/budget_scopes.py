"""Vertentes do Budget disponíveis em cada módulo."""
TIPOS_COMPRAS = ("produto", "fornecedor")
TIPOS_FINANCEIRO = ("projeto", "departamento", "categoria")


def tipos_modulo(area):
    return TIPOS_FINANCEIRO if area == "financeiro" else TIPOS_COMPRAS


def dimensoes_modulo(area):
    # Preserve budgets saved using the old family aggregation identifier.
    return tipos_modulo(area) + (("familia_produto",) if area == "compras" else ())
