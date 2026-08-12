from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.empresas.models import (
    CadastroOmie,
    CategoriaOmie,
    DepartamentoOmie,
    Empresa,
    IntegracaoOmie,
    PedidoCompraItemOmie,
    ProdutoOmie,
    ProjetoOmie,
)
from apps.empresas.omie import OmieAPIError, consultar_orcamentos_categorias
from apps.empresas.services import usuario_gestor_empresa

from .models import BudgetConfiguracaoCompra, BudgetLimiteCompra

MODALIDADE_INDIVIDUAL = "individual"
MODALIDADE_GRUPO = "grupo"
MODALIDADES_BUDGET = {MODALIDADE_INDIVIDUAL, MODALIDADE_GRUPO}
PERIODICIDADE_ANUAL = "anual"
PERIODICIDADE_MENSAL = "mensal"
PERIODICIDADES_BUDGET = {PERIODICIDADE_ANUAL, PERIODICIDADE_MENSAL}
MESES_BUDGET = (
    (1, "Jan"),
    (2, "Fev"),
    (3, "Mar"),
    (4, "Abr"),
    (5, "Mai"),
    (6, "Jun"),
    (7, "Jul"),
    (8, "Ago"),
    (9, "Set"),
    (10, "Out"),
    (11, "Nov"),
    (12, "Dez"),
)
CARDS_BUDGET = {
    BudgetConfiguracaoCompra.TipoControle.PRODUTO: {
        "titulo": "Budget por familia de produtos",
        "etiqueta": "Familia",
        "icone": "bi-box-seam",
        "tom": "blue",
    },
    BudgetConfiguracaoCompra.TipoControle.PROJETO: {
        "titulo": "Budget de Projetos",
        "etiqueta": "Projeto",
        "icone": "bi-kanban",
        "tom": "green",
    },
    BudgetConfiguracaoCompra.TipoControle.FORNECEDOR: {
        "titulo": "Teto por fornecedor",
        "etiqueta": "Fornecedor",
        "icone": "bi-shield-check",
        "tom": "amber",
    },
    BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO: {
        "titulo": "Budget por Departamentos",
        "etiqueta": "Departamento",
        "icone": "bi-diagram-3",
        "tom": "cyan",
    },
    BudgetConfiguracaoCompra.TipoControle.CATEGORIA: {
        "titulo": "Budget por categoria",
        "etiqueta": "Categoria",
        "icone": "bi-tags",
        "tom": "violet",
    },
}
QUATRO_CASAS = Decimal("0.0001")


class ValorBudgetIncompativel(ValueError):
    pass


class ModalidadeBudgetBloqueada(ValueError):
    pass


def _exigir_gestor_empresa(request, empresa):
    if not usuario_gestor_empresa(request.user, empresa):
        raise PermissionDenied


def _redirect_budget(empresa, tipo_controle=None):
    url = reverse("dashboards:budget", kwargs={"empresa_slug": empresa.slug})
    if tipo_controle in BudgetConfiguracaoCompra.TipoControle.values:
        url = f"{url}?budget_tipo={tipo_controle}"
    return redirect(url)


def _tipo_ativo_request(request, configuracao):
    tipo = (
        request.POST.get("tipo_ativo")
        or request.POST.get("tipo_controle")
        or request.GET.get("budget_tipo")
    )
    if tipo in BudgetConfiguracaoCompra.TipoControle.values:
        return tipo
    return None


def _decimal_post(valor):
    normalizado = (valor or "").replace(".", "").replace(",", ".").strip()
    try:
        return max(Decimal(normalizado or "0"), Decimal("0"))
    except (InvalidOperation, ValueError):
        raise ValueError


def _modalidade_secao(configuracao, tipo_controle):
    modalidade = (configuracao.modalidades_controle or {}).get(tipo_controle)
    return modalidade if modalidade in MODALIDADES_BUDGET else MODALIDADE_INDIVIDUAL


def _chave_budget_mensal(tipo_controle, mes):
    return f"{tipo_controle}:mes:{mes}"


def _chave_total_grupo(tipo_controle, periodicidade, mes):
    if periodicidade == PERIODICIDADE_MENSAL:
        return _chave_budget_mensal(tipo_controle, mes)
    return tipo_controle


