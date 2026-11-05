"""Contrato de categorias. Escritas sempre fazem uma única tentativa HTTP."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.empresas.omie import CATEGORIAS_URL, SSL_CONTEXT, _abrir_requisicao_omie, OmieAPIError, _eh_limite_diario_omie


class OmieIncerta(Exception):
    pass


class OmieRecusada(Exception):
    pass


class ConsultaRecusada(ValidationError):
    """Safe, actionable read errors; never changes uncertain-write semantics."""


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
        return f"A OMIE recusou a consulta de categorias (HTTP {status.group(1)}). Confira a disponibilidade e as permissões do aplicativo."
    return "A consulta de categorias não foi confirmada pela OMIE. Confira a integração e tente novamente mais tarde."


def chamada(integracao, metodo, parametros):
    assert metodo in {"ListarCategorias", "IncluirCategoria", "IncluirGrupoCategoria", "AlterarCategoria", "AlterarGrupoCategoria"}
    corpo = {"call": metodo, "param": [parametros], "app_key": integracao.app_key, "app_secret": integracao.obter_app_secret()}
    request = Request(CATEGORIAS_URL, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        abertura = _abrir_requisicao_omie(request, settings.OMIE_API_TIMEOUT) if metodo == "ListarCategorias" else urlopen(request, timeout=settings.OMIE_API_TIMEOUT, context=SSL_CONTEXT)
        with abertura as response:
            dados = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, OmieAPIError) as exc:
        if metodo == "ListarCategorias":
            raise ConsultaRecusada(motivo_consulta(exc)) from exc
        # HTTP failures, including 429, never trigger an automatic write replay.
        raise OmieIncerta("A OMIE não confirmou a comunicação. Consulte o resultado antes de repetir qualquer inclusão.") from exc
    if not isinstance(dados, dict) or "faultstring" in dados or "faultcode" in dados:
        if metodo == "ListarCategorias":
            raise ConsultaRecusada(motivo_consulta(dados.get("faultstring", "") if isinstance(dados, dict) else ""))
        raise OmieIncerta("Resposta OMIE sem confirmação. Nenhuma repetição automática será feita.")
    if metodo != "ListarCategorias":
        status = str(dados.get("codigo_status", "")).strip()
        if status and status.lstrip("0"):
            if status.isdigit():
                raise OmieRecusada("A OMIE recusou a operação. Confira a compatibilidade do cadastro no aplicativo destino.")
            raise OmieIncerta("Status OMIE não reconhecido. Verifique antes de repetir.")
        if not status or not str(dados.get("codigo") or "").strip():
            raise OmieIncerta("Resposta sem código e confirmação de sucesso. Verifique na OMIE.")
    return dados


def listar(integracao, descricao=""):
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
