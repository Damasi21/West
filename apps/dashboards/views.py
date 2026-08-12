from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils.dateparse import parse_date

from apps.dashboards.analise_clientes_services import analise_clientes_comercial
from apps.dashboards.budget_services import budget_compras
from apps.dashboards.desempenho_vendedores_services import desempenho_vendedores
from apps.dashboards.dre_services import dre_gerencial
from apps.dashboards.faturamento_services import (
    TIPOS_FATURAMENTO,
    faturamento_comercial,
)
from apps.dashboards.fluxo_caixa_services import (
    fluxo_de_caixa,
    fluxo_de_caixa_horizontal,
)
from apps.dashboards.inadimplencia_services import inadimplencia
from apps.dashboards.margem_rentabilidade_services import (
    margem_rentabilidade_comercial,
)
from apps.dashboards.visao_geral_services import visao_geral_financeira
from apps.empresas.services import (
    areas_permitidas_usuario,
    dashboards_permitidos_usuario,
    empresas_permitidas_no_grupo,
    obter_empresa_permitida,
    usuario_admin_empresa,
    usuario_gestor_empresa,
    usuario_pode_acessar_area,
    usuario_pode_acessar_dashboard,
)


AREAS = {
    "comercial": {
        "titulo": "Comercial",
        "subtitulo": "Vendas, faturamento, clientes e desempenho comercial.",
        "icone": "bi-graph-up-arrow",
        "imagem": "vendas.png",
        "cor": "primary",
        "dashboards": [
            {
                "slug": "faturamento",
                "titulo": "Faturamento",
                "descricao": "Acompanhe faturamento, pedidos emitidos e top itens.",
                "icone": "bi-bar-chart-line",
            },
            {
                "slug": "desempenho-de-vendedores",
                "titulo": "Desempenho de vendedores",
                "descricao": "Compare metas, resultados e produtividade da equipe.",
                "icone": "bi-person-workspace",
            },
            {
                "slug": "analise-de-clientes",
                "titulo": "Análise de clientes",
                "descricao": "Entenda a carteira, recorrência e concentração das vendas.",
                "icone": "bi-people",
            },
            {
                "slug": "margem-e-rentabilidade",
                "titulo": "Margem e Rentabilidade",
                "descricao": "Veja os produtos e categorias com maior participação.",
                "icone": "bi-bullseye",
            },
        ],
    },
    "financeiro": {
        "titulo": "Financeiro",
        "subtitulo": "Receitas, despesas, fluxo de caixa e resultados.",
        "icone": "bi-cash-coin",
        "imagem": "financeiro.png",
        "cor": "success",
        "dashboards": [
            {
                "slug": "fluxo-de-caixa",
                "titulo": "Fluxo de caixa",
                "descricao": "Acompanhe entradas, saídas e saldo ao longo do período.",
                "icone": "bi-arrow-left-right",
            },
            {
                "slug": "dre-gerencial",
                "titulo": "DRE gerencial",
                "descricao": "Visualize receitas, custos, despesas e resultado.",
                "icone": "bi-file-earmark-spreadsheet",
            },
            {
                "slug": "visao-geral",
                "titulo": "Visao Geral",
                "descricao": "Acompanhe recebimentos, pagamentos, resultado e margem.",
                "icone": "bi-columns-gap",
            },
            {
                "slug": "inadimplencia",
                "titulo": "Inadimplencia",
                "descricao": "Monitore exposicao, aging, recuperacao e top devedores.",
                "icone": "bi-exclamation-octagon",
            },
        ],
    },
    "compras": {
        "titulo": "Compras",
        "subtitulo": "Pedidos, fornecedores, prazos e evolução das compras.",
        "icone": "bi-cart-check",
        "imagem": "compras.png",
        "cor": "warning",
        "dashboards": [
            {
                "slug": "budget",
                "titulo": "Budget",
                "descricao": "Compare budget, compras realizadas e itens estourados.",
                "icone": "bi-wallet2",
            },
            {
                "slug": "evolucao-de-compras",
                "titulo": "Evolução de compras",
                "descricao": "Acompanhe valores e volumes comprados por período.",
                "icone": "bi-graph-up",
            },
            {
                "slug": "analise-de-fornecedores",
                "titulo": "Análise de fornecedores",
                "descricao": "Compare participação, preços e desempenho dos parceiros.",
                "icone": "bi-buildings",
            },
            {
                "slug": "pedidos-de-compra",
                "titulo": "Pedidos de compra",
                "descricao": "Visualize pedidos emitidos, pendentes e concluídos.",
                "icone": "bi-clipboard-check",
            },
            {
                "slug": "prazos-de-entrega",
                "titulo": "Prazos de entrega",
                "descricao": "Monitore atrasos e pontualidade dos fornecedores.",
                "icone": "bi-clock-history",
            },
        ],
    },
    "estoque": {
        "titulo": "Estoque",
        "subtitulo": "Posição, giro, cobertura e movimentação dos produtos.",
        "icone": "bi-box-seam",
        "imagem": "estoque.png",
        "cor": "info",
        "dashboards": [
            {
                "slug": "posicao-de-estoque",
                "titulo": "Posição de estoque",
                "descricao": "Consulte saldos, valores e disponibilidade dos itens.",
                "icone": "bi-boxes",
            },
            {
                "slug": "giro-de-estoque",
                "titulo": "Giro de estoque",
                "descricao": "Identifique a velocidade de renovação dos produtos.",
                "icone": "bi-arrow-repeat",
            },
            {
                "slug": "cobertura-de-estoque",
                "titulo": "Cobertura de estoque",
                "descricao": "Estime por quanto tempo os saldos atenderão à demanda.",
                "icone": "bi-calendar-range",
            },
            {
                "slug": "movimentacoes",
                "titulo": "Movimentações",
                "descricao": "Acompanhe entradas, saídas e ajustes realizados.",
                "icone": "bi-arrow-down-up",
            },
        ],
    },
    "crm": {
        "titulo": "CRM",
        "subtitulo": "Funil, oportunidades, atividades e conversões.",
        "icone": "bi-people",
        "imagem": "crm.png",
        "cor": "danger",
        "dashboards": [
            {
                "slug": "funil-de-vendas",
                "titulo": "Funil de vendas",
                "descricao": "Visualize oportunidades em cada etapa comercial.",
                "icone": "bi-funnel",
            },
            {
                "slug": "oportunidades",
                "titulo": "Oportunidades",
                "descricao": "Acompanhe valores, responsáveis e previsão de fechamento.",
                "icone": "bi-bullseye",
            },
            {
                "slug": "atividades-comerciais",
                "titulo": "Atividades comerciais",
                "descricao": "Monitore contatos, tarefas e interações da equipe.",
                "icone": "bi-calendar-check",
            },
            {
                "slug": "taxa-de-conversao",
                "titulo": "Taxa de conversão",
                "descricao": "Analise a eficiência das etapas e origens dos negócios.",
                "icone": "bi-percent",
            },
        ],
    },
}