def _total_grupo_secao(
    configuracao,
    tipo_controle,
    periodicidade=PERIODICIDADE_ANUAL,
    mes=0,
):
    chave = _chave_total_grupo(tipo_controle, periodicidade, mes)
    valor = (configuracao.totais_grupo or {}).get(chave, "0")
    if isinstance(valor, dict):
        return sum(
            (
                max(Decimal(str(item or "0")), Decimal("0"))
                for item in valor.values()
            ),
            Decimal("0"),
        )
    try:
        return max(Decimal(str(valor or "0")), Decimal("0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _totais_grupo_produtos(
    configuracao,
    periodicidade=PERIODICIDADE_ANUAL,
    mes=0,
):
    chave = _chave_total_grupo(
        BudgetConfiguracaoCompra.TipoControle.PRODUTO,
        periodicidade,
        mes,
    )
    valores = (configuracao.totais_grupo or {}).get(chave, {})
    return valores if isinstance(valores, dict) else {}


def _total_grupo_familia(
    configuracao,
    familia_codigo,
    periodicidade=PERIODICIDADE_ANUAL,
    mes=0,
):
    valor = _totais_grupo_produtos(configuracao, periodicidade, mes).get(
        familia_codigo,
        "0",
    )
    try:
        return max(Decimal(str(valor or "0")), Decimal("0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _periodicidade_secao(configuracao, tipo_controle):
    periodicidade = (configuracao.periodicidades_controle or {}).get(tipo_controle)
    return (
        periodicidade
        if periodicidade in PERIODICIDADES_BUDGET
        else PERIODICIDADE_ANUAL
    )


def _meses_secao(configuracao, tipo_controle):
    meses = (configuracao.meses_controle or {}).get(tipo_controle)
    if not isinstance(meses, list):
        return list(range(1, 13))
    selecionados = []
    for mes in meses:
        try:
            mes_numero = int(mes)
        except (TypeError, ValueError):
            continue
        if 1 <= mes_numero <= 12 and mes_numero not in selecionados:
            selecionados.append(mes_numero)
    return selecionados or list(range(1, 13))


def _mes_edicao_secao(configuracao, tipo_controle):
    meses = _meses_secao(configuracao, tipo_controle)
    return meses[0] if meses else timezone.localdate().month


def _mes_edicao_post(request, tipo_controle, periodicidade):
    if periodicidade != PERIODICIDADE_MENSAL:
        return 0
    valor = (
        request.POST.get(f"mes_edicao_{tipo_controle}")
        or request.POST.get(f"mes_{tipo_controle}")
        or ""
    )
    try:
        mes = int(valor)
    except (TypeError, ValueError):
        raise ValueError
    if mes < 1 or mes > 12:
        raise ValueError
    return mes


def _meses_post(request, tipo_controle, periodicidade):
    mes = _mes_edicao_post(request, tipo_controle, periodicidade)
    if periodicidade != PERIODICIDADE_MENSAL:
        return list(range(1, 13))
    return [mes]


def _opcoes_meses(selecionados):
    selecionados = set(selecionados or [])
    return [
        {"numero": numero, "rotulo": rotulo, "selecionado": numero in selecionados}
        for numero, rotulo in MESES_BUDGET
    ]


def _resumo_meses(selecionados):
    total = len(selecionados or [])
    if total == 12:
        return "Todos os meses"
    if total == 1:
        return "1 selecionado"
    return f"{total} selecionados"


def _rotulo_mes(numero):
    return dict(MESES_BUDGET).get(numero, str(numero))


def _remover_chaves_mensais(dados, tipo_controle):
    dados.pop(tipo_controle, None)
    prefixo = f"{tipo_controle}:mes:"
    for chave in list(dados.keys()):
        if str(chave).startswith(prefixo):
            dados.pop(chave, None)


def _formatar_decimal_input(valor):
    valor = (valor or Decimal("0")).quantize(Decimal("0.01"))
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_moeda(valor):
    valor = (valor or Decimal("0")).quantize(Decimal("0.01"))
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def _linhas_produtos(empresa):
    return [
        {
            "codigo": str(produto.codigo_produto),
            "nome": produto.descricao or produto.codigo or str(produto.codigo_produto),
            "detalhe": produto.codigo,
            "estoque_minimo": produto.estoque_minimo,
            "familia_codigo": (
                str(produto.codigo_familia)
                if produto.codigo_familia is not None
                else "sem_familia"
            ),
            "familia_nome": produto.descricao_familia or "Sem familia",
        }
        for produto in ProdutoOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            inativo=False,
        ).order_by("descricao", "codigo")
    ]


def _linhas_familias(empresa):
    return [
        {
            "codigo": str(familia["codigo_familia"]),
            "nome": familia["descricao_familia"] or str(familia["codigo_familia"]),
            "detalhe": f"{familia['total_produtos']} produtos",
            "estoque_minimo": familia["estoque_minimo"] or Decimal("0"),
        }
        for familia in (
            ProdutoOmie.objects.filter(
                empresa=empresa,
                ativo_omie=True,
                inativo=False,
                codigo_familia__isnull=False,
            )
            .values("codigo_familia", "descricao_familia")
            .annotate(
                estoque_minimo=Sum("estoque_minimo"),
                total_produtos=Count("id"),
            )
            .order_by("descricao_familia", "codigo_familia")
        )
    ]


def _linhas_projetos(empresa):
    return [
        {
            "codigo": str(projeto.codigo),
            "nome": projeto.nome,
            "detalhe": projeto.codigo_integracao,
            "estoque_minimo": Decimal("0"),
        }
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            inativo=False,
        ).order_by("nome", "codigo")
    ]


def _linhas_fornecedores(empresa):
    return [
        {
            "codigo": str(fornecedor.codigo_cliente_omie),
            "nome": fornecedor.razao_social
            or fornecedor.nome_fantasia
            or str(fornecedor.codigo_cliente_omie),
            "detalhe": fornecedor.cnpj_cpf,
            "estoque_minimo": Decimal("0"),
        }
        for fornecedor in CadastroOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            inativo=False,
            tipo__in=[CadastroOmie.Tipo.FORNECEDOR, CadastroOmie.Tipo.AMBOS],
        ).order_by("razao_social", "nome_fantasia")
    ]


