"""Contrato de categorias. Escritas sempre fazem uma única tentativa HTTP."""
import json
import re
import time
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.empresas.omie import CATEGORIAS_URL, SSL_CONTEXT, _abrir_requisicao_omie, OmieAPIError, _eh_limite_diario_omie


class OmieIncerta(Exception):
    def __init__(self, mensagem="", *, detalhe=""):
        super().__init__(mensagem)
        self.detalhe = detalhe


class OmieRecusada(Exception):
    def __init__(self, mensagem="", *, detalhe="", codigo=""):
        super().__init__(mensagem)
        self.detalhe = detalhe
        self.codigo = codigo


class ConsultaRecusada(ValidationError):
    """Safe, actionable read errors; never changes uncertain-write semantics."""


def eh_duplicidade(erro):
    detalhe = getattr(erro, "detalhe", "").casefold()
    return (getattr(erro, "codigo", "") == "102" and "existe" in detalhe
        and any(campo in detalhe for campo in ("descri", "nome")))


def detalhe_envio(dados, integracao):
    """Only structured provider messages, with known credentials redacted."""
    if not isinstance(dados, dict):
        return ""
    valor = dados.get("faultstring") or dados.get("descricao_status") or ""
    if not isinstance(valor, str):
        return ""
    for segredo in (integracao.app_key, integracao.obter_app_secret()):
        if segredo:
            valor = re.sub(re.escape(segredo), "[redigido]", valor, flags=re.IGNORECASE)
    return valor.strip()[:1000]


def motivo_consulta(erro):
    texto = str(erro)
    if _eh_limite_diario_omie(texto):
        numero = re.search(r"limite de (\d{1,6}) requisi", texto, re.IGNORECASE)
        limite = f" de {numero.group(1)} requisições" if numero else ""
        return (f"A OMIE informou que o limite diário{limite} deste aplicativo foi atingido. "
            "Aguarde a renovação da cota informada pela OMIE ou verifique o plano do aplicativo. "
            "Retomar a consulta agora não libera essa cota.")
    if any(t in texto.casefold() for t in ("app_key", "app_secret", "autentic", "credencia")):
        return "A OMIE não autorizou a consulta. Confira as credenciais e as permissões da integração desta empresa."
    status = re.search(r"HTTP (\d{3})", texto)
    if status:
        if status.group(1).startswith("5"):
            return f"A consulta de categorias não foi concluída pela OMIE (HTTP {status.group(1)}). Tente novamente mais tarde; se persistir, consulte os logs de integração da OMIE."
        return f"A OMIE recusou a consulta de categorias (HTTP {status.group(1)}). Confira a disponibilidade e as permissões do aplicativo."
    return "A consulta de categorias não foi confirmada pela OMIE. Confira a integração e tente novamente mais tarde."


def falha_ack_servidor(erro):
    # Only this structured protocol error is retryable here. Generic HTTP 500
    # may represent business validation, authentication or malformed parameters.
    resultado = re.search(r"HTTP 500:\s*(\{.*\})\s*$", str(erro), re.DOTALL)
    if not resultado:
        return False
    try:
        dados = json.loads(resultado.group(1))
    except ValueError:
        return False
    return isinstance(dados, dict) and dados.get("proto") == "CLIENT_ACK_SERVER_ERROR"


def abrir_consulta_categorias(request, pagina):
    for tentativa in range(1, 4):
        try:
            return _abrir_requisicao_omie(request, settings.OMIE_API_TIMEOUT)
        except OmieAPIError as exc:
            if not falha_ack_servidor(exc):
                raise
            if tentativa == 3:
                raise ConsultaRecusada(
                    f"ListarCategorias: página {pagina}. A OMIE retornou CLIENT_ACK_SERVER_ERROR "
                    "e não confirmou esta leitura após 3 tentativas. A lista incompleta não será usada. "
                    "Tente retomar a consulta mais tarde; se persistir, informe esse código ao suporte da OMIE."
                ) from exc
            time.sleep(5 * tentativa)


