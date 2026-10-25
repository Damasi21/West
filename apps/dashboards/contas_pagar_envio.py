from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.empresas.models import IntegracaoOmie
from apps.empresas.auditoria import registrar_acao
from apps.empresas.models import AcaoUsuarioLog
from .contas_pagar_forms import ContaPagarLocalForm
from .contas_pagar_permissions import contas_locais_visiveis, pode_cadastrar_conta_local
from .contas_pagar_omie import ResultadoOmieIncerto, incluir_conta_pagar, incluir_contas_pagar_lote, consultar_conta_por_integracao
from .models import ContaPagarLocal, EnvioContasPagarLocal


def _status_omie(resposta):
    try:
        return int(str(resposta.get("codigo_status")).strip())
    except (TypeError, ValueError):
        return None


def dados_inclusao(conta):
    # Revalidate related records against the same tenant immediately before dispatch.
    dados = {campo: getattr(conta, campo + "_id") if campo in {"fornecedor", "categoria", "departamento", "conta_corrente"} else getattr(conta, campo)
             for campo in ContaPagarLocalForm.Meta.fields}
    form = ContaPagarLocalForm({**dados, "token": conta.token_cadastro}, empresa=conta.empresa)
    if not form.is_valid():
        raise ValidationError(f"Conta #{conta.pk}: confira fornecedor, categoria, centro de custo, conta corrente e demais campos antes do envio.")
    if conta.data_vencimento < timezone.localdate() or (conta.data_previsao or conta.data_vencimento) < timezone.localdate():
        raise ValidationError(f"Conta #{conta.pk}: vencimento e previsao devem ser iguais ou posteriores a hoje para inclusao na OMIE.")
    valor = float(conta.valor)
    if Decimal(str(valor)) != conta.valor:
        raise ValidationError(f"Conta #{conta.pk}: valor excede a precisao suportada para envio.")
    if len(conta.documento) > 20:
        raise ValidationError(f"Conta #{conta.pk}: o documento/NF deve ter no maximo 20 caracteres para envio a OMIE.")
    observacao = " | ".join(filter(None, [conta.descricao, conta.observacoes.replace("\n", " | "), f"Forma de pagamento: {conta.get_forma_pagamento_display()}"]))
    return {
        "codigo_lancamento_integracao": conta.codigo_integracao,
        "codigo_cliente_fornecedor": conta.fornecedor.codigo_cliente_omie,
        "data_vencimento": conta.data_vencimento.strftime("%d/%m/%Y"),
        "valor_documento": valor, "codigo_categoria": conta.categoria.codigo,
        "data_previsao": (conta.data_previsao or conta.data_vencimento).strftime("%d/%m/%Y"),
        "id_conta_corrente": conta.conta_corrente.codigo_omie,
        "data_emissao": conta.data_emissao.strftime("%d/%m/%Y"),
        "numero_documento": conta.documento, "observacao": observacao,
        "distribuicao": [{"cCodDep": conta.departamento.codigo, "nPerDep": 100, "nValDep": valor}],
        "baixar_documento": "N", "conciliar_documento": "N",
    }