MESES = (
    (1, "Janeiro"),
    (2, "Fevereiro"),
    (3, "Março"),
    (4, "Abril"),
    (5, "Maio"),
    (6, "Junho"),
    (7, "Julho"),
    (8, "Agosto"),
    (9, "Setembro"),
    (10, "Outubro"),
    (11, "Novembro"),
    (12, "Dezembro"),
)

REGIMES_FINANCEIROS = {
    "caixa": "Caixa",
    "competencia": "Competencia",
}


def _periodos_disponiveis(periodo_selecionado):
    periodos = []
    for ano in range(date.today().year, date.today().year - 6, -1):
        trimestres = []
        for trimestre in range(1, 5):
            meses = []
            primeiro_mes = (trimestre - 1) * 3 + 1
            for numero, nome in MESES[primeiro_mes - 1 : primeiro_mes + 2]:
                valor = f"mes-{ano}-{numero:02d}"
                meses.append(
                    {
                        "nome": nome,
                        "valor": valor,
                        "selecionado": valor == periodo_selecionado,
                    }
                )
            valor_trimestre = f"tri-{ano}-{trimestre}"
            trimestres.append(
                {
                    "numero": trimestre,
                    "valor": valor_trimestre,
                    "selecionado": valor_trimestre == periodo_selecionado,
                    "aberto": valor_trimestre == periodo_selecionado
                    or any(mes["selecionado"] for mes in meses),
                    "meses": meses,
                }
            )
        valor_ano = f"ano-{ano}"
        periodos.append(
            {
                "ano": ano,
                "valor": valor_ano,
                "selecionado": valor_ano == periodo_selecionado,
                "aberto": valor_ano == periodo_selecionado
                or any(
                    trimestre["selecionado"] or trimestre["aberto"]
                    for trimestre in trimestres
                ),
                "trimestres": trimestres,
            }
        )
    return periodos


