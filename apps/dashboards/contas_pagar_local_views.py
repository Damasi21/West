from pathlib import Path
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.empresas.auditoria import registrar_acao
from apps.empresas.models import AcaoUsuarioLog
from apps.empresas.services import obter_empresa_permitida, usuario_gestor_empresa
from .contas_pagar_forms import ContaPagarLocalForm, MAX_ANEXOS, MAX_TOTAL_BYTES
from .models import AnexoContaPagarLocal, ContaPagarLocal, EnvioContasPagarLocal
from .contas_pagar_permissions import pode_cadastrar_conta_local, contas_locais_visiveis
from .contas_pagar_envio import preparar_envio, publicar_envio


def _empresa_cadastro(request, slug):
    empresa = obter_empresa_permitida(request.user, slug)
    if not pode_cadastrar_conta_local(request.user, empresa):
        raise PermissionDenied("Sem permissao para cadastrar contas a pagar.")
    return empresa


def _html_form(request, empresa, form):
    return render_to_string("dashboards/partials/conta_pagar_form.html", {"empresa": empresa, "form": form}, request=request)


def salvar_conta_local(form, empresa, usuario):
    arquivos_salvos = []
    try:
        with transaction.atomic():
            dados = {campo: form.cleaned_data[campo] for campo in form.Meta.fields}
            if form.instance.pk:
                conta = contas_locais_visiveis(usuario, empresa).select_for_update().get(pk=form.instance.pk)
                if not conta.editavel:
                    raise ValidationError("Conta enviada ou em processamento: alteracoes somente na OMIE apos a confirmacao.")
                if conta.token_cadastro != form.cleaned_data["token"]:
                    raise PermissionDenied("Cadastro indisponivel.")
                existentes = list(conta.anexos.all())
                if len(existentes) + len(form.arquivos) > MAX_ANEXOS or sum(a.tamanho for a in existentes) + sum(a.size for a in form.arquivos) > MAX_TOTAL_BYTES:
                    raise ValidationError("Limite de anexos excedido.")
                for campo, valor in dados.items():
                    setattr(conta, campo, valor)
                conta.status = ContaPagarLocal.Status.RASCUNHO
                conta.erro_envio = ""
                conta.save()
                criada = False
                gravar_arquivos = True
            else:
                conta, criada = ContaPagarLocal.objects.get_or_create(
                    token_cadastro=form.cleaned_data["token"],
                    defaults={**dados, "empresa": empresa, "criado_por": usuario},
                )
                if conta.empresa_id != empresa.pk or conta.criado_por_id != usuario.pk:
                    raise PermissionDenied("Cadastro indisponivel.")
                gravar_arquivos = criada
            if gravar_arquivos:
                for arquivo in form.arquivos:
                    nome = Path(arquivo.name.replace("\\", "/")).name[:150]
                    anexo = AnexoContaPagarLocal(conta=conta, nome_original=nome, tamanho=arquivo.size)
                    anexo.arquivo.save(arquivo.name, arquivo, save=False)
                    arquivos_salvos.append((anexo.arquivo.storage, anexo.arquivo.name))
                    anexo.save()
        return conta, criada
    except Exception:
        for storage, nome in arquivos_salvos:
            storage.delete(nome)
        raise


