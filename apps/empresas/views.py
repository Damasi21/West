import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    AgendamentoSincronizacaoOmieForm,
    ContaDREForm,
    EmpresaForm,
    EmpresaUsuarioForm,
    IntegracaoOmieForm,
)
from .models import (
    AgendamentoSincronizacaoOmie,
    CadastroOmie,
    CategoriaOmie,
    ContaDRE,
    Empresa,
    IntegracaoOmie,
    MetaVendedorComercial,
    SincronizacaoOmie,
    VendedorOmie,
    EmpresaUsuario,
)
from .omie import iniciar_sincronizacao_omie
from .planilhas import (
    PlanilhaInvalida,
    exportar_categorias,
    exportar_dre,
    importar_categorias,
    importar_dre,
)
from .services import (
    empresas_permitidas,
    obter_empresa_permitida,
    usuario_admin_empresa,
    usuario_gestor_empresa,
    usuario_pode_gerenciar_vinculo,
)


MESES_METAS = [
    (1, "Janeiro"),
    (2, "Fevereiro"),
    (3, "Marco"),
    (4, "Abril"),
    (5, "Maio"),
    (6, "Junho"),
    (7, "Julho"),
    (8, "Agosto"),
    (9, "Setembro"),
    (10, "Outubro"),
    (11, "Novembro"),
    (12, "Dezembro"),
]


SINCRONIZACAO_OMIE_EXPIRA_APOS = timedelta(minutes=30)


@login_required
def lista_empresas(request):
    empresas = empresas_permitidas(request.user)
    return render(
        request,
        "empresas/lista_empresas.html",
        {
            "empresas": empresas,
            "total_empresas": empresas.count(),
        },
    )


def _exigir_administrador(request):
    if not (request.user.is_superuser or request.user.is_staff):
        raise PermissionDenied


def _exigir_administrador_empresa(request, empresa):
    if not usuario_admin_empresa(request.user, empresa):
        raise PermissionDenied


def _exigir_gestor_empresa(request, empresa):
    if not usuario_gestor_empresa(request.user, empresa):
        raise PermissionDenied


def _obter_empresa_administravel(empresa_slug):
    return get_object_or_404(Empresa, slug=empresa_slug, ativa=True)


@login_required
def configuracoes_empresas(request):
    _exigir_administrador(request)
    empresas = Empresa.objects.all()
    return render(
        request,
        "empresas/configuracoes_empresas.html",
        {
            "empresas": empresas,
            "total_empresas": empresas.count(),
            "total_ativas": empresas.filter(ativa=True).count(),
        },
    )


