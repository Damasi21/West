from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.empresas.models import AmbienteWhiteLabel, Empresa, CategoriaOmie
from apps.empresas.white_label_branding import SESSION_MARCA
from apps.empresas.white_label_domains import _marca_host, marca_host_atual
from .forms import PlanoForm, NovaCategoriaForm, PadronizacaoForm
from .models import CadastroCategoria, CadastroCategoriaEmpresa
from . import central
from .models import PlanoReplicacao, ComparacaoReplicacao, ItemReplicacao, DestinoReplicacao, VinculoCategoria
from .permissions import empresas_gerenciaveis, planos_permitidos, conferir_acesso
from .services import solicitar_comparacao, publicar, aprovar, resolver_item, candidatos_item, auditar, disponibilidade_exclusao, excluir_configuracao
from .comparacao import sugestoes_nome, compativel, dados


def ambiente_view(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        marca = marca_host_atual()
        if marca is None:
            marca_id = request.session.get(SESSION_MARCA)
            if isinstance(marca_id, int):
                marca = AmbienteWhiteLabel.objects.filter(pk=marca_id, ativa=True).first()
        token = _marca_host.set(marca)
        try:
            if empresas_gerenciaveis(request.user).count() < 2:
                raise PermissionDenied("É necessário administrar a matriz e ao menos uma empresa destino.")
            response = view(request, *args, **kwargs)
            response["Cache-Control"] = "private, no-store"
            return response
        finally:
            _marca_host.reset(token)
    return login_required(wrapped)


def plano_request(request, plano_id):
    return get_object_or_404(planos_permitidos(request.user).select_related("matriz", "marca"), pk=plano_id)


def informar_erro(request, erro):
    messages.error(request, " ".join(erro.messages) if hasattr(erro, "messages") else "Operação não autorizada.")


def voltar_comparacao(plano, comparacao_id):
    return redirect(reverse("replicacao:detalhe", args=[plano.pk])+f"?comparacao={comparacao_id}")


@ambiente_view
@require_GET
def lista(request):
    planos = disponibilidade_exclusao(planos_permitidos(request.user)).select_related("matriz").prefetch_related("destinos__empresa")
    return render(request, "replicacao/lista.html", {"planos": planos})


@ambiente_view
@require_http_methods(["GET", "POST"])
def excluir(request, plano_id):
    plano = get_object_or_404(disponibilidade_exclusao(planos_permitidos(request.user)).select_related("matriz"), pk=plano_id)
    if request.method == "POST":
        try:
            if request.POST.get("confirmar") != "sim":
                raise ValidationError("Confirme a exclusão da configuração.")
            excluir_configuracao(plano, request.user)
            messages.success(request, "Configuração excluída.")
            return redirect("replicacao:lista")
        except (ValidationError, PermissionDenied) as erro:
            informar_erro(request, erro)
    if not plano.pode_excluir:
        messages.error(request, "Esta configuração já possui solicitações ou vínculos e não pode ser excluída. Você pode pausá-la.")
        return redirect("replicacao:lista")
    return render(request, "replicacao/excluir.html", {"plano": plano})


@ambiente_view
@require_http_methods(["GET", "POST"])
def novo(request):
    form = PlanoForm(request.POST or None, usuario=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            plano = form.salvar()
            auditar(plano, request.user, "Criou plano de replicação", destinos=list(plano.destinos.values_list("empresa_id", flat=True)))
            messages.success(request, "Configuração salva. Atualize a árvore de categorias da base PAI para começar.")
            return redirect("replicacao:detalhe", plano_id=plano.pk)
        except (ValidationError, PermissionDenied) as erro:
            form.add_error(None, erro)
    return render(request, "replicacao/novo.html", {"form": form})


@ambiente_view
@require_GET
def detalhe(request, plano_id):
    plano = plano_request(request, plano_id)
    if plano.grupo and not request.GET.get("historico"):
        return painel_central(request, plano)
    comparacoes = plano.comparacoes.select_related("solicitado_por")
    comparacao_id = request.GET.get("comparacao")
    comparacao = get_object_or_404(comparacoes, pk=comparacao_id) if comparacao_id and comparacao_id.isascii() and comparacao_id.isdigit() else comparacoes.first()
    itens = comparacao.itens.select_related("origem", "categoria", "destino__empresa") if comparacao else ItemReplicacao.objects.none()
    resumo = {"criar": 0, "alterar": 0, "igual": 0, "ambiguo": 0, "bloqueado": 0}
    if comparacao:
        from django.db.models import Count
        resumo.update({linha["situacao"]: linha["total"] for linha in itens.values("situacao").annotate(total=Count("pk"))})
    situacao = request.GET.get("situacao", "")
    if situacao in resumo:
        itens = itens.filter(situacao=situacao)
    busca = request.GET.get("q", "").strip()[:120]
    if busca:
        itens = itens.filter(caminho__icontains=busca)
    pagina = Paginator(itens, 100).get_page(request.GET.get("page"))
    ids_candidatos = {pk for item in pagina if item.categoria_id is None for pk in item.candidatos}
    catalogo_sugeridos = {c.pk: c for c in CategoriaOmie.objects.filter(pk__in=ids_candidatos, ativo_omie=True, conta_inativa=False, transferencia=False)}
    filhos_sugeridos = [item for item in pagina if item.candidatos and item.categoria_id is None and not item.matriz_dados["totalizadora"]]
    destinos_ids = {item.destino_id for item in filhos_sugeridos}
    codigos_pais = {item.matriz_dados["categoria_superior"] for item in filhos_sugeridos}
    pais = {}
    if filhos_sugeridos:
        pais.update({(destino_id, origem_codigo): codigo for destino_id, origem_codigo, codigo in comparacao.itens.filter(
            destino_id__in=destinos_ids, origem__codigo__in=codigos_pais, categoria__isnull=False
        ).values_list("destino_id", "origem__codigo", "categoria__codigo")})
        pais.update({(destino_id, origem_codigo): codigo for destino_id, origem_codigo, codigo in VinculoCategoria.objects.filter(
            destino_id__in=destinos_ids, origem__codigo__in=codigos_pais
        ).values_list("destino_id", "origem__codigo", "categoria__codigo")})
    for item in pagina:
        item.sugestoes = sugestoes_nome(item.matriz_dados["descricao"], [catalogo_sugeridos[pk] for pk in item.candidatos
            if pk in catalogo_sugeridos and catalogo_sugeridos[pk].empresa_id == item.destino.empresa_id
            and compativel(item.matriz_dados, dados(catalogo_sugeridos[pk]), pais.get((item.destino_id, item.matriz_dados["categoria_superior"])))]) if item.categoria_id is None else []
        item.pode_selecionar = item.status == "pendente" and item.situacao not in {"ambiguo", "bloqueado"} and comparacao.status in {"pronta", "concluida"} and plano.ativo
        item.pode_resolver = item.status == "pendente" and item.situacao != "bloqueado" and comparacao.status in {"pronta", "concluida"} and plano.ativo
        item.pode_verificar = plano.ativo and (item.status == "incerto" or (item.status == "executando" and item.atualizado_em < timezone.now()-timedelta(minutes=30)))
    return render(request, "replicacao/detalhe.html", {
        "plano": plano, "comparacao": comparacao, "comparacoes": comparacoes[:20], "pagina": pagina,
        "resumo": resumo, "situacao": situacao, "busca": busca,
        "situacoes": ItemReplicacao.Situacao.choices,
        "em_processamento": comparacao and comparacao.status in {"fila", "comparando", "enviando"},
        "pode_enviar": comparacao and comparacao.status in {"pronta", "concluida"} and plano.ativo,
    })


@ambiente_view
@require_POST
def comparar(request, plano_id):
    plano = plano_request(request, plano_id)
    try:
        comparacao = solicitar_comparacao(plano, request.user)
        transaction.on_commit(lambda: publicar(comparacao))
    except (ValidationError, PermissionDenied) as erro:
        informar_erro(request, erro)
    return redirect("replicacao:detalhe", plano_id=plano.pk)


@ambiente_view
@require_POST
def enviar(request, plano_id, comparacao_id):
    plano = plano_request(request, plano_id)
    comparacao = get_object_or_404(plano.comparacoes, pk=comparacao_id)
    if request.POST.get("confirmar") != "sim":
        messages.error(request, "Confirme que os itens selecionados serão aplicados na OMIE das empresas destino.")
    else:
        try:
            valores = request.POST.getlist("itens")
            if any(not i.isascii() or not i.isdigit() for i in valores):
                raise ValidationError("Seleção inválida.")
            comparacao = aprovar(comparacao, request.user, [int(i) for i in valores])
            transaction.on_commit(lambda: publicar(comparacao, envio=True))
            messages.success(request, "Itens selecionados enviados para a fila de replicação.")
        except (ValidationError, PermissionDenied) as erro:
            informar_erro(request, erro)
    return voltar_comparacao(plano, comparacao.pk)


@ambiente_view
@require_http_methods(["GET", "POST"])
def resolver(request, plano_id, item_id):
    plano = plano_request(request, plano_id)
    item = get_object_or_404(ItemReplicacao, pk=item_id, comparacao__plano=plano)
    if not plano.ativo or item.status != "pendente" or item.situacao == "bloqueado" or item.comparacao.status not in {"pronta", "concluida"}:
        raise PermissionDenied
    if request.method == "GET":
        candidatos = candidatos_item(item)
        sugestoes = sugestoes_nome(item.matriz_dados["descricao"], candidatos) if item.categoria_id is None else []
        ids_sugeridos = {c.pk for c in sugestoes}
        return render(request, "replicacao/resolver.html", {"plano": plano, "item": item,
            "candidatos": [c for c in candidatos if c.pk not in ids_sugeridos], "sugestoes": sugestoes})
    valor = request.POST.get("categoria", "")
    try:
        if valor != "nova" and (not valor.isascii() or not valor.isdigit()):
            raise ValidationError("Selecione o cadastro correspondente ou escolha criar um novo.")
        resolver_item(item, request.user, categoria_id=int(valor) if valor != "nova" else None, criar=valor == "nova")
        messages.success(request, "Correspondência definida. Revise e selecione o item para replicar.")
    except (ValidationError, PermissionDenied) as erro:
        informar_erro(request, erro)
    return voltar_comparacao(plano, item.comparacao_id)


@ambiente_view
@require_POST
def verificar(request, plano_id, item_id):
    from .tasks import verificar_categoria
    plano = plano_request(request, plano_id)
    item = get_object_or_404(ItemReplicacao, pk=item_id, comparacao__plano=plano)
    try:
        conferir_acesso(plano, request.user)
        if item.status != "incerto" and not (item.status == "executando" and item.atualizado_em < timezone.now()-timedelta(minutes=30)):
            raise ValidationError("O envio ainda não está disponível para verificação.")
        codigo = request.POST.get("codigo", "").strip()
        if len(codigo) > 20 or (codigo and any(c not in "0123456789." for c in codigo)):
            raise ValidationError("Informe somente o código da categoria na OMIE destino.")
        conhecido = item.codigo_confirmado or (item.categoria.codigo if item.categoria_id else "")
        if conhecido and codigo and conhecido != codigo:
            raise ValidationError("O código informado difere do código original deste envio.")
        if not conhecido and not codigo:
            raise ValidationError("Consulte o cadastro na OMIE e informe seu código para verificar a inclusão.")
        verificar_categoria.apply_async(args=[item.pk, request.user.pk, codigo], queue="omie_replicacao", retry=False)
        messages.success(request, "Verificação solicitada. Esta ação consulta a OMIE e não repete inclusões ou alterações.")
    except (ValidationError, PermissionDenied) as erro:
        informar_erro(request, erro)
    except Exception:
        messages.error(request, "Não foi possível conectar ao worker. Tente verificar novamente.")
    return voltar_comparacao(plano, item.comparacao_id)


@ambiente_view
@require_POST
def atualizar_situacao(request, plano_id, comparacao_id):
    plano = plano_request(request, plano_id)
    with transaction.atomic():
        comparacao = get_object_or_404(plano.comparacoes.select_for_update(), pk=comparacao_id)
        if comparacao.status == "fila" or (comparacao.status == "enviando" and comparacao.iniciada_em is None):
            transaction.on_commit(lambda: publicar(comparacao, envio=comparacao.status == "enviando"))
            messages.success(request, "Solicitação reenfileirada. O controle de processamento impede envios duplicados.")
        elif comparacao.status in {"comparando", "enviando"} and comparacao.atualizada_em < timezone.now()-timedelta(minutes=30):
            comparacao.itens.filter(status="executando").update(status="incerto", mensagem="Processamento sem conclusão. Verifique o resultado na OMIE; não será reenviado.")
            comparacao.itens.filter(status="fila").update(status="erro", mensagem="Não processado. Gere uma nova comparação.")
            comparacao.status = "erro" if comparacao.status == "comparando" else "concluida"
            comparacao.mensagem = "Espera encerrada. Revise os resultados sem confirmação antes de uma nova comparação."
            comparacao.save()
        else:
            messages.info(request, "O processamento ainda está no prazo de execução. Atualize a página para acompanhar.")
    return redirect("replicacao:detalhe", plano_id=plano.pk)


@ambiente_view
@require_POST
def alternar(request, plano_id):
    plano = plano_request(request, plano_id)
    try:
        with transaction.atomic():
            list(Empresa.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
            plano = PlanoReplicacao.objects.select_for_update().get(pk=plano.pk)
            if plano.cadastros.filter(status__in=["fila", "consultando", "enviando", "revisao"]).exists() or plano.cadastros.filter(empresas__status__in=["executando", "incerto"]).exists():
                raise ValidationError("Conclua ou verifique os cadastros centrais antes de pausar a configuração.")
            if plano.comparacoes.filter(status__in=["comparando", "enviando"]).exists():
                raise ValidationError("Aguarde a conclusão do processamento antes de pausar este plano.")
            if plano.ativo and ItemReplicacao.objects.filter(comparacao__plano=plano, status__in=["incerto", "executando"]).exists():
                raise ValidationError("Verifique os envios sem confirmação antes de pausar ou substituir este fluxo.")
            plano.ativo = not plano.ativo
            plano.save()
            if plano.ativo:
                conferir_acesso(plano, request.user)
                ids = list(plano.destinos.values_list("empresa_id", flat=True))
                if DestinoReplicacao.objects.filter(plano__ativo=True, empresa_id__in=[plano.matriz_id, *ids]).exclude(plano=plano).exists() or PlanoReplicacao.objects.filter(ativo=True, matriz_id__in=ids).exclude(pk=plano.pk).exists():
                    raise ValidationError("Há outro fluxo ativo usando estas empresas. Não é possível reativar este plano.")
            auditar(plano, request.user, "Alterou situação do plano de replicação", ativo=plano.ativo)
    except (ValidationError, PermissionDenied) as erro:
        informar_erro(request, erro)
    return redirect("replicacao:detalhe", plano_id=plano.pk)


def painel_central(request, plano):
    erro_grupo = ""
    try:
        central.conferir_grupo(plano, request.user)
    except (ValidationError, PermissionDenied) as exc:
        erro_grupo = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
    operacao = plano.cadastros.first()
    if request.GET.get("cadastro", "").isdigit():
        operacao = get_object_or_404(plano.cadastros, pk=request.GET["cadastro"])
    categorias = list(CategoriaOmie.objects.filter(empresa=plano.matriz, ativo_omie=True).order_by("codigo"))
    # The OMIE hierarchy is shallow, but keep the display independent of code
    # numbering and show orphans instead of silently dropping a category.
    por_pai = {}
    codigos = {c.codigo for c in categorias}
    for c in categorias:
        por_pai.setdefault(c.categoria_superior if c.categoria_superior in codigos else "", []).append(c)
    arvore, visitados = [], set()
    def incluir(c, nivel):
        if c.pk in visitados:
            return
        visitados.add(c.pk)
        c.nivel_visual = min(nivel, 4)
        arvore.append(c)
        for filho in por_pai.get(c.codigo, []):
            incluir(filho, nivel + 1)
    for c in por_pai.get("", []):
        incluir(c, 0)
    for c in categorias:
        incluir(c, 0)
    for categoria in arvore:
        categoria.pode_alterar_situacao = not categoria.totalizadora and not categoria.transferencia and categoria.ativo_omie
    linhas = list(operacao.empresas.select_related("empresa")) if operacao else []
    for linha in linhas:
        linha.precisa_codigo = any(p.get("status") in {"executando", "incerto"} and not p.get("codigo") and not p.get("alvo") for p in linha.passos)
        if operacao.modo in {"inativar", "reativar", "espelho"} and linha.status == "revisao":
            linha.rotulo_situacao = "Aguardando confirmação"
    ocupado = plano.cadastros.filter(status__in=central.OCUPADOS | {"revisao"}).exists()
    return render(request, "replicacao/central.html", {"plano": plano, "arvore": arvore,
        "erro_grupo": erro_grupo, "form": NovaCategoriaForm(plano=plano), "form_padronizacao": PadronizacaoForm(plano=plano), "operacao": operacao,
        "progresso": central.situacao(operacao) if operacao else None, "linhas": linhas,
        "ocupado": ocupado, "historico": plano.cadastros.all()[:20],
        "pode_cancelar": operacao and (operacao.status in {"erro", "fila", "revisao"} or (operacao.status == "concluido" and operacao.empresas.exclude(status__in=["sucesso", "ignorada"]).exists())),
        "alteracao_situacao": operacao and operacao.modo in {"inativar", "reativar"}})


@ambiente_view
@require_http_methods(["GET", "POST"])
def situacao_categoria(request, plano_id, categoria_id):
    from . import estado
    plano = plano_request(request, plano_id)
    categoria = get_object_or_404(CategoriaOmie, pk=categoria_id, empresa=plano.matriz)
    try:
        empresas = central.conferir_grupo(plano, request.user)
        estado.validar_categoria(categoria)
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
        return redirect("replicacao:detalhe", plano_id=plano.pk)
    modo = request.POST.get("modo", "reativar" if categoria.conta_inativa else "inativar")
    if request.method == "POST":
        try:
            valores = request.POST.getlist("empresas")
            if any(not v.isascii() or not v.isdigit() for v in valores):
                raise ValidationError("Seleção de empresas inválida.")
            op = estado.solicitar(plano, request.user, categoria, modo, [int(v) for v in valores])
            transaction.on_commit(lambda: central.publicar_cadastro(op))
            return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")
        except (ValidationError, PermissionDenied) as exc:
            informar_erro(request, exc)
    return render(request, "replicacao/situacao_categoria.html", {"plano": plano, "categoria": categoria,
        "empresas": empresas, "modo": modo, "selecionadas": request.POST.getlist("empresas") if request.method == "POST" else [str(e.pk) for e in empresas]})


@ambiente_view
@require_POST
def confirmar_situacao(request, plano_id, cadastro_id):
    from . import estado
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        op = estado.confirmar(op, request.user, request.POST)
        if op.status == "fila":
            transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")


@ambiente_view
@require_POST
def cadastrar(request, plano_id):
    plano = plano_request(request, plano_id)
    form = NovaCategoriaForm(request.POST, plano=plano)
    try:
        if request.POST.get("confirmar") != "sim":
            raise ValidationError("Confirme o cadastro nos OMIEs do grupo.")
        if not form.is_valid():
            raise ValidationError([f"{form.fields[n].label}: {e}" for n, erros in form.errors.items() for e in erros])
        op = central.solicitar(plano, request.user, form.cleaned_data["descricao"], form.cleaned_data["pai"],
            destinos_ids=list(form.cleaned_data["destinos"].values_list("pk", flat=True)), estrito=True)
        transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect("replicacao:detalhe", plano_id=plano.pk)


@ambiente_view
@require_POST
def atualizar_arvore(request, plano_id):
    plano = plano_request(request, plano_id)
    try:
        op = central.solicitar(plano, request.user, catalogo=True)
        transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect("replicacao:detalhe", plano_id=plano.pk)


@ambiente_view
@require_POST
def padronizar(request, plano_id):
    from . import padronizacao
    plano = plano_request(request, plano_id)
    form = PadronizacaoForm(request.POST, plano=plano)
    try:
        if not form.is_valid():
            raise ValidationError("Selecione uma única empresa FILHO desta configuração.")
        op = padronizacao.solicitar(plano, request.user, [form.cleaned_data["destinos"].pk])
        transaction.on_commit(lambda: central.publicar_cadastro(op))
        return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect("replicacao:detalhe", plano_id=plano.pk)


@ambiente_view
@require_POST
def confirmar_padronizacao(request, plano_id, cadastro_id):
    from . import padronizacao
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        op = padronizacao.confirmar(op, request.user, request.POST)
        if op.status == "fila":
            transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")


@ambiente_view
@require_POST
def resolver_nomes_padronizacao(request, plano_id, cadastro_id):
    from . import padronizacao
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        padronizacao.resolver_nomes(op, request.user, request.POST)
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")


@ambiente_view
@require_GET
def progresso_cadastro(request, plano_id, cadastro_id):
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    return JsonResponse(central.situacao(op))


@ambiente_view
@require_POST
def resolver_cadastro(request, plano_id, cadastro_id):
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        if request.POST.get("confirmar") != "sim":
            raise ValidationError("Confirme as decisões e o envio para o grupo.")
        op = central.resolver_cadastro(op, request.user, request.POST)
        transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")


@ambiente_view
@require_POST
def retomar_cadastro(request, plano_id, cadastro_id):
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        op = central.retomar(op, request.user)
        transaction.on_commit(lambda: central.publicar_cadastro(op))
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")


@ambiente_view
@require_POST
def verificar_cadastro(request, plano_id, empresa_id):
    from .tasks import verificar_cadastro as tarefa
    plano = plano_request(request, plano_id)
    linha = get_object_or_404(CadastroCategoriaEmpresa, pk=empresa_id, cadastro__plano=plano)
    try:
        central.conferir_grupo(plano, request.user)
        codigo = request.POST.get("codigo", "").strip()
        if linha.status != "incerto" or (codigo and (len(codigo) > 20 or any(c not in "0123456789." for c in codigo))):
            raise ValidationError("Selecione um envio sem confirmação e informe um código válido.")
        tarefa.apply_async(args=[linha.pk, request.user.pk, codigo], queue="omie_replicacao", retry=False)
        messages.success(request, "Verificação solicitada; nenhuma inclusão ou alteração será repetida.")
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    except Exception:
        messages.error(request, "Worker indisponível; tente verificar novamente.")
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={linha.cadastro_id}")


@ambiente_view
@require_POST
def cancelar_cadastro(request, plano_id, cadastro_id):
    plano = plano_request(request, plano_id)
    op = get_object_or_404(plano.cadastros, pk=cadastro_id)
    try:
        if request.POST.get("confirmar") != "sim":
            raise ValidationError("Confirme o cancelamento das etapas restantes desta requisição.")
        central.cancelar(op, request.user)
        messages.success(request, "Requisição cancelada. Os registros já enviados à OMIE foram preservados.")
    except (ValidationError, PermissionDenied) as exc:
        informar_erro(request, exc)
    return redirect(reverse("replicacao:detalhe", args=[plano.pk]) + f"?cadastro={op.pk}")
