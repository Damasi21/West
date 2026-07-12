import json
from datetime import timedelta

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

from .forms import ContaDREForm, EmpresaForm, IntegracaoOmieForm
from .models import (
    CadastroOmie,
    CategoriaOmie,
    ContaDRE,
    Empresa,
    IntegracaoOmie,
    SincronizacaoOmie,
)
from .omie import iniciar_sincronizacao_omie
from .planilhas import (
    PlanilhaInvalida,
    exportar_categorias,
    exportar_dre,
    importar_categorias,
    importar_dre,
)
from .services import empresas_permitidas, obter_empresa_permitida


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
    if not request.user.is_staff:
        raise PermissionDenied


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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
    form_omie = IntegracaoOmieForm(
        request.POST or None,
        empresa=empresa,
    )
    if request.method == "POST" and form_omie.is_valid():
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
            "status": "Planejado",
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
    ]
    return render(
        request,
        "empresas/parametros.html",
        {
            "topicos": topicos,
            "empresa": empresa,
            "form_omie": form_omie,
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
        },
    )


@login_required
def dre_categorias(request, empresa_slug):
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
    return _resposta_planilha(
        exportar_dre(empresa),
        f"dre-{slugify(empresa.nome_fantasia)}",
    )


@login_required
@require_POST
def importar_planilha_dre(request, empresa_slug):
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
    return _resposta_planilha(
        exportar_categorias(empresa),
        f"categorias-{slugify(empresa.nome_fantasia)}",
    )


@login_required
@require_POST
def importar_planilha_categorias(request, empresa_slug):
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
        recurso="cadastros",
        mensagem="Sincronização adicionada à fila.",
    )
    iniciar_sincronizacao_omie(sincronizacao.pk)
    return JsonResponse(_dados_sincronizacao(sincronizacao), status=202)


@login_required
@require_GET
def status_sincronizacao_omie(request, empresa_slug, sincronizacao_id):
    _exigir_administrador(request)
    empresa = obter_empresa_permitida(request.user, empresa_slug)
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
