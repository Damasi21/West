import json
from decimal import Decimal
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.empresas.services import usuario_gestor_empresa, usuario_pode_acessar_dashboard
from apps.dashboards.dre_services import _formatar_moeda
from .catalogo import REGRAS
from .forms import PoliticaForm, TratamentoForm
from .models import CasoAuditoria, EventoAuditoria, ExecucaoAuditoria, PoliticaAuditoria
from .services import fontes_empresa, politicas_empresa, solicitar_execucao
from .tasks import executar_auditoria_task


def _contexto(request, empresa_slug, tela):
    from apps.dashboards.views import _contexto_base
    contexto = _contexto_base(request, empresa_slug)
    empresa = contexto["empresa"]
    if not usuario_pode_acessar_dashboard(request.user, empresa, "auditor", tela):
        raise Http404
    contexto.update(area_slug="auditor", dashboard_slug=tela, tela=tela,
                    pode_tratar=usuario_gestor_empresa(request.user, empresa))
    for pagina in ("visao-geral", "alertas", "regras"):
        contexto["pode_" + pagina.replace("-", "_")] = usuario_pode_acessar_dashboard(request.user, empresa, "auditor", pagina)
    return contexto


@login_required
@require_GET
def visao_geral(request, empresa_slug):
    contexto = _contexto(request, empresa_slug, "visao-geral")
    empresa = contexto["empresa"]
    casos = CasoAuditoria.objects.filter(empresa=empresa)
    contexto.update(
        fontes=fontes_empresa(empresa), execucoes=ExecucaoAuditoria.objects.filter(empresa=empresa)[:8],
        ultima_execucao=ExecucaoAuditoria.objects.filter(empresa=empresa, status="concluida").first(),
        execucao_ativa=ExecucaoAuditoria.objects.filter(empresa=empresa, status__in=["fila", "executando"]).first(),
        recentes=casos.select_related("responsavel")[:6],
        novos=casos.filter(status="novo").count(), em_analise=casos.filter(status="analise").count(),
        criticos=casos.filter(severidade="critico").exclude(status__in=["resolvido", "justificado"]).count(),
        encerrados=casos.filter(status__in=["resolvido", "justificado"]).count(),
    )
    ativa = contexto["execucao_ativa"]
    contexto["espera_expirada"] = bool(ativa and ativa.status == "fila" and ativa.criada_em < timezone.now() - timedelta(minutes=30))
    ultima = contexto["ultima_execucao"]
    contexto["cobertura_linhas"] = [
        {"regra": REGRAS.get(codigo, {}).get("titulo", codigo), **valores}
        for codigo, valores in (ultima.resumo.get("cobertura", {}) if ultima else {}).items()
    ]
    return render(request, "auditor/visao_geral.html", contexto)


@login_required
@require_GET
def alertas(request, empresa_slug):
    contexto = _contexto(request, empresa_slug, "alertas")
    casos = CasoAuditoria.objects.filter(empresa=contexto["empresa"]).select_related("responsavel")
    for campo, escolhas in (("status", CasoAuditoria.Status.values), ("severidade", PoliticaAuditoria.Severidade.values), ("regra", REGRAS)):
        valor = request.GET.get(campo, "")
        if valor in escolhas:
            casos = casos.filter(**{campo: valor})
    busca = request.GET.get("q", "").strip()[:150]
    if busca:
        filtro = Q(titulo__icontains=busca)
        if busca.isascii() and busca.isdigit() and len(busca) <= 18:
            filtro |= Q(pk=int(busca))
        casos = casos.filter(filtro)
    contexto.update(pagina=Paginator(casos, 25).get_page(request.GET.get("page")),
                    status_opcoes=CasoAuditoria.Status.choices, severidade_opcoes=PoliticaAuditoria.Severidade.choices,
                    regras=REGRAS, filtros=request.GET)
    return render(request, "auditor/alertas.html", contexto)