def _linhas_departamentos(empresa):
    return [
        {
            "codigo": str(departamento.codigo),
            "nome": departamento.descricao or departamento.codigo,
            "detalhe": departamento.estrutura,
            "estoque_minimo": Decimal("0"),
        }
        for departamento in DepartamentoOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            inativo=False,
        ).order_by("estrutura", "descricao")
    ]


def _linhas_categorias(empresa):
    return [
        {
            "codigo": str(categoria.codigo),
            "nome": categoria.descricao or categoria.codigo,
            "detalhe": (
                f"Superior {categoria.categoria_superior}"
                if categoria.categoria_superior
                else ""
            ),
            "estoque_minimo": Decimal("0"),
        }
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            conta_inativa=False,
            nao_exibir=False,
            codigo__startswith="2",
        ).order_by("codigo", "descricao")
    ]


LINHAS_POR_TIPO = {
    BudgetConfiguracaoCompra.TipoControle.PRODUTO: _linhas_produtos,
    BudgetConfiguracaoCompra.TipoControle.FAMILIA_PRODUTO: _linhas_familias,
    BudgetConfiguracaoCompra.TipoControle.PROJETO: _linhas_projetos,
    BudgetConfiguracaoCompra.TipoControle.FORNECEDOR: _linhas_fornecedores,
    BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO: _linhas_departamentos,
    BudgetConfiguracaoCompra.TipoControle.CATEGORIA: _linhas_categorias,
}


def _codigo_gasto(item, tipo_controle):
    if tipo_controle == BudgetConfiguracaoCompra.TipoControle.PRODUTO:
        return str(item.codigo_produto) if item.codigo_produto is not None else ""
    if tipo_controle == BudgetConfiguracaoCompra.TipoControle.FAMILIA_PRODUTO:
        produto = item.produto
        codigo = produto.codigo_familia if produto else None
        return str(codigo) if codigo is not None else ""
    if tipo_controle == BudgetConfiguracaoCompra.TipoControle.PROJETO:
        codigo = item.pedido.codigo_projeto
        return str(codigo) if codigo is not None else ""
    if tipo_controle == BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO:
        for departamento in item.pedido.departamentos_consulta or []:
            codigo = (
                departamento.get("cCodDep")
                or departamento.get("codigo")
                or departamento.get("nCodDep")
                or departamento.get("nCodDepto")
            )
            if codigo:
                return str(codigo)
        return ""
    if tipo_controle == BudgetConfiguracaoCompra.TipoControle.CATEGORIA:
        return str(item.codigo_categoria or item.pedido.codigo_categoria or "")
    codigo = item.pedido.codigo_fornecedor
    return str(codigo) if codigo is not None else ""


def _gastos_ano_anterior(empresa, tipo_controle):
    ano = timezone.localdate().year - 1
    gastos = {}
    itens = (
        PedidoCompraItemOmie.objects.filter(
            empresa=empresa,
            ativo_omie=True,
            pedido__ativo_omie=True,
            pedido__data_previsao__year=ano,
        )
        .select_related("pedido", "produto")
        .order_by()
    )
    for item in itens:
        codigo = _codigo_gasto(item, tipo_controle)
        if not codigo:
            continue
        gastos[codigo] = gastos.get(codigo, Decimal("0")) + (item.valor_total or Decimal("0"))
    return gastos


def _itens_orcamento_omie(dados):
    if isinstance(dados, list):
        for item in dados:
            yield from _itens_orcamento_omie(item)
    elif isinstance(dados, dict):
        if "cCodCateg" in dados:
            yield dados
        for valor in dados.values():
            if isinstance(valor, (dict, list)):
                yield from _itens_orcamento_omie(valor)