def preparar_envio(usuario, empresa, ids, verificar=False):
    if not pode_cadastrar_conta_local(usuario, empresa):
        raise PermissionDenied
    if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
        raise ValidationError("Selecione de 1 a 50 contas distintas.")
    with transaction.atomic():
        contas = list(contas_locais_visiveis(usuario, empresa).select_for_update().filter(pk__in=ids).order_by("pk"))
        if len(contas) != len(ids):
            raise PermissionDenied("Uma das contas nao esta disponivel para seu usuario.")
        if not IntegracaoOmie.objects.filter(empresa=empresa, ativa=True).exists():
            raise ValidationError("A empresa nao possui integracao OMIE ativa.")
        if verificar:
            for conta in contas:
                if conta.editavel:
                    raise ValidationError("Esta conta ainda nao possui envio a confirmar.")
                if conta.status == ContaPagarLocal.Status.ENVIANDO and conta.envio and conta.envio.status == "processando" and conta.envio.iniciado_em > timezone.now() - timedelta(minutes=5):
                    raise ValidationError("O envio ainda esta em processamento. Aguarde antes de verificar.")
            # A queued job can be published again safely: the DB claim prevents duplicate writes.
            aguardando = {c.envio_id for c in contas if c.envio and c.envio.status == "aguardando"}
            if aguardando:
                if len(aguardando) == 1 and all(c.envio_id in aguardando for c in contas):
                    existente = EnvioContasPagarLocal.objects.get(pk=aguardando.pop())
                    if contas_locais_visiveis(usuario, empresa).filter(pk__in=existente.contas_ids).count() != len(existente.contas_ids):
                        raise ValidationError("Aguarde o processamento do lote solicitado pelo gestor.")
                    return existente
                raise ValidationError("Verifique separadamente os envios que aguardam o worker.")
        else:
            if any(not c.editavel for c in contas):
                raise ValidationError("Uma das contas ja foi enviada ou aguarda confirmacao. O envio nao pode ser repetido.")
        payloads = {} if verificar else {c.pk: dados_inclusao(c) for c in contas}
        envio = EnvioContasPagarLocal.objects.create(empresa=empresa, solicitado_por=usuario,
                                                    operacao="verificacao" if verificar else "inclusao", contas_ids=ids,
                                                    payloads=list(payloads.values()))
        if not verificar:
            for conta in contas:
                conta.status = ContaPagarLocal.Status.ENVIANDO
                conta.envio = envio
                conta.dados_envio = payloads[conta.pk]
                conta.erro_envio = ""
                conta.save(update_fields=["status", "envio", "dados_envio", "erro_envio"])
        return envio


def publicar_envio(envio):
    from .tasks import processar_contas_pagar_locais
    try:
        processar_contas_pagar_locais.apply_async(args=[envio.pk], queue="omie_manual", task_id=str(envio.token), retry=False)
    except Exception:
        EnvioContasPagarLocal.objects.filter(pk=envio.pk, status="aguardando").update(erro="Aguardando conexao com o worker. Use Verificar envio para reenfileirar com seguranca.")
        return False
    return True


def _confirmar(conta, resposta, usuario):
    try:
        codigo = int(resposta.get("codigo_lancamento_omie") or 0)
    except (TypeError, ValueError):
        codigo = 0
    referencia = resposta.get("codigo_lancamento_integracao")
    if codigo <= 0 or (referencia and referencia != conta.codigo_integracao):
        return False
    if conta.status == ContaPagarLocal.Status.ENVIADO:
        return conta.codigo_lancamento_omie == codigo
    autor = conta.envio.solicitado_por if conta.envio and conta.envio.solicitado_por else usuario
    alterados = ContaPagarLocal.objects.filter(pk=conta.pk).exclude(status="enviado").update(
        status=ContaPagarLocal.Status.ENVIADO, codigo_lancamento_omie=codigo,
        enviado_em=conta.enviado_em or timezone.now(), enviado_por=autor, erro_envio="",
    )
    if alterados:
        registrar_acao(usuario=autor, empresa=conta.empresa, tipo=AcaoUsuarioLog.Tipo.ALTERACAO,
                       descricao="Inclusao de conta a pagar confirmada na OMIE",
                       dados={"conta_local_id": conta.pk, "codigo_lancamento_omie": codigo})
    return True