@login_required
@require_http_methods(["GET", "POST"])
def cadastrar_conta_pagar_local(request, empresa_slug):
    empresa = _empresa_cadastro(request, empresa_slug)
    identificador = (request.POST if request.method == "POST" else request.GET).get("conta_id")
    conta = None
    if identificador:
        if not identificador.isascii() or not identificador.isdigit():
            raise Http404("Conta nao encontrada.")
        conta = get_object_or_404(contas_locais_visiveis(request.user, empresa), pk=identificador)
        if not conta.editavel:
            return JsonResponse({"mensagem": "Conta bloqueada para edicao no BI. Alteracoes de contas enviadas devem ser feitas na OMIE."}, status=409)
    form = ContaPagarLocalForm(
        request.POST if request.method == "POST" else None,
        empresa=empresa, arquivos=request.FILES.getlist("anexos"), instance=conta,
    )
    if request.method == "GET":
        response = JsonResponse({"html": _html_form(request, empresa, form)})
    elif form.is_valid():
        try:
            conta, criada = salvar_conta_local(form, empresa, request.user)
        except OSError:
            form.add_error(None, "Nao foi possivel salvar os anexos. Tente novamente.")
            response = JsonResponse({"html": _html_form(request, empresa, form)}, status=503)
        except ValidationError as exc:
            form.add_error(None, exc)
            response = JsonResponse({"html": _html_form(request, empresa, form)}, status=409)
        else:
            if criada or identificador:
                registrar_acao(usuario=request.user, empresa=empresa, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
                               descricao="Conta a pagar salva como rascunho local", request=request,
                               dados={"conta_local_id": conta.pk})
            response = JsonResponse({"sucesso": True, "id": conta.pk,
                                     "quantidade": contas_locais_visiveis(request.user, empresa).count(),
                                     "mensagem": "Conta salva no BI como rascunho local. Nenhum dado foi enviado ao OMIE."})
    else:
        response = JsonResponse({"html": _html_form(request, empresa, form)}, status=400)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def listar_contas_pagar_locais(request, empresa_slug):
    empresa = _empresa_cadastro(request, empresa_slug)
    contas = contas_locais_visiveis(request.user, empresa).select_related("fornecedor", "categoria", "departamento", "conta_corrente", "criado_por", "envio").prefetch_related("anexos")
    pagina = Paginator(contas, 20).get_page(request.GET.get("pagina"))
    html = render_to_string("dashboards/partials/contas_pagar_locais.html", {"empresa": empresa, "pagina": pagina, "ver_autores": usuario_gestor_empresa(request.user, empresa)}, request=request)
    pagina_ids = {c.pk for c in pagina}
    pendentes = any(pagina_ids.intersection(ids) for ids in EnvioContasPagarLocal.objects.filter(
        empresa=empresa, status__in=["aguardando", "processando"]).values_list("contas_ids", flat=True))
    response = JsonResponse({"html": html, "pendentes": pendentes})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def baixar_anexo_conta_local(request, empresa_slug, anexo_id):
    empresa = _empresa_cadastro(request, empresa_slug)
    anexo = get_object_or_404(AnexoContaPagarLocal, pk=anexo_id, conta__in=contas_locais_visiveis(request.user, empresa))
    try:
        arquivo = anexo.arquivo.open("rb")
    except FileNotFoundError:
        raise Http404("Anexo indisponivel.")
    response = FileResponse(arquivo, as_attachment=True, filename=anexo.nome_original)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_POST
def enviar_contas_pagar_locais(request, empresa_slug):
    empresa = _empresa_cadastro(request, empresa_slug)
    try:
        dados = json.loads(request.body)
        if not isinstance(dados, dict) or dados.get("confirmar") is not True:
            raise ValidationError("Confirme explicitamente a operacao.")
        verificar = dados.get("acao") == "verificar"
        if dados.get("acao") not in {"enviar", "verificar"}:
            raise ValidationError("Operacao invalida.")
        envio = preparar_envio(request.user, empresa, dados.get("ids"), verificar=verificar)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"mensagem": "Solicitacao invalida."}, status=400)
    except ValidationError as exc:
        return JsonResponse({"mensagem": " ".join(exc.messages)}, status=400)
    transaction.on_commit(lambda: publicar_envio(envio))
    registrar_acao(usuario=request.user, empresa=empresa, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
                   descricao="Solicitacao de verificacao OMIE" if verificar else "Solicitacao de inclusao de contas na OMIE",
                   request=request, dados={"envio_id": envio.pk, "contas_ids": envio.contas_ids})
    return JsonResponse({"sucesso": True, "mensagem": "Solicitacao registrada. Acompanhe o resultado nos cadastros locais."}, status=202)