def _buscar_previsto_realizado_categoria(empresa, configuracao, secao, request):
    periodicidade = request.POST.get(
        "periodicidade_categoria",
        PERIODICIDADE_ANUAL,
    )
    if periodicidade not in PERIODICIDADES_BUDGET:
        raise ValueError
    meses = _meses_post(
        request,
        BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
        periodicidade,
    )
    mes_limite = meses[0] if periodicidade == PERIODICIDADE_MENSAL else 0
    ano = timezone.localdate().year
    integracao = IntegracaoOmie.objects.filter(empresa=empresa, ativa=True).first()
    if not integracao:
        raise OmieAPIError("Integracao OMIE ativa nao encontrada.")

    previstos = {}
    for mes in meses:
        dados = consultar_orcamentos_categorias(integracao, ano, mes)
        for item in _itens_orcamento_omie(dados):
            codigo = str(item.get("cCodCateg") or "").strip()
            if not codigo.startswith("2"):
                continue
            previstos[codigo] = previstos.get(codigo, Decimal("0")) + Decimal(
                str(item.get("nValorPrevisto") or "0")
            )

    linhas = {
        linha["codigo"]: linha
        for linha in secao["linhas"]
        if linha["codigo"].startswith("2")
    }
    alterados = 0
    with transaction.atomic():
        for codigo, valor in previstos.items():
            linha = linhas.get(codigo)
            if not linha:
                continue
            BudgetLimiteCompra.objects.update_or_create(
                empresa=empresa,
                configuracao=configuracao,
                tipo_controle=BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
                referencia_codigo=codigo,
                mes=mes_limite,
                defaults={
                    "referencia_nome": linha["nome"],
                    "estoque_minimo": linha["estoque_minimo"],
                    "limite_compra": valor,
                },
            )
            alterados += 1

        periodicidades = dict(configuracao.periodicidades_controle or {})
        meses_controle = dict(configuracao.meses_controle or {})
        periodicidades[BudgetConfiguracaoCompra.TipoControle.CATEGORIA] = periodicidade
        meses_controle[BudgetConfiguracaoCompra.TipoControle.CATEGORIA] = meses
        configuracao.periodicidades_controle = periodicidades
        configuracao.meses_controle = meses_controle
        configuracao.save(
            update_fields=[
                "periodicidades_controle",
                "meses_controle",
                "atualizado_em",
            ]
        )
    return alterados, ano, meses


def _montar_secoes(empresa, configuracao):
    rotulos = dict(BudgetConfiguracaoCompra.TipoControle.choices)
    secoes = []
    total_itens = 0
    total_limite = Decimal("0")
    tipos_selecionados = set(configuracao.tipos_selecionados)
    ordem_tipos = [
        BudgetConfiguracaoCompra.TipoControle.PRODUTO,
        BudgetConfiguracaoCompra.TipoControle.PROJETO,
        BudgetConfiguracaoCompra.TipoControle.FORNECEDOR,
        BudgetConfiguracaoCompra.TipoControle.DEPARTAMENTO,
        BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
    ]
    for tipo_controle in ordem_tipos:
        linhas_base = LINHAS_POR_TIPO[tipo_controle](empresa)
        gastos_anteriores = _gastos_ano_anterior(empresa, tipo_controle)
        periodicidade = _periodicidade_secao(configuracao, tipo_controle)
        mes_edicao = _mes_edicao_secao(configuracao, tipo_controle)
        mes_limite = mes_edicao if periodicidade == PERIODICIDADE_MENSAL else 0
        limites_todos = list(
            BudgetLimiteCompra.objects.filter(
                empresa=empresa,
                tipo_controle=tipo_controle,
            )
        )
        limites_atuais = {
            limite.referencia_codigo: limite
            for limite in limites_todos
            if limite.mes == mes_limite
        }
        tem_budget_salvo = any(
            limite.limite_compra > 0 for limite in limites_todos
        )
        modalidade = _modalidade_secao(configuracao, tipo_controle)
        linhas = []
        for linha in linhas_base:
            limite = limites_atuais.get(linha["codigo"])
            valor = limite.limite_compra if limite else Decimal("0")
            gasto_anterior = gastos_anteriores.get(linha["codigo"], Decimal("0"))
            total_limite += valor
            linhas.append(
                {
                    **linha,
                    "gasto_ano_anterior": gasto_anterior,
                    "gasto_ano_anterior_fmt": _formatar_moeda(gasto_anterior),
                    "limite_compra": valor,
                    "limite_compra_input": _formatar_decimal_input(valor),
                    "selecionado_grupo": valor > 0,
                }
            )
        total_itens += len(linhas)
        meses_selecionados = [mes_edicao]
        familias = []
        if tipo_controle == BudgetConfiguracaoCompra.TipoControle.PRODUTO:
            mapa_familias = {}
            for linha in linhas:
                familia_codigo = linha["familia_codigo"]
                familia = mapa_familias.setdefault(
                    familia_codigo,
                    {
                        "codigo": familia_codigo,
                        "nome": linha["familia_nome"],
                        "linhas": [],
                        "total_limite": Decimal("0"),
                        "total_gasto_anterior": Decimal("0"),
                        "total_grupo": _total_grupo_familia(
                            configuracao,
                            familia_codigo,
                            periodicidade,
                            mes_edicao,
                        ),
                    },
                )
                familia["linhas"].append(linha)
                familia["total_limite"] += linha["limite_compra"]
                familia["total_gasto_anterior"] += linha["gasto_ano_anterior"]
            familias = sorted(
                mapa_familias.values(),
                key=lambda item: (item["nome"] == "Sem familia", item["nome"]),
            )
            for familia in familias:
                familia["total_limite_fmt"] = _formatar_moeda(familia["total_limite"])
                familia["total_gasto_anterior_fmt"] = _formatar_moeda(
                    familia["total_gasto_anterior"]
                )
                familia["total_grupo_input"] = _formatar_decimal_input(
                    familia["total_grupo"]
                )
                familia["selecionado_grupo"] = any(
                    linha["selecionado_grupo"] for linha in familia["linhas"]
                )
        secoes.append(
            {
                "tipo": tipo_controle,
                "titulo": rotulos[tipo_controle],
                "card_titulo": CARDS_BUDGET[tipo_controle]["titulo"],
                "card_etiqueta": CARDS_BUDGET[tipo_controle]["etiqueta"],
                "card_icone": CARDS_BUDGET[tipo_controle]["icone"],
                "card_tom": CARDS_BUDGET[tipo_controle]["tom"],
                "ativo": tipo_controle in tipos_selecionados,
                "linhas": linhas,
                "familias": familias,
                "usa_familias": (
                    tipo_controle == BudgetConfiguracaoCompra.TipoControle.PRODUTO
                ),
                "modalidade": modalidade,
                "tem_budget_salvo": tem_budget_salvo,
                "modalidade_bloqueada": modalidade if tem_budget_salvo else "",
                "total_grupo": _total_grupo_secao(
                    configuracao,
                    tipo_controle,
                    periodicidade,
                    mes_edicao,
                ),
                "total_grupo_input": _formatar_decimal_input(
                    _total_grupo_secao(
                        configuracao,
                        tipo_controle,
                        periodicidade,
                        mes_edicao,
                    )
                ),
                "periodicidade": periodicidade,
                "mes_edicao": mes_edicao,
                "mes_edicao_rotulo": _rotulo_mes(mes_edicao),
                "meses": _opcoes_meses(meses_selecionados),
                "meses_resumo": _resumo_meses(meses_selecionados),
                "total_limite": sum((linha["limite_compra"] for linha in linhas), Decimal("0")),
                "total_limite_fmt": _formatar_moeda(
                    sum((linha["limite_compra"] for linha in linhas), Decimal("0"))
                ),
                "total_gasto_anterior": sum(
                    (linha["gasto_ano_anterior"] for linha in linhas),
                    Decimal("0"),
                ),
                "total_gasto_anterior_fmt": _formatar_moeda(
                    sum((linha["gasto_ano_anterior"] for linha in linhas), Decimal("0"))
                ),
            }
        )
    return secoes, total_itens, total_limite