def executar_envio(envio_id):
    with transaction.atomic():
        envio = EnvioContasPagarLocal.objects.select_for_update(of=("self",)).select_related("empresa", "solicitado_por").get(pk=envio_id)
        if envio.status != "aguardando":
            return "ja_processado"
        envio.status = "processando"
        envio.iniciado_em = timezone.now()
        envio.save(update_fields=["status", "iniciado_em"])
    usuario = envio.solicitado_por
    try:
        contas = list(ContaPagarLocal.objects.filter(pk__in=envio.contas_ids, empresa=envio.empresa).select_related("fornecedor", "categoria", "departamento", "conta_corrente", "empresa", "envio__solicitado_por").order_by("pk"))
        permitidas = set(contas_locais_visiveis(usuario, envio.empresa).filter(pk__in=envio.contas_ids).values_list("pk", flat=True)) if usuario else set()
        if len(contas) != len(envio.contas_ids) or not usuario or not envio.empresa.ativa or not pode_cadastrar_conta_local(usuario, envio.empresa) or any(c.pk not in permitidas for c in contas):
            raise ValidationError("Acesso revogado antes do processamento; nenhum novo envio realizado.")
        integracao = IntegracaoOmie.objects.filter(empresa=envio.empresa, ativa=True).first()
        if not integracao:
            raise ValidationError("Integracao OMIE indisponivel; nenhum novo envio realizado.")
        if envio.operacao == "verificacao":
            for conta in contas:
                try:
                    resposta = consultar_conta_por_integracao(integracao, conta.codigo_integracao)
                    if not _confirmar(conta, resposta, usuario):
                        ContaPagarLocal.objects.filter(pk=conta.pk).exclude(status="enviado").update(erro_envio="A OMIE ainda nao confirmou este codigo. O envio permanece bloqueado para evitar duplicidade.")
                except ResultadoOmieIncerto as exc:
                    ContaPagarLocal.objects.filter(pk=conta.pk).exclude(status="enviado").update(erro_envio=str(exc))
        else:
            if any(c.status != ContaPagarLocal.Status.ENVIANDO or c.envio_id != envio.pk for c in contas):
                raise ValidationError("Estado do cadastro alterado. Nenhum novo envio foi realizado.")
            # Revalidation is allowed; the write uses the immutable snapshot reserved by the request.
            for conta in contas:
                dados_inclusao(conta)
            if len(contas) == 1:
                conta = contas[0]
                resposta = incluir_conta_pagar(integracao, conta.dados_envio)
                if _status_omie(resposta) == 0 and _confirmar(conta, resposta, usuario):
                    pass
                elif _status_omie(resposta) is not None and _status_omie(resposta) != 0 and not resposta.get("codigo_lancamento_omie"):
                    ContaPagarLocal.objects.filter(pk=conta.pk, envio=envio).update(status="erro", erro_envio="A OMIE recusou a inclusao. Revise os dados antes de enviar novamente.")
                else:
                    ContaPagarLocal.objects.filter(pk=conta.pk, envio=envio).update(status="confirmar", erro_envio="Aguardando confirmacao do codigo na OMIE.")
            else:
                resposta = incluir_contas_pagar_lote(integracao, envio.pk, [c.dados_envio for c in contas])
                aceito = _status_omie(resposta) == 0
                ContaPagarLocal.objects.filter(envio=envio, status="enviando").update(
                    status="confirmar" if aceito else "incerto",
                    erro_envio="Lote recebido. Verifique na OMIE para confirmar cada conta." if aceito else "Resultado do lote nao confirmado. Verifique cada conta antes de qualquer novo envio.",
                )
            envio.resposta = {k: resposta[k] for k in ["codigo_status", "codigo_lancamento_omie", "lote"] if k in resposta}
        from .contas_pagar_anexos import processar_anexos
        for conta in contas:
            conta.refresh_from_db()
            processar_anexos(conta, integracao)
    except ValidationError as exc:
        envio.erro = " ".join(exc.messages)
        if envio.operacao == "inclusao":
            ContaPagarLocal.objects.filter(envio=envio, status="enviando").update(status="erro", erro_envio=envio.erro)
    except Exception:
        # A crash/timeout is not evidence that a financial write failed remotely.
        envio.erro = "Resultado nao confirmado. Consulte a OMIE; nenhum reenvio automatico sera feito."
        if envio.operacao == "inclusao":
            ContaPagarLocal.objects.filter(envio=envio, status="enviando").update(status="incerto", erro_envio=envio.erro)
    finally:
        envio.status = "finalizado"
        envio.finalizado_em = timezone.now()
        envio.save(update_fields=["status", "finalizado_em", "resposta", "erro"])
    return "processado"