@login_required
def parametros(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_gestor_empresa(request, empresa)
    agendamento = AgendamentoSincronizacaoOmie.objects.filter(empresa=empresa).first()
    formulario_postado = request.POST.get("formulario")
    form_omie = IntegracaoOmieForm(
        request.POST
        if request.method == "POST" and formulario_postado in (None, "omie")
        else None,
        empresa=empresa,
    )
    form_agendamento = AgendamentoSincronizacaoOmieForm(
        request.POST
        if request.method == "POST" and formulario_postado == "sincronizacao"
        else None,
        empresa=empresa,
        usuario=request.user,
        instance=agendamento,
    )
    if request.method == "POST" and formulario_postado == "sincronizacao":
        if form_agendamento.is_valid():
            agendamento = form_agendamento.save()
            messages.success(request, "Agendamento de sincronizacao salvo com sucesso.")
            return redirect(f"{request.path}#sincronizacao-omie")
    elif request.method == "POST" and form_omie.is_valid():
        form_omie.save()
        messages.success(
            request,
            f"Credenciais da OMIE para {empresa.nome_fantasia} salvas com sucesso.",
        )
        return redirect(f"{request.path}#integracao-omie")

    topicos = [
        {
            "titulo": "Períodos de análise",
            "descricao": "Defina mês fiscal, janelas comparativas e filtros padrão dos dashboards.",
            "icone": "bi-calendar3",
            "status": "Planejado",
        },
        {
            "titulo": "Metas e objetivos",
            "descricao": "Cadastre metas comerciais, financeiras e operacionais por empresa ou área.",
            "icone": "bi-bullseye",
            "status": "DisponÃ­vel",
            "url": reverse(
                "dashboards:metas",
                kwargs={"empresa_slug": empresa.slug},
            ),
        },
        {
            "titulo": "Indicadores",
            "descricao": "Organize quais KPIs aparecem em cada dashboard e como devem ser calculados.",
            "icone": "bi-speedometer2",
            "status": "Planejado",
        },
        {
            "titulo": "Classificações",
            "descricao": "Padronize categorias, centros de custo, vendedores, fornecedores e produtos.",
            "icone": "bi-tags",
            "status": "Planejado",
        },
        {
            "titulo": "DRE",
            "descricao": "Monte e organize a estrutura hierárquica do demonstrativo de resultados.",
            "icone": "bi-diagram-3",
            "status": "Disponível",
            "url": reverse(
                "dashboards:dre_categorias",
                kwargs={"empresa_slug": empresa.slug},
            ),
        },
        {
            "titulo": "Categorias",
            "descricao": "Organize as categorias da OMIE e prepare suas regras de associação.",
            "icone": "bi-tags",
            "status": "Disponível",
            "url": reverse(
                "dashboards:categorias",
                kwargs={"empresa_slug": empresa.slug},
            ),
        },
        {
            "titulo": "Budget",
            "descricao": "Defina o controle de compras por produto, familia, projeto ou fornecedor.",
            "icone": "bi-wallet2",
            "status": "Disponivel",
            "url": reverse(
                "dashboards:budget",
                kwargs={"empresa_slug": empresa.slug},
            ),
        },
        {
            "titulo": "Sincronizacao",
            "descricao": "Agende atualizacoes automaticas da OMIE com ate 4 horarios por dia.",
            "icone": "bi-robot",
            "status": "Disponivel",
            "url": reverse(
                "dashboards:sincronizacao_omie",
                kwargs={"empresa_slug": empresa.slug},
            ),
        },
    ]
    return render(
        request,
        "empresas/parametros.html",
        {
            "topicos": topicos,
            "empresa": empresa,
            "pode_administrar_empresa": usuario_admin_empresa(request.user, empresa),
            "form_omie": form_omie,
            "form_agendamento": form_agendamento,
            "agendamento_sincronizacao": agendamento,
            "ultima_sincronizacao": empresa.sincronizacoes_omie.first(),
            "total_cadastros_omie": empresa.cadastros_omie.count(),
            "total_clientes_omie": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.CLIENTE, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "total_fornecedores_omie": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.FORNECEDOR, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "total_projetos_omie": empresa.projetos_omie.count(),
            "total_departamentos_omie": empresa.departamentos_omie.count(),
            "total_vendedores_omie": empresa.vendedores_omie.count(),
            "total_produtos_omie": empresa.produtos_omie.count(),
            "total_servicos_omie": empresa.servicos_omie.count(),
            "total_ordens_servico_omie": empresa.ordens_servico_omie.count(),
            "total_itens_ordem_servico_omie": (
                empresa.itens_ordem_servico_omie.count()
            ),
            "total_contratos_omie": empresa.contratos_omie.count(),
            "total_itens_contrato_omie": empresa.itens_contrato_omie.count(),
            "total_categorias_omie": empresa.categorias_omie.count(),
            "total_tipos_conta_corrente_omie": (
                empresa.tipos_conta_corrente_omie.count()
            ),
            "total_contas_correntes_omie": empresa.contas_correntes_omie.count(),
            "total_contas_pagar_omie": empresa.contas_pagar_omie.count(),
            "total_contas_receber_omie": empresa.contas_receber_omie.count(),
            "total_lancamentos_conta_corrente_omie": (
                empresa.lancamentos_conta_corrente_omie.count()
            ),
            "total_pedidos_omie": empresa.pedidos_omie.count(),
            "total_itens_pedido_omie": empresa.itens_pedido_omie.count(),
            "total_pedidos_compra_omie": empresa.pedidos_compra_omie.count(),
            "total_itens_pedido_compra_omie": (
                empresa.itens_pedido_compra_omie.count()
            ),
        },
    )


@login_required
def sincronizacao_omie(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    agendamento = AgendamentoSincronizacaoOmie.objects.filter(empresa=empresa).first()
    form_agendamento = AgendamentoSincronizacaoOmieForm(
        request.POST or None,
        empresa=empresa,
        usuario=request.user,
        instance=agendamento,
    )
    if request.method == "POST" and form_agendamento.is_valid():
        agendamento = form_agendamento.save()
        messages.success(request, "Agendamento de sincronizacao salvo com sucesso.")
        return redirect(
            reverse(
                "dashboards:sincronizacao_omie",
                kwargs={"empresa_slug": empresa.slug},
            )
        )

    form_omie = IntegracaoOmieForm(None, empresa=empresa)
    ultima_sincronizacao = empresa.sincronizacoes_omie.first()
    return render(
        request,
        "empresas/sincronizacao_omie.html",
        {
            "empresa": empresa,
            "pode_administrar_empresa": usuario_admin_empresa(request.user, empresa),
            "form_omie": form_omie,
            "form_agendamento": form_agendamento,
            "agendamento_sincronizacao": agendamento,
            "ultima_sincronizacao": ultima_sincronizacao,
            "ultima_sincronizacao_info": _info_sincronizacao(ultima_sincronizacao),
            "total_cadastros_omie": empresa.cadastros_omie.count(),
            "total_clientes_omie": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.CLIENTE, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "total_fornecedores_omie": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.FORNECEDOR, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "total_projetos_omie": empresa.projetos_omie.count(),
            "total_departamentos_omie": empresa.departamentos_omie.count(),
            "total_vendedores_omie": empresa.vendedores_omie.count(),
            "total_produtos_omie": empresa.produtos_omie.count(),
            "total_servicos_omie": empresa.servicos_omie.count(),
            "total_ordens_servico_omie": empresa.ordens_servico_omie.count(),
            "total_itens_ordem_servico_omie": (
                empresa.itens_ordem_servico_omie.count()
            ),
            "total_contratos_omie": empresa.contratos_omie.count(),
            "total_itens_contrato_omie": empresa.itens_contrato_omie.count(),
            "total_categorias_omie": empresa.categorias_omie.count(),
            "total_tipos_conta_corrente_omie": (
                empresa.tipos_conta_corrente_omie.count()
            ),
            "total_contas_correntes_omie": empresa.contas_correntes_omie.count(),
            "total_contas_pagar_omie": empresa.contas_pagar_omie.count(),
            "total_contas_receber_omie": empresa.contas_receber_omie.count(),
            "total_lancamentos_conta_corrente_omie": (
                empresa.lancamentos_conta_corrente_omie.count()
            ),
            "total_pedidos_omie": empresa.pedidos_omie.count(),
            "total_itens_pedido_omie": empresa.itens_pedido_omie.count(),
            "total_pedidos_compra_omie": empresa.pedidos_compra_omie.count(),
            "total_itens_pedido_compra_omie": (
                empresa.itens_pedido_compra_omie.count()
            ),
        },
    )


@login_required
def metas(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    hoje = timezone.localdate()
    try:
        ano_selecionado = int(request.POST.get("ano") or request.GET.get("ano") or hoje.year)
    except (TypeError, ValueError):
        ano_selecionado = hoje.year
    try:
        mes_selecionado = int(request.POST.get("mes") or request.GET.get("mes") or hoje.month)
    except (TypeError, ValueError):
        mes_selecionado = hoje.month
    mes_selecionado = min(max(mes_selecionado, 1), 12)
    ano_selecionado = min(max(ano_selecionado, hoje.year - 5), hoje.year + 5)
    vendedores = list(
        VendedorOmie.objects.filter(empresa=empresa, inativo=False).order_by(
            "nome",
            "codigo",
        )
    )
    metas_atuais = {
        meta.vendedor_id: meta
        for meta in MetaVendedorComercial.objects.filter(
            empresa=empresa,
            vendedor__in=vendedores,
            ano=ano_selecionado,
            mes=mes_selecionado,
        )
    }

    if request.method == "POST":
        valores_por_vendedor = {}
        for vendedor in vendedores:
            valor_bruto = request.POST.get(f"meta_{vendedor.pk}", "")
            valor_normalizado = valor_bruto.replace(".", "").replace(",", ".").strip()
            try:
                valor = max(Decimal(valor_normalizado or "0"), Decimal("0"))
            except Exception:
                messages.error(request, "Informe metas com valores numericos validos.")
                return redirect("dashboards:metas", empresa_slug=empresa.slug)
            valores_por_vendedor[vendedor.pk] = valor

        acao = request.POST.get("acao", "salvar")
        meses_destino = (
            range(mes_selecionado, 13)
            if acao == "replicar"
            else (mes_selecionado,)
        )
        with transaction.atomic():
            for mes_destino in meses_destino:
                for vendedor in vendedores:
                    MetaVendedorComercial.objects.update_or_create(
                        empresa=empresa,
                        vendedor=vendedor,
                        ano=ano_selecionado,
                        mes=mes_destino,
                        defaults={"valor_mensal": valores_por_vendedor[vendedor.pk]},
                    )
        if acao == "replicar":
            messages.success(
                request,
                "Metas replicadas do mes selecionado ate dezembro.",
            )
        else:
            messages.success(request, "Metas comerciais salvas.")
        return redirect(
            f"{reverse('dashboards:metas', kwargs={'empresa_slug': empresa.slug})}"
            f"?ano={ano_selecionado}&mes={mes_selecionado}"
        )

    linhas = []
    total_mensal = Decimal("0")
    for vendedor in vendedores:
        meta = metas_atuais.get(vendedor.pk)
        valor = meta.valor_mensal if meta else Decimal("0")
        total_mensal += valor
        linhas.append(
            {
                "vendedor": vendedor,
                "valor": valor,
            }
        )

    return render(
        request,
        "empresas/metas.html",
        {
            "empresa": empresa,
            "linhas": linhas,
            "total_mensal": total_mensal,
            "ano_selecionado": ano_selecionado,
            "mes_selecionado": mes_selecionado,
            "meses": MESES_METAS,
            "anos": range(hoje.year - 1, hoje.year + 3),
        },
    )


@login_required
def usuarios(request, empresa_slug):
    from apps.dashboards.views import AREAS

    empresa = _obter_empresa_administravel(empresa_slug)
    if not usuario_pode_gerenciar_vinculo(request.user, empresa):
        raise PermissionDenied

    vinculos = (
        EmpresaUsuario.objects.filter(empresa=empresa)
        .select_related("usuario")
        .order_by("usuario__first_name", "usuario__username")
    )
    if not (request.user.is_superuser or request.user.is_staff):
        operador = EmpresaUsuario.objects.filter(
            empresa=empresa,
            usuario=request.user,
            ativo=True,
        ).first()
        if operador and operador.papel == EmpresaUsuario.Papel.GESTOR:
            vinculos = vinculos.exclude(papel=EmpresaUsuario.Papel.ADMINISTRADOR)

    vinculo_edicao = None
    editar_id = request.GET.get("editar")
    if editar_id:
        vinculo_edicao = get_object_or_404(
            EmpresaUsuario.objects.select_related("usuario"),
            pk=editar_id,
            empresa=empresa,
        )
        if not usuario_pode_gerenciar_vinculo(request.user, empresa, vinculo_edicao):
            raise PermissionDenied

    form = EmpresaUsuarioForm(
        request.POST or None,
        empresa=empresa,
        operador=request.user,
        areas=AREAS,
        vinculo=vinculo_edicao,
    )
    if request.method == "POST" and form.is_valid():
        vinculo = form.save()
        messages.success(
            request,
            f"Acesso de {vinculo.usuario.get_full_name() or vinculo.usuario.username} salvo com sucesso.",
        )
        return redirect("dashboards:usuarios", empresa_slug=empresa.slug)

    return render(
        request,
        "empresas/usuarios.html",
        {
            "empresa": empresa,
            "form": form,
            "vinculos": vinculos,
            "vinculo_edicao": vinculo_edicao,
            "areas": AREAS,
            "pode_administrar_empresa": usuario_admin_empresa(request.user, empresa),
        },
    )


@login_required
def dre_categorias(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    conta_edicao = None
    if request.GET.get("editar"):
        conta_edicao = get_object_or_404(
            ContaDRE,
            pk=request.GET["editar"],
            empresa=empresa,
        )

    form = ContaDREForm(
        request.POST or None,
        empresa=empresa,
        instance=conta_edicao,
    )
    if request.method == "POST" and form.is_valid():
        conta = form.save()
        acao = "atualizada" if conta_edicao else "criada"
        messages.success(request, f"Conta “{conta.nome}” {acao} com sucesso.")
        return redirect("dashboards:dre_categorias", empresa_slug=empresa.slug)

    contas_pai = (
        ContaDRE.objects.filter(empresa=empresa, conta_pai__isnull=True)
        .prefetch_related("contas_filhas")
        .order_by("ordem", "nome")
    )
    return render(
        request,
        "empresas/dre_categorias.html",
        {
            "empresa": empresa,
            "form": form,
            "conta_edicao": conta_edicao,
            "contas_pai": contas_pai,
            "total_contas": empresa.contas_dre.count(),
        },
    )


@login_required
def categorias(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    categorias_ativas = list(
        CategoriaOmie.objects.filter(
            empresa=empresa,
            conta_inativa=False,
        )
        .select_related("conta_dre")
        .order_by("codigo")
    )
    contas_pai = list(
        ContaDRE.objects.filter(empresa=empresa, conta_pai__isnull=True)
        .exclude(sinal=ContaDRE.Sinal.RESULTADO)
        .prefetch_related("contas_filhas")
        .order_by("ordem", "nome")
    )

    if request.method == "POST":
        contas_validas = {
            str(conta.pk): conta
            for conta in ContaDRE.objects.filter(empresa=empresa).exclude(
                sinal=ContaDRE.Sinal.RESULTADO,
            )
        }
        ids_solicitados = {
            valor
            for categoria in categorias_ativas
            if categoria.permite_vinculo_dre
            for valor in [request.POST.get(f"conta_dre_{categoria.pk}", "")]
            if valor
        }
        if not ids_solicitados.issubset(contas_validas):
            messages.error(request, "Uma das contas DRE selecionadas é inválida.")
        else:
            alteradas = []
            for categoria in categorias_ativas:
                if not categoria.permite_vinculo_dre:
                    continue
                valor = request.POST.get(f"conta_dre_{categoria.pk}", "")
                novo_id = int(valor) if valor else None
                if categoria.conta_dre_id != novo_id:
                    categoria.conta_dre_id = novo_id
                    alteradas.append(categoria)
            if alteradas:
                with transaction.atomic():
                    CategoriaOmie.objects.bulk_update(alteradas, ["conta_dre"])
            messages.success(
                request,
                f"Vínculos de categorias da {empresa.nome_fantasia} salvos.",
            )
            return redirect("dashboards:categorias", empresa_slug=empresa.slug)

    return render(
        request,
        "empresas/categorias.html",
        {
            "empresa": empresa,
            "categorias": categorias_ativas,
            "contas_pai": contas_pai,
            "total_categorias": len(categorias_ativas),
            "total_vinculaveis": sum(
                categoria.permite_vinculo_dre for categoria in categorias_ativas
            ),
        },
    )


def _resposta_planilha(conteudo, nome):
    response = HttpResponse(
        conteudo,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{nome}.xlsx"'
    return response


def _obter_planilha_enviada(request):
    arquivo = request.FILES.get("planilha")
    if not arquivo:
        raise PlanilhaInvalida("Selecione uma planilha XLSX para importar.")
    if not arquivo.name.lower().endswith(".xlsx"):
        raise PlanilhaInvalida("O arquivo precisa estar no formato XLSX.")
    if arquivo.size > 5 * 1024 * 1024:
        raise PlanilhaInvalida("A planilha deve ter no máximo 5 MB.")
    return arquivo


@login_required
@require_GET
def exportar_planilha_dre(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    return _resposta_planilha(
        exportar_dre(empresa),
        f"dre-{slugify(empresa.nome_fantasia)}",
    )


@login_required
@require_POST
def importar_planilha_dre(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    destino = "dashboards:dre_categorias"
    try:
        arquivo = _obter_planilha_enviada(request)
        contas = importar_dre(arquivo)
        if empresa.contas_dre.exists() and request.POST.get("sobrepor") != "sim":
            messages.error(
                request,
                "A estrutura atual não foi alterada. Confirme a sobreposição para importar.",
            )
            return redirect(destino, empresa_slug=empresa.slug)

        with transaction.atomic():
            empresa.contas_dre.filter(conta_pai__isnull=False).delete()
            empresa.contas_dre.filter(conta_pai__isnull=True).delete()
            contas_criadas = {}
            for indice, dados in enumerate(contas):
                conta_pai = (
                    contas_criadas[dados["indice_pai"]]
                    if dados["tipo"] == "filho"
                    else None
                )
                conta = ContaDRE.objects.create(
                    empresa=empresa,
                    nome=dados["nome"],
                    conta_pai=conta_pai,
                    sinal=dados["sinal"],
                    ordem=dados["ordem"],
                )
                contas_criadas[indice] = conta
        messages.success(
            request,
            f"Estrutura DRE importada com {len(contas)} contas.",
        )
    except PlanilhaInvalida as exc:
        messages.error(request, str(exc))
    return redirect(destino, empresa_slug=empresa.slug)


@login_required
@require_GET
def exportar_planilha_categorias(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    return _resposta_planilha(
        exportar_categorias(empresa),
        f"categorias-{slugify(empresa.nome_fantasia)}",
    )


@login_required
@require_POST
def importar_planilha_categorias(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    destino = "dashboards:categorias"
    try:
        arquivo = _obter_planilha_enviada(request)
        alteracoes = importar_categorias(arquivo, empresa)
        categorias = {
            categoria.pk: categoria
            for categoria in CategoriaOmie.objects.filter(
                empresa=empresa,
                pk__in=alteracoes,
            )
        }
        atualizadas = []
        for categoria_id, conta_dre_id in alteracoes.items():
            categoria = categorias[categoria_id]
            if categoria.conta_dre_id != conta_dre_id:
                categoria.conta_dre_id = conta_dre_id
                atualizadas.append(categoria)
        if atualizadas:
            with transaction.atomic():
                CategoriaOmie.objects.bulk_update(atualizadas, ["conta_dre"])
        messages.success(
            request,
            f"Planilha importada. {len(atualizadas)} associações atualizadas.",
        )
    except PlanilhaInvalida as exc:
        messages.error(request, str(exc))
    return redirect(destino, empresa_slug=empresa.slug)


@login_required
@require_POST
def excluir_conta_dre(request, empresa_slug, conta_id):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    conta = get_object_or_404(ContaDRE, pk=conta_id, empresa=empresa)
    if conta.contas_filhas.exists():
        messages.error(
            request,
            "Remova ou mova as contas filhas antes de excluir este grupo.",
        )
    else:
        nome = conta.nome
        conta.delete()
        messages.success(request, f"Conta “{nome}” excluída.")
    return redirect("dashboards:dre_categorias", empresa_slug=empresa.slug)


@login_required
@require_POST
def reordenar_contas_dre(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    try:
        dados = json.loads(request.body)
        ids = [int(item) for item in dados.get("ids", [])]
        parent_id = dados.get("parent_id")
        parent_id = int(parent_id) if parent_id not in (None, "") else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"erro": "Ordem inválida."}, status=400)

    if len(ids) != len(set(ids)):
        return JsonResponse({"erro": "Existem contas repetidas na ordem."}, status=400)
    if parent_id is not None and not ContaDRE.objects.filter(
        pk=parent_id,
        empresa=empresa,
        conta_pai__isnull=True,
    ).exclude(sinal=ContaDRE.Sinal.RESULTADO).exists():
        return JsonResponse({"erro": "Grupo pai inválido."}, status=400)

    contas = list(
        ContaDRE.objects.filter(
            empresa=empresa,
            conta_pai_id=parent_id,
        ).order_by("ordem", "nome")
    )
    if set(ids) != {conta.pk for conta in contas}:
        return JsonResponse({"erro": "A lista de contas está incompleta."}, status=400)

    posicoes = {conta_id: ordem for ordem, conta_id in enumerate(ids, start=1)}
    for conta in contas:
        conta.ordem = posicoes[conta.pk]
    with transaction.atomic():
        ContaDRE.objects.bulk_update(contas, ["ordem"])
    return JsonResponse({"ok": True})


def _formatar_data_hora_sincronizacao(valor):
    if not valor:
        return ""
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")


def _formatar_duracao_sincronizacao(inicio, fim):
    if not inicio:
        return ""
    fim = fim or timezone.now()
    total_segundos = max(0, int((fim - inicio).total_seconds()))
    horas, resto = divmod(total_segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos:02d} min"
    if minutos:
        return f"{minutos} min {segundos:02d} s"
    return f"{segundos} s"


def _info_sincronizacao(sincronizacao):
    if not sincronizacao:
        return {
            "iniciada_em": "",
            "finalizada_em": "",
            "duracao": "",
        }
    return {
        "iniciada_em": _formatar_data_hora_sincronizacao(
            sincronizacao.iniciada_em
        ),
        "finalizada_em": _formatar_data_hora_sincronizacao(
            sincronizacao.finalizada_em
        ),
        "duracao": _formatar_duracao_sincronizacao(
            sincronizacao.iniciada_em,
            sincronizacao.finalizada_em,
        ),
    }


def _dados_sincronizacao(sincronizacao):
    return {
        "id": sincronizacao.pk,
        "status": sincronizacao.status,
        "status_label": sincronizacao.get_status_display(),
        "percentual": sincronizacao.percentual,
        "pagina_atual": sincronizacao.pagina_atual,
        "total_paginas": sincronizacao.total_paginas,
        "registros_processados": sincronizacao.registros_processados,
        "total_registros": sincronizacao.total_registros,
        "mensagem": sincronizacao.mensagem,
        "erro": sincronizacao.erro,
        **_info_sincronizacao(sincronizacao),
        "origem": sincronizacao.origem,
        "origem_label": sincronizacao.get_origem_display(),
        "disparada_por": (
            sincronizacao.disparada_por.get_full_name()
            or sincronizacao.disparada_por.username
            if sincronizacao.disparada_por_id
            else ""
        ),
    }


def _encerrar_sincronizacoes_omie_obsoletas(empresa):
    agora = timezone.now()
    return empresa.sincronizacoes_omie.filter(
        status__in=[
            SincronizacaoOmie.Status.PENDENTE,
            SincronizacaoOmie.Status.EM_ANDAMENTO,
        ],
        atualizada_em__lt=agora - SINCRONIZACAO_OMIE_EXPIRA_APOS,
    ).update(
        status=SincronizacaoOmie.Status.ERRO,
        finalizada_em=agora,
        mensagem="Sincronização interrompida. Inicie uma nova atualização.",
        erro="A sincronização ficou sem atividade por mais de 30 minutos.",
    )


@login_required
@require_POST
def sincronizar_clientes_omie(request, empresa_slug):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    integracao = IntegracaoOmie.objects.filter(empresa=empresa, ativa=True).first()
    if not integracao:
        return JsonResponse(
            {"erro": "Salve e ative as credenciais da OMIE antes de sincronizar."},
            status=400,
        )

    _encerrar_sincronizacoes_omie_obsoletas(empresa)
    em_execucao = empresa.sincronizacoes_omie.filter(
        status__in=[
            SincronizacaoOmie.Status.PENDENTE,
            SincronizacaoOmie.Status.EM_ANDAMENTO,
        ]
    ).first()
    if em_execucao:
        return JsonResponse(_dados_sincronizacao(em_execucao), status=202)

    sincronizacao = SincronizacaoOmie.objects.create(
        empresa=empresa,
        recurso="completa",
        origem=SincronizacaoOmie.Origem.MANUAL,
        disparada_por=request.user,
        mensagem="Sincronização adicionada à fila.",
    )
    iniciar_sincronizacao_omie(sincronizacao.pk)
    return JsonResponse(_dados_sincronizacao(sincronizacao), status=202)


@login_required
@require_GET
def status_sincronizacao_omie(request, empresa_slug, sincronizacao_id):
    empresa = _obter_empresa_administravel(empresa_slug)
    _exigir_administrador_empresa(request, empresa)
    sincronizacao = get_object_or_404(
        SincronizacaoOmie,
        pk=sincronizacao_id,
        empresa=empresa,
    )
    if sincronizacao.status in [
        SincronizacaoOmie.Status.PENDENTE,
        SincronizacaoOmie.Status.EM_ANDAMENTO,
    ] and (
        sincronizacao.atualizada_em
        < timezone.now() - SINCRONIZACAO_OMIE_EXPIRA_APOS
    ):
        _encerrar_sincronizacoes_omie_obsoletas(empresa)
        sincronizacao.refresh_from_db()
    dados = _dados_sincronizacao(sincronizacao)
    if sincronizacao.status == SincronizacaoOmie.Status.CONCLUIDA:
        dados["totais"] = {
            "cadastros": empresa.cadastros_omie.count(),
            "clientes": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.CLIENTE, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "fornecedores": empresa.cadastros_omie.filter(
                tipo__in=[CadastroOmie.Tipo.FORNECEDOR, CadastroOmie.Tipo.AMBOS]
            ).count(),
            "projetos": empresa.projetos_omie.count(),
            "departamentos": empresa.departamentos_omie.count(),
            "vendedores": empresa.vendedores_omie.count(),
            "produtos": empresa.produtos_omie.count(),
            "servicos": empresa.servicos_omie.count(),
            "ordens_servico": empresa.ordens_servico_omie.count(),
            "itens_ordem_servico": empresa.itens_ordem_servico_omie.count(),
            "contratos": empresa.contratos_omie.count(),
            "itens_contrato": empresa.itens_contrato_omie.count(),
            "categorias": empresa.categorias_omie.count(),
            "tipos_conta_corrente": empresa.tipos_conta_corrente_omie.count(),
            "contas_correntes": empresa.contas_correntes_omie.count(),
            "contas_pagar": empresa.contas_pagar_omie.count(),
            "contas_receber": empresa.contas_receber_omie.count(),
            "lancamentos_conta_corrente": (
                empresa.lancamentos_conta_corrente_omie.count()
            ),
            "pedidos": empresa.pedidos_omie.count(),
            "itens_pedido": empresa.itens_pedido_omie.count(),
            "pedidos_compra": empresa.pedidos_compra_omie.count(),
            "itens_pedido_compra": empresa.itens_pedido_compra_omie.count(),
        }
    return JsonResponse(dados)


@login_required
def cadastrar_empresa(request):
    _exigir_administrador(request)
    form = EmpresaForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        empresa = form.save()
        messages.success(request, f"{empresa.nome_fantasia} cadastrada com sucesso.")
        return redirect("empresas:configuracoes")

    return render(
        request,
        "empresas/form_empresa.html",
        {"form": form, "titulo": "Cadastrar empresa"},
    )


@login_required
def editar_empresa(request, empresa_id):
    _exigir_administrador(request)
    empresa = get_object_or_404(Empresa, pk=empresa_id)
    form = EmpresaForm(request.POST or None, request.FILES or None, instance=empresa)
    if request.method == "POST" and form.is_valid():
        empresa = form.save()
        messages.success(request, f"{empresa.nome_fantasia} atualizada com sucesso.")
        return redirect("empresas:configuracoes")

    return render(
        request,
        "empresas/form_empresa.html",
        {"form": form, "titulo": "Editar empresa", "empresa_edicao": empresa},
    )