@login_required
def parametros_budget(request, empresa_slug):
    empresa = get_object_or_404(Empresa, slug=empresa_slug, ativa=True)
    _exigir_gestor_empresa(request, empresa)
    configuracao, _ = BudgetConfiguracaoCompra.objects.get_or_create(empresa=empresa)

    if request.method == "POST" and request.POST.get("acao") == "definir_tipos":
        tipos_controle = request.POST.getlist("tipos_controle")
        tipos_validos = BudgetConfiguracaoCompra.TipoControle.values
        if any(tipo not in tipos_validos for tipo in tipos_controle):
            messages.error(request, "Selecione tipos de controle validos.")
        elif not tipos_controle:
            messages.error(request, "Selecione pelo menos um controle de budget.")
        else:
            configuracao.definir_tipos(tipos_controle)
            configuracao.save(
                update_fields=["tipo_controle", "tipos_controle", "atualizado_em"]
            )
            messages.success(request, "Controles de budget atualizados.")
        return _redirect_budget(empresa)

    secoes, total_itens, total_limite = _montar_secoes(empresa, configuracao)
    budget_tipo_ativo = _tipo_ativo_request(request, configuracao)

    if request.method == "POST" and request.POST.get("acao") == "reverter_budget":
        tipo_reverter = request.POST.get("tipo_controle")
        if tipo_reverter not in BudgetConfiguracaoCompra.TipoControle.values:
            messages.error(request, "Controle de budget invalido para reverter.")
            return _redirect_budget(empresa, budget_tipo_ativo)

        modalidades = dict(configuracao.modalidades_controle or {})
        totais_grupo = dict(configuracao.totais_grupo or {})
        periodicidades = dict(configuracao.periodicidades_controle or {})
        meses_controle = dict(configuracao.meses_controle or {})
        with transaction.atomic():
            BudgetLimiteCompra.objects.filter(
                empresa=empresa,
                tipo_controle=tipo_reverter,
            ).delete()
            modalidades.pop(tipo_reverter, None)
            _remover_chaves_mensais(totais_grupo, tipo_reverter)
            periodicidades.pop(tipo_reverter, None)
            meses_controle.pop(tipo_reverter, None)
            configuracao.modalidades_controle = modalidades
            configuracao.totais_grupo = totais_grupo
            configuracao.periodicidades_controle = periodicidades
            configuracao.meses_controle = meses_controle
            configuracao.save(
                update_fields=[
                    "modalidades_controle",
                    "totais_grupo",
                    "periodicidades_controle",
                    "meses_controle",
                    "atualizado_em",
                ]
            )
        messages.success(request, "Budget revertido. Escolha a modalidade novamente.")
        return _redirect_budget(empresa, tipo_reverter)

    if request.method == "POST" and request.POST.get("acao") == "selecionar_mes_budget":
        tipo_selecionar = request.POST.get("tipo_controle")
        if tipo_selecionar not in BudgetConfiguracaoCompra.TipoControle.values:
            messages.error(request, "Controle de budget invalido para selecionar mes.")
            return _redirect_budget(empresa, budget_tipo_ativo)
        try:
            mes_edicao = int(request.POST.get("mes_edicao") or "0")
            if mes_edicao < 1 or mes_edicao > 12:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, "Escolha um mes valido para carregar.")
            return _redirect_budget(empresa, tipo_selecionar)

        periodicidades = dict(configuracao.periodicidades_controle or {})
        meses_controle = dict(configuracao.meses_controle or {})
        periodicidades[tipo_selecionar] = PERIODICIDADE_MENSAL
        meses_controle[tipo_selecionar] = [mes_edicao]
        configuracao.periodicidades_controle = periodicidades
        configuracao.meses_controle = meses_controle
        configuracao.save(
            update_fields=[
                "periodicidades_controle",
                "meses_controle",
                "atualizado_em",
            ]
        )
        messages.success(
            request,
            f"Budget de {_rotulo_mes(mes_edicao)} carregado.",
        )
        return _redirect_budget(empresa, tipo_selecionar)

    if request.method == "POST" and request.POST.get("acao") == "replicar_budget_mensal":
        tipo_replicar = request.POST.get("tipo_controle")
        if tipo_replicar not in BudgetConfiguracaoCompra.TipoControle.values:
            messages.error(request, "Controle de budget invalido para replicar.")
            return _redirect_budget(empresa, budget_tipo_ativo)
        try:
            mes_origem = int(request.POST.get("mes_origem") or "0")
            if mes_origem < 1 or mes_origem > 12:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, "Escolha um mes valido para replicar.")
            return _redirect_budget(empresa, tipo_replicar)

        limites_origem = list(
            BudgetLimiteCompra.objects.filter(
                empresa=empresa,
                tipo_controle=tipo_replicar,
                mes=mes_origem,
            )
        )
        if not limites_origem:
            messages.error(
                request,
                "Salve o budget deste mes antes de replicar para o ano.",
            )
            return _redirect_budget(empresa, tipo_replicar)

        totais_grupo = dict(configuracao.totais_grupo or {})
        periodicidades = dict(configuracao.periodicidades_controle or {})
        meses_controle = dict(configuracao.meses_controle or {})
        with transaction.atomic():
            for mes_destino in range(1, 13):
                for limite_origem in limites_origem:
                    BudgetLimiteCompra.objects.update_or_create(
                        empresa=empresa,
                        configuracao=configuracao,
                        tipo_controle=tipo_replicar,
                        referencia_codigo=limite_origem.referencia_codigo,
                        mes=mes_destino,
                        defaults={
                            "referencia_nome": limite_origem.referencia_nome,
                            "estoque_minimo": limite_origem.estoque_minimo,
                            "limite_compra": limite_origem.limite_compra,
                        },
                    )

            chave_origem = _chave_budget_mensal(tipo_replicar, mes_origem)
            if chave_origem in totais_grupo:
                for mes_destino in range(1, 13):
                    totais_grupo[
                        _chave_budget_mensal(tipo_replicar, mes_destino)
                    ] = totais_grupo[chave_origem]

            periodicidades[tipo_replicar] = PERIODICIDADE_MENSAL
            meses_controle[tipo_replicar] = [mes_origem]
            configuracao.totais_grupo = totais_grupo
            configuracao.periodicidades_controle = periodicidades
            configuracao.meses_controle = meses_controle
            configuracao.save(
                update_fields=[
                    "totais_grupo",
                    "periodicidades_controle",
                    "meses_controle",
                    "atualizado_em",
                ]
            )
        messages.success(
            request,
            f"Budget de {_rotulo_mes(mes_origem)} replicado para todos os meses do ano.",
        )
        return _redirect_budget(empresa, tipo_replicar)

    if (
        request.method == "POST"
        and request.POST.get("acao") == "buscar_previsto_realizado_categoria"
    ):
        secao_categoria = next(
            (
                secao
                for secao in secoes
                if secao["tipo"] == BudgetConfiguracaoCompra.TipoControle.CATEGORIA
            ),
            None,
        )
        try:
            if not secao_categoria:
                raise ValueError
            alterados, ano, meses = _buscar_previsto_realizado_categoria(
                empresa,
                configuracao,
                secao_categoria,
                request,
            )
        except OmieAPIError as exc:
            messages.error(request, f"Nao foi possivel buscar o previsto no Omie: {exc}")
        except (InvalidOperation, ValueError):
            messages.error(
                request,
                "Informe uma periodicidade valida e ao menos um mes para buscar o previsto.",
            )
        else:
            meses_texto = ", ".join(str(mes) for mes in meses)
            messages.success(
                request,
                f"Previsto x realizado importado para {alterados} categoria(s) de despesa em {ano} mes(es): {meses_texto}.",
            )
            return _redirect_budget(
                empresa,
                BudgetConfiguracaoCompra.TipoControle.CATEGORIA,
            )

    if request.method == "POST" and request.POST.get("acao") == "salvar_limites":
        alteracoes = []
        modalidades = dict(configuracao.modalidades_controle or {})
        totais_grupo = dict(configuracao.totais_grupo or {})
        periodicidades = dict(configuracao.periodicidades_controle or {})
        meses_controle = dict(configuracao.meses_controle or {})
        try:
            with transaction.atomic():
                for secao in secoes:
                    tipo_controle = secao["tipo"]
                    modalidade = request.POST.get(
                        f"modalidade_{tipo_controle}",
                        MODALIDADE_INDIVIDUAL,
                    )
                    if modalidade not in MODALIDADES_BUDGET:
                        raise ValueError
                    if (
                        secao["tem_budget_salvo"]
                        and secao["modalidade_bloqueada"]
                        and modalidade != secao["modalidade_bloqueada"]
                    ):
                        raise ModalidadeBudgetBloqueada
                    modalidades[tipo_controle] = modalidade
                    periodicidade = request.POST.get(
                        f"periodicidade_{tipo_controle}",
                        PERIODICIDADE_ANUAL,
                    )
                    if periodicidade not in PERIODICIDADES_BUDGET:
                        raise ValueError
                    periodicidades[tipo_controle] = periodicidade
                    mes_edicao = _mes_edicao_post(
                        request,
                        tipo_controle,
                        periodicidade,
                    )
                    mes_limite = (
                        mes_edicao if periodicidade == PERIODICIDADE_MENSAL else 0
                    )
                    meses_controle[tipo_controle] = (
                        [mes_edicao]
                        if periodicidade == PERIODICIDADE_MENSAL
                        else list(range(1, 13))
                    )
                    chave_total_grupo = _chave_total_grupo(
                        tipo_controle,
                        periodicidade,
                        mes_edicao,
                    )
                    total_grupo = _decimal_post(
                        request.POST.get(f"total_grupo_{tipo_controle}")
                    )
                    selecionados_grupo = set(
                        request.POST.getlist(f"grupo_item_{tipo_controle}")
                    )
                    valor_rateado = Decimal("0")
                    valores_grupo = {}
                    if (
                        modalidade == MODALIDADE_GRUPO
                        and tipo_controle
                        == BudgetConfiguracaoCompra.TipoControle.PRODUTO
                    ):
                        totais_familias = {}
                        existe_item_selecionado = False
                        for familia in secao["familias"]:
                            familia_codigo = familia["codigo"]
                            total_familia = _decimal_post(
                                request.POST.get(
                                    f"total_grupo_{tipo_controle}_{familia_codigo}"
                                )
                            )
                            totais_familias[familia_codigo] = str(total_familia)
                            selecionados_familia = set(
                                request.POST.getlist(
                                    f"grupo_item_{tipo_controle}_{familia_codigo}"
                                )
                            )
                            existe_item_selecionado = (
                                existe_item_selecionado or bool(selecionados_familia)
                            )
                            linhas_selecionadas = [
                                linha
                                for linha in familia["linhas"]
                                if linha["codigo"] in selecionados_familia
                            ]
                            valores_familia = {}
                            for linha in linhas_selecionadas:
                                codigo = linha["codigo"]
                                campo_limite = f"limite_{tipo_controle}_{codigo}"
                                if campo_limite in request.POST:
                                    valores_familia[codigo] = _decimal_post(
                                        request.POST.get(campo_limite)
                                    )
                            if len(valores_familia) == len(linhas_selecionadas):
                                soma_familia = sum(
                                    valores_familia.values(),
                                    Decimal("0"),
                                )
                                if (
                                    soma_familia.quantize(QUATRO_CASAS)
                                    != total_familia.quantize(QUATRO_CASAS)
                                ):
                                    raise ValorBudgetIncompativel
                            sem_valor_manual = [
                                linha["codigo"]
                                for linha in linhas_selecionadas
                                if linha["codigo"] not in valores_familia
                            ]
                            restante = max(
                                total_familia
                                - sum(valores_familia.values(), Decimal("0")),
                                Decimal("0"),
                            )
                            valor_familia_rateado = Decimal("0")
                            if sem_valor_manual:
                                valor_familia_rateado = (
                                    restante / Decimal(len(sem_valor_manual))
                                ).quantize(QUATRO_CASAS)
                            for linha in familia["linhas"]:
                                codigo = linha["codigo"]
                                if codigo not in selecionados_familia:
                                    valores_grupo[codigo] = Decimal("0")
                                else:
                                    valores_grupo[codigo] = valores_familia.get(
                                        codigo,
                                        valor_familia_rateado,
                                    )
                        if not existe_item_selecionado:
                            raise ValueError
                        totais_grupo[chave_total_grupo] = totais_familias
                    else:
                        totais_grupo[chave_total_grupo] = str(total_grupo)
                    if (
                        modalidade == MODALIDADE_GRUPO
                        and tipo_controle
                        != BudgetConfiguracaoCompra.TipoControle.PRODUTO
                        and not selecionados_grupo
                    ):
                        raise ValueError
                    if (
                        modalidade == MODALIDADE_GRUPO
                        and tipo_controle
                        != BudgetConfiguracaoCompra.TipoControle.PRODUTO
                    ):
                        linhas_selecionadas = [
                            linha
                            for linha in secao["linhas"]
                            if linha["codigo"] in selecionados_grupo
                        ]
                        for linha in linhas_selecionadas:
                            codigo = linha["codigo"]
                            campo_limite = f"limite_{tipo_controle}_{codigo}"
                            if campo_limite in request.POST:
                                valores_grupo[codigo] = _decimal_post(
                                    request.POST.get(campo_limite)
                                )
                        if len(valores_grupo) == len(linhas_selecionadas):
                            soma_grupo = sum(valores_grupo.values(), Decimal("0"))
                            if (
                                soma_grupo.quantize(QUATRO_CASAS)
                                != total_grupo.quantize(QUATRO_CASAS)
                            ):
                                raise ValorBudgetIncompativel
                        sem_valor_manual = [
                            linha["codigo"]
                            for linha in linhas_selecionadas
                            if linha["codigo"] not in valores_grupo
                        ]
                        restante = max(
                            total_grupo - sum(valores_grupo.values(), Decimal("0")),
                            Decimal("0"),
                        )
                        if sem_valor_manual:
                            valor_rateado = (
                                restante / Decimal(len(sem_valor_manual))
                            ).quantize(QUATRO_CASAS)

                    for linha in secao["linhas"]:
                        codigo = linha["codigo"]
                        if modalidade == MODALIDADE_GRUPO:
                            if (
                                tipo_controle
                                == BudgetConfiguracaoCompra.TipoControle.PRODUTO
                            ):
                                valor = valores_grupo.get(codigo, Decimal("0"))
                            elif codigo not in selecionados_grupo:
                                valor = Decimal("0")
                            else:
                                valor = valores_grupo.get(codigo, valor_rateado)
                        else:
                            valor = _decimal_post(
                                request.POST.get(f"limite_{tipo_controle}_{codigo}")
                            )
                        limite, _ = BudgetLimiteCompra.objects.get_or_create(
                            empresa=empresa,
                            configuracao=configuracao,
                            tipo_controle=tipo_controle,
                            referencia_codigo=codigo,
                            mes=mes_limite,
                            defaults={
                                "referencia_nome": linha["nome"],
                                "estoque_minimo": linha["estoque_minimo"],
                                "limite_compra": valor,
                            },
                        )
                        if (
                            limite.referencia_nome != linha["nome"]
                            or limite.estoque_minimo != linha["estoque_minimo"]
                            or limite.limite_compra != valor
                        ):
                            limite.referencia_nome = linha["nome"]
                            limite.estoque_minimo = linha["estoque_minimo"]
                            limite.limite_compra = valor
                            alteracoes.append(limite)
                if alteracoes:
                    BudgetLimiteCompra.objects.bulk_update(
                        alteracoes,
                        ["referencia_nome", "estoque_minimo", "limite_compra"],
                    )
                configuracao.modalidades_controle = modalidades
                configuracao.totais_grupo = totais_grupo
                configuracao.periodicidades_controle = periodicidades
                configuracao.meses_controle = meses_controle
                configuracao.save(
                    update_fields=[
                        "modalidades_controle",
                        "totais_grupo",
                        "periodicidades_controle",
                        "meses_controle",
                        "atualizado_em",
                    ]
                )
        except ValorBudgetIncompativel:
            messages.error(request, "Valor incompativel com o orçado")
        except ModalidadeBudgetBloqueada:
            messages.error(
                request,
                "Para alterar a modalidade, reverta o budget salvo antes.",
            )
        except ValueError:
            messages.error(
                request,
                "Informe valores validos, meses do budget mensal e itens para ratear no modo Grupo.",
            )
        else:
            messages.success(request, "Limites de budget salvos.")
            return _redirect_budget(empresa, _tipo_ativo_request(request, configuracao))

    return render(
        request,
        "compras/budget.html",
        {
            "empresa": empresa,
            "configuracao": configuracao,
            "tipos_controle": BudgetConfiguracaoCompra.TipoControle.choices,
            "tipos_selecionados": configuracao.tipos_selecionados,
            "rotulos_tipos": configuracao.rotulos_tipos(),
            "secoes": secoes,
            "budget_tipo_ativo": budget_tipo_ativo,
            "total_itens": total_itens,
            "total_limite": total_limite,
        },
    )
