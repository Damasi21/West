from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils.dateparse import parse_date

from apps.empresas.services import empresas_permitidas, obter_empresa_permitida


AREAS = {
    "comercial": {
        "titulo": "Comercial",
        "subtitulo": "Vendas, faturamento, clientes e desempenho comercial.",
        "icone": "bi-graph-up-arrow",
        "imagem": "vendas.png",
        "cor": "primary",
        "dashboards": [
            {
                "slug": "visao-de-vendas",
                "titulo": "Visão de vendas",
                "descricao": "Acompanhe vendas, faturamento e evolução comercial.",
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
                "slug": "produtos-vendidos",
                "titulo": "Produtos vendidos",
                "descricao": "Veja os produtos e categorias com maior participação.",
                "icone": "bi-box-seam",
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
                "slug": "contas-a-receber",
                "titulo": "Contas a receber",
                "descricao": "Monitore vencimentos, recebimentos e inadimplência.",
                "icone": "bi-wallet2",
            },
            {
                "slug": "contas-a-pagar",
                "titulo": "Contas a pagar",
                "descricao": "Controle compromissos, vencimentos e pagamentos.",
                "icone": "bi-receipt",
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


def _contexto_base(request, empresa_slug):
    return {
        "empresa": obter_empresa_permitida(request.user, empresa_slug),
        "areas": AREAS,
    }


@login_required
def home(request, empresa_slug):
    return render(
        request,
        "dashboards/home.html",
        _contexto_base(request, empresa_slug),
    )


@login_required
def area(request, empresa_slug, area_slug):
    area_atual = AREAS.get(area_slug)
    if area_atual is None:
        raise Http404("Área de dashboards não encontrada.")

    contexto = _contexto_base(request, empresa_slug)
    contexto.update({"area_slug": area_slug, "area_atual": area_atual})
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
    if dashboard_atual is None:
        raise Http404("Dashboard não encontrado.")

    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    empresas = list(empresas_permitidas(request.user))
    chave_dashboard = (
        f"filtros_dashboard:{empresa.pk}:{area_slug}:{dashboard_slug}"
    )
    chave_modulo = f"filtros_modulo:{empresa.pk}:{area_slug}"
    estado = request.session.get(chave_dashboard, {})
    estado_modulo = request.session.get(chave_modulo, {})
    periodo_compartilhado = estado_modulo.get("periodo")

    if "_filtrar" in request.GET:
        empresas_selecionadas = _valores_validos(
            request.GET.getlist("empresa"),
            (str(item.pk) for item in empresas),
        )
    else:
        empresas_selecionadas = _valores_validos(
            estado.get("empresas", [str(empresa.pk)]),
            (str(item.pk) for item in empresas),
        )

    empresas_consulta_ids = empresas_selecionadas or [
        str(item.pk) for item in empresas
    ]
    from apps.empresas.models import DepartamentoOmie, ProjetoOmie

    projetos = ProjetoOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
        inativo=False,
    ).select_related("empresa")
    departamentos = DepartamentoOmie.objects.filter(
        empresa_id__in=empresas_consulta_ids,
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

    if "_filtrar" in request.GET:
        projetos_selecionados = _valores_validos(
            request.GET.getlist("projeto"),
            (item["valor"] for item in projetos_opcoes),
        )
        departamentos_selecionados = _valores_validos(
            request.GET.getlist("departamento"),
            (item["valor"] for item in departamentos_opcoes),
        )
        periodo_selecionado = _valor_periodo_valido(
            request.GET.get("periodo", "")
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
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "projetos": projetos_selecionados,
            "departamentos": departamentos_selecionados,
            "empresas": empresas_selecionadas,
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
        fonte_periodo = estado if estado.get("periodo") else estado_modulo
        periodo_selecionado = _valor_periodo_valido(
            fonte_periodo.get("periodo") or periodo_compartilhado or ""
        )
        data_inicio, data_fim = _datas_periodo_especifico(
            periodo_selecionado,
            fonte_periodo.get("data_inicio"),
            fonte_periodo.get("data_fim"),
        )
        if periodo_selecionado == "personalizado" and not data_inicio:
            periodo_selecionado = _valor_periodo_valido("")

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
            "empresas_filtro": empresas,
            "empresas_selecionadas": empresas_selecionadas,
        }
    )
    return render(request, "dashboards/dashboard.html", contexto)
