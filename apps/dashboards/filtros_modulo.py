"""Only share controls actually offered by both dashboard filter bars."""


def campos_compartilhados(area, dashboard):
    campos = {"periodo", "data_inicio", "data_fim", "projetos", "departamentos"}
    if area == "financeiro":
        campos.add("categorias")
        if dashboard == "aprovacao-de-pagamentos":
            return {"categorias"}
    if area == "compras" and dashboard == "budget":
        campos.difference_update({"projetos", "departamentos"})
        campos.add("budget_dimensao")
    if area == "comercial":
        if dashboard in {"faturamento", "desempenho-de-vendedores"}:
            campos.add("vendedores")
        if dashboard == "faturamento":
            campos.add("tipos_faturamento")
        if dashboard == "margem-e-rentabilidade":
            campos.add("familias_produtos")
    if area == "estoque" and dashboard == "curva-abc":
        campos.update({"curva_abc_tipo", "curva_abc_classe_a", "curva_abc_classe_b"})
    return campos


def compartilhamento_ativo(estado_modulo):
    # Preserve the previous period-sharing setting for existing sessions.
    return bool(estado_modulo.get("ativo", bool(estado_modulo.get("periodo"))))


def herdar_filtros(estado, estado_modulo, area, dashboard):
    resultado = dict(estado)
    if compartilhamento_ativo(estado_modulo):
        resultado.update({k: estado_modulo[k] for k in campos_compartilhados(area, dashboard) if k in estado_modulo})
    return resultado