def chamada(integracao, metodo, parametros):
    assert metodo in {"ListarCategorias", "IncluirCategoria", "IncluirGrupoCategoria", "AlterarCategoria", "AlterarGrupoCategoria"}
    corpo = {"call": metodo, "param": [parametros], "app_key": integracao.app_key, "app_secret": integracao.obter_app_secret()}
    request = Request(CATEGORIAS_URL, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        abertura = abrir_consulta_categorias(request, parametros.get("pagina", 1)) if metodo == "ListarCategorias" else urlopen(request, timeout=settings.OMIE_API_TIMEOUT, context=SSL_CONTEXT)
        with abertura as response:
            dados = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, OmieAPIError) as exc:
        if metodo == "ListarCategorias":
            raise ConsultaRecusada(f'ListarCategorias: página {parametros.get("pagina", 1)}. {motivo_consulta(exc)}') from exc
        # HTTP failures, including 429, never trigger an automatic write replay.
        detalhe = ""
        if isinstance(exc, HTTPError):
            dados_erro = None
            try:
                dados_erro = json.loads(exc.read(16384).decode("utf-8"))
                detalhe = detalhe_envio(dados_erro, integracao)
            except (ValueError, OSError):
                pass
            if isinstance(dados_erro, dict):
                status = str(dados_erro.get("codigo_status", "")).strip()
                if status.isdigit() and int(status) > 0 and not dados_erro.get("codigo"):
                    raise OmieRecusada("A OMIE recusou a operação.", detalhe=f"OMIE recusou a operação (código {status}): {detalhe}", codigo=status) from exc
            detalhe = f"OMIE retornou HTTP {exc.code}" + (f": {detalhe}" if detalhe else ".")
        elif isinstance(exc, TimeoutError):
            detalhe = "Tempo limite de resposta da OMIE excedido. O envio pode ter sido recebido; verifique o resultado sem reenviar."
        elif isinstance(exc, URLError):
            detalhe = "Falha de conexão com a OMIE. Não foi possível confirmar o resultado do envio."
        elif isinstance(exc, ValueError):
            detalhe = "A resposta da OMIE não pôde ser interpretada. Verifique o resultado antes de repetir."
        elif isinstance(exc, OSError):
            detalhe = "A conexão com a OMIE foi interrompida antes da confirmação do resultado."
        raise OmieIncerta("A OMIE não confirmou a comunicação. Consulte o resultado antes de repetir qualquer inclusão.", detalhe=detalhe) from exc
    if not isinstance(dados, dict) or "faultstring" in dados or "faultcode" in dados:
        if metodo == "ListarCategorias":
            raise ConsultaRecusada(motivo_consulta(dados.get("faultstring", "") if isinstance(dados, dict) else ""))
        raise OmieIncerta("Resposta OMIE sem confirmação. Nenhuma repetição automática será feita.", detalhe=detalhe_envio(dados, integracao))
    if metodo != "ListarCategorias":
        status = str(dados.get("codigo_status", "")).strip()
        if status and status.lstrip("0"):
            if status.isdigit():
                raise OmieRecusada("A OMIE recusou a operação. Confira a compatibilidade do cadastro no aplicativo destino.", detalhe=detalhe_envio(dados, integracao), codigo=status)
            raise OmieIncerta("Status OMIE não reconhecido. Verifique antes de repetir.")
        if not status or not str(dados.get("codigo") or "").strip():
            raise OmieIncerta("Resposta sem código e confirmação de sucesso. Verifique na OMIE.")
    return dados


def listar(integracao, descricao=""):
    # OMIE escapes labels in responses but expects their literal text in filters.
    # Keep the returned snapshots unchanged for validation and audit.
    descricao = unescape(descricao)
    itens = []
    pagina = 1
    total_paginas = None
    while True:
        dados = chamada(integracao, "ListarCategorias", {"pagina": pagina, "registros_por_pagina": 50, "descricao": descricao})
        registros = dados.get("categoria_cadastro")
        try:
            paginas = int(dados["total_de_paginas"])
            registros_total = int(dados["total_de_registros"])
        except (KeyError, TypeError, ValueError):
            raise OmieIncerta("Listagem de categorias incompleta. A comparação não foi gerada.")
        if not isinstance(registros, list) or paginas < 0 or paginas > 1000 or registros_total < 0:
            raise OmieIncerta("Listagem de categorias inválida.")
        if total_paginas is not None and paginas != total_paginas:
            raise OmieIncerta("A listagem mudou durante a consulta. Compare novamente.")
        total_paginas = paginas
        for item in registros:
            if not isinstance(item, dict) or not str(item.get("codigo") or "").strip() or "descricao" not in item:
                raise OmieIncerta("Uma categoria retornada está incompleta.")
        itens.extend(registros)
        if pagina >= max(1, paginas):
            if len(itens) != registros_total or len({str(i['codigo']) for i in itens}) != len(itens):
                raise OmieIncerta("Contagem de categorias divergente. Compare novamente.")
            return itens
        pagina += 1