def _valor_periodo_valido(valor):
    if valor == "personalizado":
        return valor
    valores = {
        periodo["valor"]
        for periodo in _periodos_disponiveis("")
    }
    for periodo in _periodos_disponiveis(""):
        for trimestre in periodo["trimestres"]:
            valores.add(trimestre["valor"])
            valores.update(mes["valor"] for mes in trimestre["meses"])
    return valor if valor in valores else f"ano-{date.today().year}"


def _datas_periodo_especifico(valor, data_inicio, data_fim):
    if valor != "personalizado":
        return "", ""
    inicio = parse_date(data_inicio or "")
    fim = parse_date(data_fim or "")
    if not inicio or not fim or inicio > fim:
        return "", ""
    return inicio.isoformat(), fim.isoformat()


def _rotulo_periodo(valor, data_inicio="", data_fim=""):
    if valor == "personalizado":
        inicio = parse_date(data_inicio)
        fim = parse_date(data_fim)
        if inicio and fim:
            return f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"
        return "Período específico"
    partes = valor.split("-")
    if partes[0] == "ano":
        return partes[1]
    if partes[0] == "tri":
        return f"{partes[1]} · {partes[2]}º trimestre"
    numero_mes = int(partes[2])
    return f"{MESES[numero_mes - 1][1]} de {partes[1]}"


def _valores_validos(selecionados, permitidos):
    permitidos = set(permitidos)
    return [valor for valor in selecionados if valor in permitidos]


def _valores_para_consulta(selecionados, opcoes):
    todos = [item["valor"] for item in opcoes]
    if not selecionados or set(selecionados) == set(todos):
        return []
    return selecionados


def _regime_financeiro_valido(valor):
    return valor if valor in REGIMES_FINANCEIROS else "caixa"


def _chave_empresas_inicio(empresa):
    return f"filtros_inicio:{empresa.pk}:empresas"


def _empresas_inicio_selecionadas(request, empresa, empresas):
    return _valores_validos(
        request.session.get(_chave_empresas_inicio(empresa), [str(empresa.pk)]),
        (str(item.pk) for item in empresas),
    )


def _contexto_base(request, empresa_slug):
    empresa = obter_empresa_permitida(request.user, empresa_slug)
    return {
        "empresa": empresa,
        "areas": areas_permitidas_usuario(request.user, empresa, AREAS),
        "pode_administrar_empresa": usuario_admin_empresa(request.user, empresa),
        "pode_ver_parametros": usuario_gestor_empresa(request.user, empresa),
    }


@login_required
def home(request, empresa_slug):
    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    empresas = list(empresas_permitidas_no_grupo(request.user, empresa))

    if "limpar_filtros" in request.GET:
        empresas_selecionadas = [str(item.pk) for item in empresas]
        request.session[_chave_empresas_inicio(empresa)] = empresas_selecionadas
    elif "_filtrar_empresas" in request.GET:
        empresas_selecionadas = _valores_validos(
            request.GET.getlist("empresa"),
            (str(item.pk) for item in empresas),
        )
        request.session[_chave_empresas_inicio(empresa)] = empresas_selecionadas
    else:
        empresas_selecionadas = _empresas_inicio_selecionadas(
            request,
            empresa,
            empresas,
        )

    contexto.update(
        {
            "empresas_filtro": empresas,
            "empresas_selecionadas": empresas_selecionadas,
        }
    )
    return render(
        request,
        "dashboards/home.html",
        contexto,
    )