@login_required
@require_http_methods(["GET", "POST"])
def detalhe(request, empresa_slug, caso_id):
    contexto = _contexto(request, empresa_slug, "alertas")
    empresa = contexto["empresa"]
    caso = get_object_or_404(CasoAuditoria.objects.select_related("responsavel", "ultima_execucao"), empresa=empresa, pk=caso_id)
    usuarios = get_user_model().objects.filter(is_active=True).filter(
        Q(vinculos_empresas__empresa=empresa, vinculos_empresas__ativo=True)
        | Q(ambientes_white_label_administrados__ativa=True, ambientes_white_label_administrados__empresas=empresa)
    ).distinct()
    if request.user.is_superuser:
        usuarios = get_user_model().objects.filter(is_active=True).filter(Q(pk__in=usuarios.values("pk")) | Q(pk=request.user.pk))
    form = TratamentoForm(request.POST or None, caso=caso, usuarios=usuarios)
    if request.method == "POST":
        if not contexto["pode_tratar"]:
            return HttpResponseForbidden()
        if form.is_valid():
            with transaction.atomic():
                atual = CasoAuditoria.objects.select_for_update().get(pk=caso.pk, empresa=empresa)
                antes = atual.get_status_display()
                atual.status = form.cleaned_data["status"]
                atual.responsavel = form.cleaned_data["responsavel"]
                atual.save(update_fields=["status", "responsavel"])
                EventoAuditoria.objects.create(empresa=empresa, caso=atual, autor=request.user,
                    acao=f"{antes} > {atual.get_status_display()}",
                    descricao=f"Responsavel: {atual.responsavel or 'Nao atribuido'}. {form.cleaned_data['comentario']}")
            messages.success(request, "Tratamento registrado.")
            return redirect("auditor:detalhe", empresa_slug=empresa.slug, caso_id=caso.pk)
    evidencias = Paginator(caso.evidencias.select_related("execucao"), 10).get_page(request.GET.get("page"))
    for evidencia in evidencias:
        evidencia.texto = json.dumps(evidencia.dados, ensure_ascii=False, indent=2)
        dados = evidencia.dados.get("evidencia", {})
        evidencia.itens = dados.get("titulos", [dados["titulo"]] if "titulo" in dados else [])
        for item in evidencia.itens:
            item["valor_formatado"] = _formatar_moeda(Decimal(item["valor_original"]))
        evidencia.campos = []
        for chave, rotulo in (("mediana", "Mediana historica"), ("limite", "Limite de alerta"),
                              ("categoria_habitual", "Categoria habitual"), ("campos_ausentes", "Campos ausentes"),
                              ("codigo", "Cadastro"), ("captura_anterior", "Captura anterior"), ("captura_atual", "Captura atual"),
                              ("autor_na_origem", "Autor na origem")):
            if chave in dados and (chave != "limite" or evidencia.itens and "mediana" in dados):
                valor = dados[chave]
                if chave in {"mediana", "limite"}:
                    valor = _formatar_moeda(Decimal(valor))
                if isinstance(valor, list):
                    valor = ", ".join(valor)
                evidencia.campos.append((rotulo, valor))
        evidencia.referencia = dados.get("referencia")
    contexto.update(caso=caso, form=form, evidencias=evidencias,
                    eventos=caso.eventos.select_related("autor")[:100], regra=REGRAS.get(caso.regra))
    return render(request, "auditor/detalhe.html", contexto)


