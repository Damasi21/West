"""Attachments are independent from title creation: never recreate a confirmed title."""

import base64
import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath

from django.db import transaction
from django.utils import timezone

from .contas_pagar_forms import MAX_ANEXO_BYTES
from .contas_pagar_omie import incluir_anexo, consultar_anexo
from .models import AnexoContaPagarLocal, ContaPagarLocal


def dados_anexo(anexo):
    if anexo.conta.status != ContaPagarLocal.Status.ENVIADO or not anexo.conta.codigo_lancamento_omie:
        raise ValueError("A conta precisa estar confirmada na OMIE.")
    original = PurePosixPath(anexo.nome_original.replace("\\", "/")).name
    extensao = PurePosixPath(original).suffix.lower().lstrip(".")
    if extensao not in {"pdf", "png", "jpg", "jpeg"}:
        raise ValueError("Tipo de arquivo nao permitido.")
    # OMIE rejects multiple dots and paths; preserve the original name in the BI.
    nome = re.sub(r"[^\w -]", "_", PurePosixPath(original).stem).strip(" _") or "Anexo"
    nome = f"{nome[:95-len(extensao)]}.{extensao}"
    with anexo.arquivo.open("rb") as arquivo:
        conteudo = arquivo.read(MAX_ANEXO_BYTES + 1)
    if not conteudo or len(conteudo) > MAX_ANEXO_BYTES or len(conteudo) != anexo.tamanho:
        raise ValueError("Arquivo ausente, alterado ou acima do limite.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pacote:
        info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        pacote.writestr(info, conteudo)
    compactado = buffer.getvalue()
    arquivo_base64 = base64.b64encode(compactado).decode("ascii")
    return {"cCodIntAnexo": anexo.codigo_integracao, "cTabela": "conta-pagar",
            "nId": anexo.conta.codigo_lancamento_omie, "cNomeArquivo": nome,
            "cTipoArquivo": extensao, "cArquivo": arquivo_base64,
            # OMIE validates the text in cArquivo, not the raw ZIP bytes.
            "cMd5": hashlib.md5(arquivo_base64.encode("ascii"), usedforsecurity=False).hexdigest()}


def _confirmar(anexo, resposta):
    try:
        codigo = int(resposta.get("nIdAnexo") or 0)
        if "nCodTitulo" in resposta:
            # Finance-specific API does not return nIdAnexo. Its receipt is the
            # exact integration key bound to a positive title and file name.
            if (int(resposta["nCodTitulo"]) != anexo.conta.codigo_lancamento_omie
                    or resposta.get("cCodIntAnexo") != anexo.codigo_integracao
                    or not isinstance(resposta.get("cNomeArq"), str) or not resposta["cNomeArq"].strip()):
                return False
        else:
            if codigo <= 0 or resposta.get("cCodIntAnexo", anexo.codigo_integracao) != anexo.codigo_integracao:
                return False
            if str(resposta.get("cTabela", "conta-pagar")) != "conta-pagar" or int(resposta.get("nId", anexo.conta.codigo_lancamento_omie)) != anexo.conta.codigo_lancamento_omie:
                return False
        if "cCodStatus" in resposta and int(str(resposta["cCodStatus"])) != 0:
            return False
    except (TypeError, ValueError):
        return False
    AnexoContaPagarLocal.objects.filter(pk=anexo.pk).exclude(status_omie="enviado").update(
        status_omie="enviado", codigo_anexo_omie=codigo or None, enviado_em=timezone.now(), erro_omie="")
    return True


def processar_anexos(conta, integracao):
    if conta.status != ContaPagarLocal.Status.ENVIADO or not conta.codigo_lancamento_omie:
        return
    for anexo_id in conta.anexos.exclude(status_omie="enviado").values_list("pk", flat=True):
        with transaction.atomic():
            anexo = AnexoContaPagarLocal.objects.select_for_update().get(pk=anexo_id)
            anexo.conta = conta
            if anexo.status_omie == "enviado":
                continue
            consultar = anexo.status_omie in {"enviando", "incerto"}
            if not consultar:
                # Construct before reserving a network attempt; local failures are safe to retry.
                try:
                    dados = dados_anexo(anexo)
                except Exception:
                    anexo.status_omie = "erro"
                    anexo.erro_omie = "Arquivo indisponivel para envio. Confira o anexo local."
                    anexo.save(update_fields=["status_omie", "erro_omie"])
                    continue
                anexo.status_omie = "enviando"
                anexo.erro_omie = ""
                anexo.save(update_fields=["status_omie", "erro_omie"])
        try:
            resposta = (consultar_anexo(integracao, anexo.codigo_integracao, conta.codigo_lancamento_omie)
                        if consultar else incluir_anexo(integracao, dados))
            if _confirmar(anexo, resposta):
                continue
            recusado = False
            try:
                recusado = not consultar and int(str(resposta.get("cCodStatus"))) > 0 and not resposta.get("nIdAnexo")
            except (TypeError, ValueError):
                pass
            AnexoContaPagarLocal.objects.filter(pk=anexo.pk).exclude(status_omie="enviado").update(
                status_omie="erro" if recusado else "incerto",
                erro_omie="A OMIE recusou este anexo. Tente novamente." if recusado else "Anexo sem confirmacao. Verifique na OMIE antes de novo envio.")
        except Exception:
            AnexoContaPagarLocal.objects.filter(pk=anexo.pk).exclude(status_omie="enviado").update(
                status_omie="incerto", erro_omie="Comunicacao sem confirmacao do anexo. A conta permanece enviada; a proxima verificacao apenas consultara o anexo.")