@login_required
def area(request, empresa_slug, area_slug):
    area_atual = AREAS.get(area_slug)
    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    if area_atual is None or not usuario_pode_acessar_area(
        request.user,
        empresa,
        area_slug,
    ):
        raise Http404("Area de dashboards nao encontrada.")
    contexto.update(
        {
            "area_slug": area_slug,
            "area_atual": {
                **area_atual,
                "dashboards": dashboards_permitidos_usuario(
                    request.user,
                    empresa,
                    area_slug,
                    area_atual["dashboards"],
                ),
            },
        }
    )
    return render(request, "dashboards/area.html", contexto)

@login_required
def dashboard(request, empresa_slug, area_slug, dashboard_slug):
    area_atual = AREAS.get(area_slug)
    if area_atual is None:
        raise Http404("Área de dashboards não encontrada.")

    dashboard_atual = next(
        (
            item
            for item in area_atual["dashboards"]
            if item["slug"] == dashboard_slug
        ),
        None,
    )
    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    if dashboard_atual is None or not usuario_pode_acessar_dashboard(
        request.user,
        empresa,
        area_slug,
        dashboard_slug,
    ):
        raise Http404("Dashboard nao encontrado.")

    empresas = list(empresas_permitidas_no_grupo(request.user, empresa))
    chave_dashboard = (
        f"filtros_dashboard:{empresa.pk}:{area_slug}:{dashboard_slug}"
    )
    chave_modulo = f"filtros_modulo:{empresa.pk}:{area_slug}"
    estado = request.session.get(chave_dashboard, {})
    estado_modulo = request.session.get(chave_modulo, {})
    periodo_compartilhado = estado_modulo.get("periodo")

    empresas_selecionadas = _empresas_inicio_selecionadas(
        request,
        empresa,
        empresas,
    )

    empresas_consulta_ids = empresas_selecionadas or [
        str(item.pk) for item in empresas
    ]
    from apps.empresas.models import DepartamentoOmie, ProjetoOmie, VendedorOmie

    projetos = ProjetoOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
        ativo_omie=True,
        inativo=False,
    ).select_related("empresa")
    departamentos = DepartamentoOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
        ativo_omie=True,
        inativo=False,
    ).select_related("empresa")
    vendedores = VendedorOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
        ativo_omie=True,
        inativo=False,
    ).select_related("empresa")

    projetos_opcoes = [
        {
            "valor": f"{projeto.empresa_id}:{projeto.codigo}",
            "nome": projeto.nome,
            "empresa": projeto.empresa.nome_fantasia,
        }
        for projeto in projetos
    ]
    departamentos_opcoes = [
        {
            "valor": f"{departamento.empresa_id}:{departamento.codigo}",
            "nome": departamento.descricao,
            "empresa": departamento.empresa.nome_fantasia,
        }
        for departamento in departamentos
    ]
    vendedores_opcoes = [
        {
            "valor": f"{vendedor.empresa_id}:{vendedor.codigo}",
            "nome": vendedor.nome or str(vendedor.codigo),
            "empresa": vendedor.empresa.nome_fantasia,
        }
        for vendedor in vendedores
    ]
    tipos_faturamento_opcoes = [
        {"valor": valor, "nome": rotulo, "empresa": ""}
        for valor, rotulo in TIPOS_FATURAMENTO.items()
    ]

    if "limpar_filtros" in request.GET:
        projetos_selecionados = [item["valor"] for item in projetos_opcoes]
        departamentos_selecionados = [
            item["valor"] for item in departamentos_opcoes
        ]
        vendedores_selecionados = [item["valor"] for item in vendedores_opcoes]
        tipos_faturamento_selecionados = list(TIPOS_FATURAMENTO)
        budget_dimensao = "produto"
        periodo_selecionado = f"ano-{date.today().year}"
        regime_financeiro = _regime_financeiro_valido("")
        data_inicio, data_fim = "", ""
        estado = {
            "periodo": periodo_selecionado,
            "regime_financeiro": regime_financeiro,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "projetos": projetos_selecionados,
            "departamentos": departamentos_selecionados,
            "vendedores": vendedores_selecionados,
            "tipos_faturamento": tipos_faturamento_selecionados,
            "budget_dimensao": budget_dimensao,
        }
        request.session[chave_dashboard] = estado
    elif "_filtrar" in request.GET:
        projetos_selecionados = _valores_validos(
            request.GET.getlist("projeto"),
            (item["valor"] for item in projetos_opcoes),
        )
        departamentos_selecionados = _valores_validos(
            request.GET.getlist("departamento"),
            (item["valor"] for item in departamentos_opcoes),
        )
        vendedores_selecionados = _valores_validos(
            request.GET.getlist("vendedor"),
            (item["valor"] for item in vendedores_opcoes),
        )
        tipos_faturamento_selecionados = _valores_validos(
            request.GET.getlist("tipo_faturamento"),
            TIPOS_FATURAMENTO.keys(),
        ) or list(TIPOS_FATURAMENTO)
        budget_dimensao = request.GET.get("budget_dimensao", "")
        periodo_selecionado = _valor_periodo_valido(
            request.GET.get("periodo", "")
        )
        regime_financeiro = _regime_financeiro_valido(
            request.GET.get("regime_financeiro", "")
        )
        data_inicio, data_fim = _datas_periodo_especifico(
            periodo_selecionado,
            request.GET.get("data_inicio"),
            request.GET.get("data_fim"),
        )
        if periodo_selecionado == "personalizado" and not data_inicio:
            periodo_selecionado = _valor_periodo_valido("")
        estado = {
            "periodo": periodo_selecionado,
            "regime_financeiro": regime_financeiro,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "projetos": projetos_selecionados,
            "departamentos": departamentos_selecionados,
            "vendedores": vendedores_selecionados,
            "tipos_faturamento": tipos_faturamento_selecionados,
            "budget_dimensao": budget_dimensao,
        }
        request.session[chave_dashboard] = estado
    else:
        projetos_selecionados = _valores_validos(
            estado.get("projetos", []),
            (item["valor"] for item in projetos_opcoes),
        )
        departamentos_selecionados = _valores_validos(
            estado.get("departamentos", []),
            (item["valor"] for item in departamentos_opcoes),
        )
        vendedores_selecionados = _valores_validos(
            estado.get("vendedores", []),
            (item["valor"] for item in vendedores_opcoes),
        )
        tipos_faturamento_selecionados = _valores_validos(
            estado.get("tipos_faturamento", list(TIPOS_FATURAMENTO)),
            TIPOS_FATURAMENTO.keys(),
        ) or list(TIPOS_FATURAMENTO)
        budget_dimensao = estado.get("budget_dimensao", "")
        fonte_periodo = estado if estado.get("periodo") else estado_modulo
        periodo_selecionado = _valor_periodo_valido(
            fonte_periodo.get("periodo") or periodo_compartilhado or ""
        )
        regime_financeiro = _regime_financeiro_valido(
            estado.get("regime_financeiro", "")
        )
        data_inicio, data_fim = _datas_periodo_especifico(
            periodo_selecionado,
            fonte_periodo.get("data_inicio"),
            fonte_periodo.get("data_fim"),
        )
        if periodo_selecionado == "personalizado" and not data_inicio:
            periodo_selecionado = _valor_periodo_valido("")

    projetos_consulta = _valores_para_consulta(
        projetos_selecionados,
        projetos_opcoes,
    )
    vendedores_consulta = _valores_para_consulta(
        vendedores_selecionados,
        vendedores_opcoes,
    )
    tipos_faturamento_consulta = _valores_para_consulta(
        tipos_faturamento_selecionados,
        tipos_faturamento_opcoes,
    ) or list(TIPOS_FATURAMENTO)

    periodo_foi_compartilhado = "compartilhar_periodo" in request.GET
    if periodo_foi_compartilhado:
        request.session[chave_modulo] = {
            "periodo": periodo_selecionado,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
        }
        prefixo = f"filtros_dashboard:{empresa.pk}:{area_slug}:"
        for chave in list(request.session.keys()):
            if chave.startswith(prefixo):
                filtros_dashboard = request.session.get(chave, {})
                filtros_dashboard["periodo"] = periodo_selecionado
                filtros_dashboard["data_inicio"] = data_inicio
                filtros_dashboard["data_fim"] = data_fim
                request.session[chave] = filtros_dashboard

    contexto.update(
        {
            "area_slug": area_slug,
            "area_atual": area_atual,
            "dashboard_slug": dashboard_slug,
            "dashboard_atual": dashboard_atual,
            "periodos": _periodos_disponiveis(periodo_selecionado),
            "periodo_selecionado": periodo_selecionado,
            "periodo_rotulo": _rotulo_periodo(
                periodo_selecionado,
                data_inicio,
                data_fim,
            ),
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "regime_financeiro": regime_financeiro,
            "regime_financeiro_rotulo": REGIMES_FINANCEIROS[regime_financeiro],
            "regimes_financeiros": REGIMES_FINANCEIROS,
            "periodo_foi_compartilhado": periodo_foi_compartilhado,
            "periodo_compartilhado": (
                request.session.get(chave_modulo, {}).get("periodo")
                == periodo_selecionado
                and (
                    periodo_selecionado != "personalizado"
                    or (
                        request.session.get(chave_modulo, {}).get("data_inicio")
                        == data_inicio
                        and request.session.get(chave_modulo, {}).get("data_fim")
                        == data_fim
                    )
                )
            ),
            "projetos": projetos_opcoes,
            "projetos_selecionados": projetos_selecionados,
            "departamentos": departamentos_opcoes,
            "departamentos_selecionados": departamentos_selecionados,
            "vendedores": vendedores_opcoes,
            "vendedores_selecionados": vendedores_selecionados,
            "tipos_faturamento": tipos_faturamento_opcoes,
            "tipos_faturamento_selecionados": tipos_faturamento_selecionados,
            "budget_dimensao": budget_dimensao,
            "empresas_filtro": empresas,
            "empresas_selecionadas": empresas_selecionadas,
        }
    )
    if area_slug == "compras" and dashboard_slug == "budget":
        contexto["budget"] = budget_compras(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            budget_dimensao,
        )
    if area_slug == "comercial" and dashboard_slug == "faturamento":
        contexto["faturamento"] = faturamento_comercial(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
            tipos_faturamento_consulta,
            vendedores_consulta,
        )
    if area_slug == "comercial" and dashboard_slug == "desempenho-de-vendedores":
        contexto["desempenho_vendedores"] = desempenho_vendedores(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
            vendedores_consulta,
            tipos_faturamento_consulta,
        )
    if area_slug == "comercial" and dashboard_slug == "analise-de-clientes":
        contexto["analise_clientes"] = analise_clientes_comercial(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
        )
    if area_slug == "comercial" and dashboard_slug == "margem-e-rentabilidade":
        contexto["margem_rentabilidade"] = margem_rentabilidade_comercial(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
        )
    if area_slug == "financeiro" and dashboard_slug == "dre-gerencial":
        contexto["dre_gerencial"] = dre_gerencial(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
            regime_financeiro,
        )
    if area_slug == "financeiro" and dashboard_slug == "visao-geral":
        contexto["visao_geral"] = visao_geral_financeira(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
            regime_financeiro,
        )
    if area_slug == "financeiro" and dashboard_slug == "fluxo-de-caixa":
        contexto["fluxo_caixa"] = fluxo_de_caixa(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
        )
    if area_slug == "financeiro" and dashboard_slug == "inadimplencia":
        contexto["inadimplencia"] = inadimplencia(
            empresa,
            periodo_selecionado,
            data_inicio,
            data_fim,
            empresas_consulta_ids,
            projetos_consulta,
        )
    return render(request, "dashboards/dashboard.html", contexto)