@login_required
@require_http_methods(["GET", "POST"])
def regras(request, empresa_slug):
    contexto = _contexto(request, empresa_slug, "regras")
    empresa = contexto["empresa"]
    politicas = list(politicas_empresa(empresa))
    alvo = request.POST.get("codigo") if request.method == "POST" else None
    linhas = []
    for politica in politicas:
        form = PoliticaForm(request.POST if alvo == politica.codigo else None, politica=politica,
                            auto_id=f"id_{politica.codigo}_%s")
        if alvo == politica.codigo:
            if not contexto["pode_tratar"]:
                return HttpResponseForbidden()
            if form.is_valid():
                with transaction.atomic():
                    atual = PoliticaAuditoria.objects.select_for_update().get(pk=politica.pk)
                    antes = {"ativa": atual.ativa, "severidade": atual.severidade, "parametros": atual.parametros}
                    atual.ativa = form.cleaned_data["ativa"]
                    atual.severidade = form.cleaned_data["severidade"]
                    atual.parametros = {k: float(v) if k == "multiplicador_valor" else v for k, v in form.cleaned_data.items() if k not in {"ativa", "severidade"}}
                    atual.save()
                    EventoAuditoria.objects.create(empresa=empresa, autor=request.user, acao=f"Politica: {politica.codigo}",
                        descricao=json.dumps({"anterior": antes, "atual": {"ativa": atual.ativa, "severidade": atual.severidade, "parametros": atual.parametros}}, ensure_ascii=False))
                messages.success(request, "Politica atualizada. Aplicacao a partir da proxima execucao.")
                return redirect("auditor:regras", empresa_slug=empresa.slug)
        linhas.append({"politica": politica, "regra": REGRAS[politica.codigo], "form": form})
    if request.method == "POST" and alvo not in REGRAS:
        raise Http404
    contexto.update(linhas=linhas, eventos=EventoAuditoria.objects.filter(empresa=empresa, caso__isnull=True).select_related("autor")[:30])
    return render(request, "auditor/regras.html", contexto)


@login_required
@require_POST
def executar(request, empresa_slug):
    contexto = _contexto(request, empresa_slug, "visao-geral")
    if not contexto["pode_tratar"]:
        return HttpResponseForbidden()
    execucao, nova = solicitar_execucao(contexto["empresa"], request.user)
    if nova:
        try:
            executar_auditoria_task.apply_async(args=[execucao.pk], queue="auditor", retry=False)
            messages.success(request, "Auditoria adicionada a fila do Auditor.")
        except Exception:
            # A worker may already have started if the broker reply was lost.
            alteradas = ExecucaoAuditoria.objects.filter(pk=execucao.pk, status="fila").update(
                status="erro", finalizada_em=timezone.now(), erro="Falha ao enviar a fila. Verifique Redis e auditor_worker e tente novamente.")
            messages.error(request, "Nao foi possivel confirmar o envio. Confira a execucao antes de tentar novamente." if not alteradas else "Falha ao enviar a fila do Auditor. Tente novamente apos verificar o worker.")
    else:
        messages.info(request, "Ja existe uma auditoria na fila ou em andamento para esta empresa.")
    return redirect("auditor:visao_geral", empresa_slug=empresa_slug)


@login_required
@require_POST
def encerrar_espera(request, empresa_slug, execucao_id):
    contexto = _contexto(request, empresa_slug, "visao-geral")
    if not contexto["pode_tratar"]:
        return HttpResponseForbidden()
    with transaction.atomic():
        execucao = get_object_or_404(ExecucaoAuditoria.objects.select_for_update(),
                                    empresa=contexto["empresa"], pk=execucao_id)
        if execucao.status == "fila" and execucao.criada_em < timezone.now() - timedelta(minutes=30):
            execucao.status = "erro"
            execucao.finalizada_em = timezone.now()
            execucao.erro = "Espera expirada encerrada pelo responsavel. Verificar o worker antes de solicitar novamente."
            execucao.save(update_fields=["status", "finalizada_em", "erro"])
            EventoAuditoria.objects.create(empresa=contexto["empresa"], autor=request.user,
                acao=f"Espera encerrada: #{execucao.pk}", descricao="Execucao ainda nao iniciada apos 30 minutos. Nenhuma tarefa em andamento foi interrompida.")
            messages.success(request, "Espera encerrada. Confira o worker antes de executar novamente.")
        else:
            messages.info(request, "Execucao ja iniciada ou espera ainda nao expirada. Nenhuma alteracao realizada.")
    return redirect("auditor:visao_geral", empresa_slug=empresa_slug)