@login_required
def fluxo_caixa_horizontal(request, empresa_slug):
    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    if not usuario_pode_acessar_dashboard(
        request.user,
        empresa,
        "financeiro",
        "fluxo-de-caixa",
    ):
        raise Http404("Dashboard nao encontrado.")

    empresas = list(empresas_permitidas_no_grupo(request.user, empresa))
    empresas_selecionadas = _empresas_inicio_selecionadas(
        request,
        empresa,
        empresas,
    )
    empresas_consulta_ids = empresas_selecionadas or [
        str(item.pk) for item in empresas
    ]
    chave_dashboard = f"filtros_dashboard:{empresa.pk}:financeiro:fluxo-de-caixa"
    estado = request.session.get(chave_dashboard, {})

    from apps.empresas.models import ProjetoOmie

    projetos = ProjetoOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
        ativo_omie=True,
        inativo=False,
    ).select_related("empresa")
    projetos_opcoes = [
        {
            "valor": f"{projeto.empresa_id}:{projeto.codigo}",
            "nome": projeto.nome,
            "empresa": projeto.empresa.nome_fantasia,
        }
        for projeto in projetos
    ]
    if request.GET.getlist("projeto"):
        projetos_selecionados = _valores_validos(
            request.GET.getlist("projeto"),
            (item["valor"] for item in projetos_opcoes),
        )
    else:
        projetos_selecionados = _valores_validos(
            estado.get("projetos", []),
            (item["valor"] for item in projetos_opcoes),
        )
    projetos_consulta = _valores_para_consulta(
        projetos_selecionados,
        projetos_opcoes,
    )

    hoje = date.today()
    modo = request.GET.get("modo") or "diario"
    if modo not in {"diario", "semanal", "anual"}:
        modo = "diario"
    try:
        ano_selecionado = int(request.GET.get("ano") or hoje.year)
    except (TypeError, ValueError):
        ano_selecionado = hoje.year
    ano_selecionado = min(max(ano_selecionado, hoje.year - 5), hoje.year + 1)
    try:
        mes_selecionado = int(request.GET.get("mes") or hoje.month)
    except (TypeError, ValueError):
        mes_selecionado = hoje.month
    mes_selecionado = min(max(mes_selecionado, 1), 12)
    if modo == "anual":
        periodo_selecionado = f"ano-{ano_selecionado}"
        data_inicio, data_fim = "", ""
    else:
        periodo_selecionado = f"mes-{ano_selecionado}-{mes_selecionado:02d}"
        data_inicio, data_fim = "", ""
    anos_filtro = list(range(hoje.year + 1, hoje.year - 6, -1))
    meses_filtro = [
        {"valor": indice, "nome": nome}
        for indice, nome in enumerate(
            (
                "Janeiro",
                "Fevereiro",
                "Marco",
                "Abril",
                "Maio",
                "Junho",
                "Julho",
                "Agosto",
                "Setembro",
                "Outubro",
                "Novembro",
                "Dezembro",
            ),
            start=1,
        )
    ]

    contexto.update(
        {
            "area_slug": "financeiro",
            "area_atual": AREAS["financeiro"],
            "dashboard_slug": "fluxo-de-caixa-horizontal",
            "dashboard_atual": {
                "titulo": "Fluxo de caixa horizontal",
                "descricao": "Pagamentos e recebimentos por periodo.",
            },
            "periodo_rotulo": _rotulo_periodo(
                periodo_selecionado,
                data_inicio,
                data_fim,
            ),
            "modo_horizontal": modo,
            "ano_horizontal": ano_selecionado,
            "mes_horizontal": mes_selecionado,
            "anos_horizontal": anos_filtro,
            "meses_horizontal": meses_filtro,
            "fluxo_horizontal": fluxo_de_caixa_horizontal(
                empresa,
                periodo_selecionado,
                data_inicio,
                data_fim,
                empresas_consulta_ids,
                projetos_consulta,
                modo,
            ),
        }
    )
    return render(request, "dashboards/fluxo_caixa_horizontal.html", contexto)
