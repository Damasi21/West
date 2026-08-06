import json
import re
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore
from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    CadastroOmie,
    CategoriaOmie,
    ContaCorrenteOmie,
    ContratoItemOmie,
    ContratoOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    DepartamentoOmie,
    LancamentoContaCorrenteOmie,
    MovimentoFinanceiroOmie,
    OrdemServicoItemOmie,
    OrdemServicoOmie,
    PedidoCompraItemOmie,
    PedidoCompraOmie,
    PedidoItemOmie,
    PedidoOmie,
    PosicaoEstoqueOmie,
    ProdutoOmie,
    ProjetoOmie,
    ServicoOmie,
    SincronizacaoOmie,
    TipoContaCorrenteOmie,
    VendedorOmie,
)


CLIENTES_URL = "https://app.omie.com.br/api/v1/geral/clientes/"
PROJETOS_URL = "https://app.omie.com.br/api/v1/geral/projetos/"
DEPARTAMENTOS_URL = "https://app.omie.com.br/api/v1/geral/departamentos/"
VENDEDORES_URL = "https://app.omie.com.br/api/v1/geral/vendedores/"
PRODUTOS_URL = "https://app.omie.com.br/api/v1/geral/produtos/"
CATEGORIAS_URL = "https://app.omie.com.br/api/v1/geral/categorias/"
TIPOS_CONTA_CORRENTE_URL = "https://app.omie.com.br/api/v1/geral/tipocc/"
CONTAS_CORRENTES_URL = "https://app.omie.com.br/api/v1/geral/contacorrente/"
CONTAS_PAGAR_URL = "https://app.omie.com.br/api/v1/financas/contapagar/"
CONTAS_RECEBER_URL = "https://app.omie.com.br/api/v1/financas/contareceber/"
EXTRATO_CONTA_CORRENTE_URL = "https://app.omie.com.br/api/v1/financas/extrato/"
RESUMO_FINANCAS_URL = "https://app.omie.com.br/api/v1/financas/resumo/"
MOVIMENTOS_FINANCEIROS_URL = "https://app.omie.com.br/api/v1/financas/mf/"
LANCAMENTOS_CONTA_CORRENTE_URL = (
    "https://app.omie.com.br/api/v1/financas/contacorrentelancamentos/"
)
PEDIDOS_URL = "https://app.omie.com.br/api/v1/produtos/pedido/"
PEDIDOS_COMPRA_URL = "https://app.omie.com.br/api/v1/produtos/pedidocompra/"
POSICAO_ESTOQUE_URL = "https://app.omie.com.br/api/v1/estoque/consulta/"
SERVICOS_URL = "https://app.omie.com.br/api/v1/servicos/servico/"
ORDENS_SERVICO_URL = "https://app.omie.com.br/api/v1/servicos/os/"
CONTRATOS_URL = "https://app.omie.com.br/api/v1/servicos/contrato/"
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="omie-sync")


class OmieAPIError(Exception):
    pass


class _RespostaOmieLocal:
    def __init__(self, dados):
        self._dados = dados

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self._dados).encode("utf-8")


def _detalhe_http_omie(exc):
    corpo = exc.read().decode("utf-8", errors="replace")
    if not corpo:
        return f"resposta sem corpo ({exc.reason or 'sem detalhe'})"
    try:
        dados = json.loads(corpo)
    except json.JSONDecodeError:
        return corpo
    if not isinstance(dados, dict):
        return corpo
    for chave in ("faultstring", "message", "error", "faultcode"):
        detalhe = dados.get(chave)
        if detalhe:
            return detalhe
    return corpo


def _eh_consumo_redundante_omie(detalhe):
    detalhe_normalizado = str(detalhe or "").casefold()
    return (
        "redundant" in detalhe_normalizado
        or "consumo redundante" in detalhe_normalizado
    )


def _eh_pagina_sem_registros_omie(detalhe):
    detalhe_normalizado = str(detalhe or "").casefold()
    return (
        "não existem registros para a página" in detalhe_normalizado
        or "nao existem registros para a pagina" in detalhe_normalizado
    )


def _pagina_requisicao_omie(request):
    try:
        payload = json.loads(request.data.decode("utf-8"))
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        return 1
    parametros = payload.get("param") or [{}]
    if not parametros or not isinstance(parametros[0], dict):
        return 1
    return parametros[0].get("pagina") or parametros[0].get("nPagina") or 1


def _resposta_sem_registros_omie(request):
    pagina = _pagina_requisicao_omie(request)
    return _RespostaOmieLocal(
        {
            "pagina": pagina,
            "nPagina": pagina,
            "total_de_paginas": 1,
            "total_de_registros": 0,
            "nTotPaginas": 1,
            "nTotRegistros": 0,
        }
    )


def _espera_consumo_redundante_omie(detalhe):
    espera_padrao = getattr(settings, "OMIE_API_REDUNDANT_DELAY", 60)
    margem = getattr(settings, "OMIE_API_REDUNDANT_BUFFER", 5)
    resultado = re.search(
        r"aguarde\s+(\d+)\s+segundos",
        str(detalhe),
        re.IGNORECASE,
    )
    if resultado:
        return int(resultado.group(1)) + margem
    return espera_padrao + margem


def _fechar_conexoes_antigas_fora_de_transacao():
    if not connection.in_atomic_block:
        close_old_connections()


def _abrir_requisicao_omie(request, timeout):
    tentativas = getattr(settings, "OMIE_API_RETRIES", 3)
    espera = getattr(settings, "OMIE_API_RETRY_DELAY", 2)
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            return urlopen(request, timeout=timeout, context=SSL_CONTEXT)
        except HTTPError as exc:
            detalhe = _detalhe_http_omie(exc)
            if exc.code == 500:
                if _eh_pagina_sem_registros_omie(detalhe):
                    return _resposta_sem_registros_omie(request)
                if _eh_consumo_redundante_omie(detalhe):
                    ultimo_erro = OmieAPIError(
                        f"OMIE respondeu HTTP {exc.code}: {detalhe}"
                    )
                    if tentativa == tentativas:
                        raise ultimo_erro from exc
                    time.sleep(_espera_consumo_redundante_omie(detalhe))
                    continue
            raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
        except (URLError, TimeoutError) as exc:
            ultimo_erro = exc
            if tentativa == tentativas:
                raise
            time.sleep(espera * tentativa)
    raise ultimo_erro


def _sim_nao(valor):
    return str(valor).upper() == "S"


def _decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _inteiro_ou_none(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _data_omie(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor), "%d/%m/%Y").date()
    except ValueError:
        return None


def _tipo_cadastro(tags):
    nomes = {
        str(item.get("tag", "")).strip().casefold()
        for item in (tags or [])
        if isinstance(item, dict)
    }
    cliente = "cliente" in nomes
    fornecedor = "fornecedor" in nomes
    if cliente and fornecedor:
        return CadastroOmie.Tipo.AMBOS
    if cliente:
        return CadastroOmie.Tipo.CLIENTE
    if fornecedor:
        return CadastroOmie.Tipo.FORNECEDOR
    return CadastroOmie.Tipo.OUTRO


def consultar_clientes(integracao, pagina, registros_por_pagina=50):
    payload = {
        "call": "ListarClientes",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CLIENTES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_projetos(integracao, pagina, registros_por_pagina=50):
    payload = {
        "call": "ListarProjetos",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        PROJETOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_departamentos(integracao, pagina, registros_por_pagina=50):
    payload = {
        "call": "ListarDepartamentos",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        DEPARTAMENTOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_vendedores(integracao, pagina, registros_por_pagina=100):
    payload = {
        "call": "ListarVendedores",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        VENDEDORES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_produtos(integracao, pagina, registros_por_pagina=50):
    payload = {
        "call": "ListarProdutos",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
                "filtrar_apenas_omiepdv": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        PRODUTOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_categorias(integracao, pagina, registros_por_pagina=50):
    payload = {
        "call": "ListarCategorias",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "descricao": "",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CATEGORIAS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_tipos_conta_corrente(
    integracao,
    pagina,
    registros_por_pagina=50,
):
    payload = {
        "call": "ListarTiposCC",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        TIPOS_CONTA_CORRENTE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_contas_correntes(
    integracao,
    pagina,
    registros_por_pagina=100,
):
    payload = {
        "call": "ListarContasCorrentes",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CONTAS_CORRENTES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_contas_pagar(
    integracao,
    pagina,
    registros_por_pagina=20,
):
    payload = {
        "call": "ListarContasPagar",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CONTAS_PAGAR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def alterar_conta_pagar(integracao, dados_conta):
    payload = {
        "call": "AlterarContaPagar",
        "param": [dados_conta],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CONTAS_PAGAR_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Nao foi possivel conectar a OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invalida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_contas_receber(
    integracao,
    pagina,
    registros_por_pagina=20,
):
    payload = {
        "call": "ListarContasReceber",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CONTAS_RECEBER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_lancamentos_conta_corrente(
    integracao,
    pagina,
    registros_por_pagina=20,
):
    payload = {
        "call": "ListarLancCC",
        "param": [
            {
                "nPagina": pagina,
                "nRegPorPagina": registros_por_pagina,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        LANCAMENTOS_CONTA_CORRENTE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_movimentos_financeiros(
    integracao,
    pagina,
    registros_por_pagina=500,
):
    payload = {
        "call": "ListarMovimentos",
        "param": [
            {
                "nPagina": pagina,
                "nRegPorPagina": registros_por_pagina,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        MOVIMENTOS_FINANCEIROS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_extrato_conta_corrente(
    integracao,
    conta_corrente,
    data_inicial="",
    data_final="",
):
    hoje = timezone.localdate()
    data_inicial = data_inicial or date(hoje.year, 1, 1).strftime("%d/%m/%Y")
    data_final = data_final or hoje.strftime("%d/%m/%Y")
    payload = {
        "call": "ListarExtrato",
        "param": [
            {
                "nCodCC": conta_corrente.codigo_omie,
                "cCodIntCC": conta_corrente.codigo_integracao,
                "dPeriodoInicial": data_inicial,
                "dPeriodoFinal": data_final,
                "cExibirApenasSaldo": "S",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        EXTRATO_CONTA_CORRENTE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_resumo_financas(integracao, dia=None):
    dia = dia or timezone.localdate()
    payload = {
        "call": "ObterResumoFinancas",
        "param": [
            {
                "dDia": dia.strftime("%d/%m/%Y"),
                "lApenasResumo": True,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        RESUMO_FINANCAS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Não foi possível conectar à OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta inválida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_pedidos(
    integracao,
    pagina,
    registros_por_pagina=100,
):
    payload = {
        "call": "ListarPedidos",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        PEDIDOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_pedidos_compra(
    integracao,
    pagina,
    registros_por_pagina=100,
    inicio=None,
    fim=None,
):
    hoje = timezone.localdate()
    inicio = inicio or date(hoje.year, 1, 1)
    fim = fim or date(hoje.year, 12, 31)
    payload = {
        "call": "PesquisarPedCompra",
        "param": [
            {
                "nPagina": pagina,
                "nRegsPorPagina": registros_por_pagina,
                "lApenasImportadoApi": "F",
                "lExibirPedidosPendentes": "T",
                "lExibirPedidosFaturados": "F",
                "lExibirPedidosRecebidos": "F",
                "lExibirPedidosCancelados": "F",
                "lExibirPedidosEncerrados": "F",
                "lExibirPedidosRecParciais": "F",
                "lExibirPedidosFatParciais": "F",
                "dDataInicial": inicio.strftime("%d/%m/%Y"),
                "dDataFinal": fim.strftime("%d/%m/%Y"),
                "lApenasAlterados": "F",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        PEDIDOS_COMPRA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"Nao foi possivel conectar a OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invalida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_posicoes_estoque(
    integracao,
    pagina,
    registros_por_pagina=50,
    dia=None,
):
    dia = dia or timezone.localdate()
    payload = {
        "call": "ListarPosEstoque",
        "param": [
            {
                "nPagina": pagina,
                "nRegPorPagina": registros_por_pagina,
                "dDataPosicao": dia.strftime("%d/%m/%Y"),
                "cExibeTodos": "N",
                "codigo_local_estoque": 0,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        POSICAO_ESTOQUE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_servicos(
    integracao,
    pagina,
    registros_por_pagina=20,
):
    payload = {
        "call": "ListarCadastroServico",
        "param": [
            {
                "nPagina": pagina,
                "nRegPorPagina": registros_por_pagina,
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        SERVICOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_ordens_servico(
    integracao,
    pagina,
    registros_por_pagina=50,
):
    payload = {
        "call": "ListarOS",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        ORDENS_SERVICO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def consultar_contratos(
    integracao,
    pagina,
    registros_por_pagina=50,
):
    payload = {
        "call": "ListarContratos",
        "param": [
            {
                "pagina": pagina,
                "registros_por_pagina": registros_por_pagina,
                "apenas_importado_api": "N",
            }
        ],
        "app_key": integracao.app_key,
        "app_secret": integracao.obter_app_secret(),
    }
    request = Request(
        CONTRATOS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = getattr(settings, "OMIE_API_TIMEOUT", 45)
    try:
        with _abrir_requisicao_omie(request, timeout) as response:
            dados = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        corpo = exc.read().decode("utf-8", errors="replace")
        try:
            detalhe = json.loads(corpo).get("faultstring", corpo)
        except json.JSONDecodeError:
            detalhe = corpo
        raise OmieAPIError(f"OMIE respondeu HTTP {exc.code}: {detalhe}") from exc
    except (URLError, TimeoutError) as exc:
        raise OmieAPIError(f"NÃ£o foi possÃ­vel conectar Ã  OMIE: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OmieAPIError("A OMIE retornou uma resposta invÃ¡lida.") from exc

    if "faultstring" in dados:
        raise OmieAPIError(dados["faultstring"])
    return dados


def _valores_cadastro(item):
    tags = item.get("tags") or []
    return {
        "codigo_cliente_integracao": str(item.get("codigo_cliente_integracao") or ""),
        "tipo": _tipo_cadastro(tags),
        "razao_social": str(item.get("razao_social") or ""),
        "nome_fantasia": str(item.get("nome_fantasia") or ""),
        "cnpj_cpf": str(item.get("cnpj_cpf") or ""),
        "pessoa_fisica": _sim_nao(item.get("pessoa_fisica")),
        "inativo": _sim_nao(item.get("inativo")),
        "bloquear_faturamento": _sim_nao(item.get("bloquear_faturamento")),
        "exterior": _sim_nao(item.get("exterior")),
        "enviar_anexos": _sim_nao(item.get("enviar_anexos")),
        "inscricao_estadual": str(item.get("inscricao_estadual") or ""),
        "inscricao_municipal": str(item.get("inscricao_municipal") or ""),
        "endereco": str(item.get("endereco") or ""),
        "endereco_numero": str(item.get("endereco_numero") or ""),
        "complemento": str(item.get("complemento") or ""),
        "bairro": str(item.get("bairro") or ""),
        "cidade": str(item.get("cidade") or ""),
        "cidade_ibge": str(item.get("cidade_ibge") or ""),
        "estado": str(item.get("estado") or ""),
        "cep": str(item.get("cep") or ""),
        "codigo_pais": str(item.get("codigo_pais") or ""),
        "dados_bancarios": item.get("dadosBancarios") or {},
        "endereco_entrega": item.get("enderecoEntrega") or {},
        "recomendacoes": item.get("recomendacoes") or {},
        "tags": tags,
        "info": item.get("info") or {},
        "dados_originais": item,
    }


def _salvar_clientes(empresa, itens):
    processados = 0
    for item in itens:
        codigo = item.get("codigo_cliente_omie")
        if codigo in (None, ""):
            continue
        CadastroOmie.objects.update_or_create(
            empresa=empresa,
            codigo_cliente_omie=int(codigo),
            defaults=_valores_cadastro(item),
        )
        processados += 1
    return processados


def _salvar_projetos(empresa, itens):
    processados = 0
    for item in itens:
        codigo = item.get("codigo")
        if codigo in (None, ""):
            continue
        ProjetoOmie.objects.update_or_create(
            empresa=empresa,
            codigo=int(codigo),
            defaults={
                "codigo_integracao": str(
                    item.get("codInt") or item.get("codint") or ""
                ),
                "nome": str(item.get("nome") or ""),
                "inativo": _sim_nao(item.get("inativo")),
                "info": item.get("info") or {},
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_departamentos(empresa, itens):
    processados = 0
    for item in itens:
        codigo = str(item.get("codigo") or "").strip()
        if not codigo:
            continue
        DepartamentoOmie.objects.update_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={
                "descricao": str(item.get("descricao") or ""),
                "estrutura": str(item.get("estrutura") or ""),
                "inativo": _sim_nao(item.get("inativo")),
                "nivel_totalizador": _sim_nao(item.get("nivel_totalizador")),
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_vendedores(empresa, itens):
    processados = 0
    for item in itens:
        codigo = _inteiro_ou_none(item.get("codigo"))
        if codigo is None:
            continue
        VendedorOmie.objects.update_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={
                "codigo_integracao": str(item.get("codInt") or ""),
                "nome": str(item.get("nome") or ""),
                "email": str(item.get("email") or ""),
                "comissao": _decimal(item.get("comissao")),
                "fatura_pedido": _sim_nao(item.get("fatura_pedido")),
                "visualiza_pedido": _sim_nao(item.get("visualiza_pedido")),
                "inativo": _sim_nao(item.get("inativo")),
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_produtos(empresa, itens):
    processados = 0
    for item in itens:
        codigo_produto = _inteiro_ou_none(item.get("codigo_produto"))
        if codigo_produto is None:
            continue
        ProdutoOmie.objects.update_or_create(
            empresa=empresa,
            codigo_produto=codigo_produto,
            defaults={
                "codigo": str(item.get("codigo") or ""),
                "codigo_produto_integracao": str(
                    item.get("codigo_produto_integracao") or ""
                ),
                "descricao": str(item.get("descricao") or ""),
                "descr_detalhada": str(item.get("descr_detalhada") or ""),
                "unidade": str(item.get("unidade") or ""),
                "ncm": str(item.get("ncm") or ""),
                "ean": str(item.get("ean") or ""),
                "marca": str(item.get("marca") or ""),
                "modelo": str(item.get("modelo") or ""),
                "tipo_item": str(item.get("tipoItem") or ""),
                "valor_unitario": _decimal(item.get("valor_unitario")),
                "quantidade_estoque": _decimal(item.get("quantidade_estoque")),
                "estoque_minimo": _decimal(item.get("estoque_minimo")),
                "peso_bruto": _decimal(item.get("peso_bruto")),
                "peso_liq": _decimal(item.get("peso_liq")),
                "altura": _decimal(item.get("altura")),
                "largura": _decimal(item.get("largura")),
                "profundidade": _decimal(item.get("profundidade")),
                "codigo_familia": _inteiro_ou_none(item.get("codigo_familia")),
                "codigo_integracao_familia": str(
                    item.get("codInt_familia") or ""
                ),
                "descricao_familia": str(item.get("descricao_familia") or ""),
                "bloqueado": _sim_nao(item.get("bloqueado")),
                "inativo": _sim_nao(item.get("inativo")),
                "importado_api": _sim_nao(item.get("importado_api")),
                "produto_lote": _sim_nao(item.get("produto_lote")),
                "produto_variacao": _sim_nao(item.get("produto_variacao")),
                "bloquear_exclusao": _sim_nao(item.get("bloquear_exclusao")),
                "info": item.get("info") or {},
                "recomendacoes_fiscais": item.get("recomendacoes_fiscais") or {},
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_posicoes_estoque(empresa, itens):
    codigos_produtos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("nCodProd"))]
        if codigo is not None
    }
    produtos = {
        produto.codigo_produto: produto
        for produto in ProdutoOmie.objects.filter(
            empresa=empresa,
            codigo_produto__in=codigos_produtos,
        )
    }
    data_posicao = timezone.localdate()
    processados = 0
    for item in itens:
        codigo_produto = _inteiro_ou_none(item.get("nCodProd"))
        if codigo_produto is None:
            continue
        codigo_local = _inteiro_ou_none(item.get("codigo_local_estoque")) or 0
        PosicaoEstoqueOmie.objects.update_or_create(
            empresa=empresa,
            codigo_produto=codigo_produto,
            codigo_local_estoque=codigo_local,
            defaults={
                "produto": produtos.get(codigo_produto),
                "codigo": str(item.get("cCodigo") or ""),
                "codigo_integracao": str(item.get("cCodInt") or ""),
                "descricao": str(item.get("cDescricao") or ""),
                "data_posicao": data_posicao,
                "estoque_minimo": _decimal(item.get("estoque_minimo")),
                "fisico": _decimal(item.get("fisico")),
                "pendente": _decimal(item.get("nPendente")),
                "reservado": _decimal(item.get("reservado")),
                "saldo": _decimal(item.get("nSaldo")),
                "cmc": _decimal(item.get("nCMC")),
                "preco_unitario": _decimal(item.get("nPrecoUnitario")),
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_servicos(empresa, itens):
    codigos_categorias = {
        str((item.get("cabecalho") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("cabecalho") or {}).get("cCodCateg") or "").strip()
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }

    processados = 0
    for item in itens:
        cabecalho = item.get("cabecalho") or {}
        descricao = item.get("descricao") or {}
        impostos = item.get("impostos") or {}
        info = item.get("info") or {}
        int_listar = item.get("intListar") or {}
        codigo_servico = _inteiro_ou_none(int_listar.get("nCodServ"))
        if codigo_servico is None:
            continue

        codigo_categoria = str(cabecalho.get("cCodCateg") or "").strip()
        ServicoOmie.objects.update_or_create(
            empresa=empresa,
            codigo_servico=codigo_servico,
            defaults={
                "codigo_integracao_servico": str(
                    int_listar.get("cCodIntServ") or ""
                ),
                "codigo": str(cabecalho.get("cCodigo") or ""),
                "descricao": str(cabecalho.get("cDescricao") or ""),
                "descricao_completa": str(descricao.get("cDescrCompleta") or ""),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_lc116": str(cabecalho.get("cCodLC116") or ""),
                "codigo_servico_municipal": str(
                    cabecalho.get("cCodServMun") or ""
                ),
                "id_tributacao": str(cabecalho.get("cIdTrib") or ""),
                "tipo_desconto": str(cabecalho.get("cTipoDesc") or ""),
                "preco_unitario": _decimal(cabecalho.get("nPrecoUnit")),
                "aliquota_desconto": _decimal(cabecalho.get("nAliqDesc")),
                "valor_desconto": _decimal(cabecalho.get("nValorDesc")),
                "aliquota_iss": _decimal(impostos.get("nAliqISS")),
                "ret_cofins": _sim_nao(impostos.get("cRetCOFINS")),
                "ret_csll": _sim_nao(impostos.get("cRetCSLL")),
                "ret_inss": _sim_nao(impostos.get("cRetINSS")),
                "ret_ir": _sim_nao(impostos.get("cRetIR")),
                "ret_iss": _sim_nao(impostos.get("cRetISS")),
                "ret_pis": _sim_nao(impostos.get("cRetPIS")),
                "deduz_iss": bool(impostos.get("lDeduzISS")),
                "importado_api": _sim_nao(info.get("cImpAPI")),
                "inativo": _sim_nao(info.get("inativo")),
                "cabecalho": cabecalho,
                "descricao_dados": descricao,
                "impostos": impostos,
                "info": info,
                "int_listar": int_listar,
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_ordens_servico(empresa, itens):
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("Cabecalho") or {}).get("nCodCli"))]
        if codigo is not None
    }
    codigos_contas = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("InformacoesAdicionais") or {}).get("nCodCC"))
        ]
        if codigo is not None
    }
    codigos_categorias = {
        str((item.get("InformacoesAdicionais") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("InformacoesAdicionais") or {}).get("cCodCateg") or "").strip()
    }
    codigos_servicos = {
        codigo
        for item in itens
        for servico in item.get("ServicosPrestados") or []
        for codigo in [_inteiro_ou_none(servico.get("nCodServico"))]
        if codigo not in (None, 0)
    }
    codigos_categorias.update(
        str(servico.get("cCodCategItem") or "").strip()
        for item in itens
        for servico in item.get("ServicosPrestados") or []
        if str(servico.get("cCodCategItem") or "").strip()
    )

    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=codigos_contas,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    servicos = {
        servico.codigo_servico: servico
        for servico in ServicoOmie.objects.filter(
            empresa=empresa,
            codigo_servico__in=codigos_servicos,
        )
    }

    processados = 0
    for item in itens:
        cabecalho = item.get("Cabecalho") or {}
        codigo_os = _inteiro_ou_none(cabecalho.get("nCodOS"))
        if codigo_os is None:
            continue

        info = item.get("InfoCadastro") or {}
        informacoes = item.get("InformacoesAdicionais") or {}
        codigo_cliente = _inteiro_ou_none(cabecalho.get("nCodCli"))
        codigo_conta = _inteiro_ou_none(informacoes.get("nCodCC"))
        codigo_vendedor = _inteiro_ou_none(cabecalho.get("nCodVend"))
        codigo_categoria = str(informacoes.get("cCodCateg") or "").strip()
        ordem_servico, _criado = OrdemServicoOmie.objects.update_or_create(
            empresa=empresa,
            codigo_os=codigo_os,
            defaults={
                "codigo_integracao_os": str(cabecalho.get("cCodIntOS") or ""),
                "numero_os": str(cabecalho.get("cNumOS") or ""),
                "etapa": str(cabecalho.get("cEtapa") or ""),
                "codigo_parcela": str(cabecalho.get("cCodParc") or ""),
                "codigo_cliente": codigo_cliente,
                "cliente": clientes.get(codigo_cliente),
                "data_previsao": _data_omie(cabecalho.get("dDtPrevisao")),
                "quantidade_parcelas": int(cabecalho.get("nQtdeParc") or 0),
                "valor_total": _decimal(cabecalho.get("nValorTotal")),
                "valor_total_impostos_retidos": _decimal(
                    cabecalho.get("nValorTotalImpRet")
                ),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "codigo_vendedor": codigo_vendedor,
                "cidade_prestacao": str(informacoes.get("cCidPrestServ") or ""),
                "numero_contrato": str(informacoes.get("cNumContrato") or ""),
                "numero_recibo": str(informacoes.get("cNumRecibo") or ""),
                "uso_consumo": _sim_nao(informacoes.get("cUsoConsumo")),
                "cancelada": _sim_nao(info.get("cCancelada")),
                "faturada": _sim_nao(info.get("cFaturada")),
                "origem": str(info.get("cOrigem") or ""),
                "data_inclusao": _data_omie(info.get("dDtInc")),
                "data_alteracao": _data_omie(info.get("dDtAlt")),
                "data_faturamento": _data_omie(info.get("dDtFat")),
                "cabecalho": cabecalho,
                "departamentos": item.get("Departamentos") or [],
                "email": item.get("Email") or {},
                "info_cadastro": info,
                "informacoes_adicionais": informacoes,
                "observacoes": item.get("Observacoes") or {},
                "parcelas": item.get("Parcelas") or [],
                "servicos_prestados": item.get("ServicosPrestados") or [],
                "dados_originais": item,
            },
        )

        itens_ativos = set()
        for servico_item in item.get("ServicosPrestados") or []:
            codigo_item = _inteiro_ou_none(servico_item.get("nIdItem"))
            if codigo_item is None:
                continue

            codigo_servico = _inteiro_ou_none(servico_item.get("nCodServico"))
            if codigo_servico == 0:
                codigo_servico = None
            codigo_categoria_item = str(
                servico_item.get("cCodCategItem") or ""
            ).strip()
            impostos = servico_item.get("impostos") or {}
            OrdemServicoItemOmie.objects.update_or_create(
                empresa=empresa,
                codigo_item=codigo_item,
                defaults={
                    "ordem_servico": ordem_servico,
                    "sequencia": int(servico_item.get("nSeqItem") or 0),
                    "codigo_servico": codigo_servico,
                    "servico": servicos.get(codigo_servico),
                    "descricao": str(servico_item.get("cDescServ") or ""),
                    "codigo_categoria": codigo_categoria_item,
                    "categoria_principal": categorias.get(codigo_categoria_item),
                    "codigo_lc116": str(servico_item.get("cCodServLC116") or ""),
                    "codigo_servico_municipal": str(
                        servico_item.get("cCodServMun") or ""
                    ),
                    "tributacao_servico": str(servico_item.get("cTribServ") or ""),
                    "quantidade": _decimal(servico_item.get("nQtde")),
                    "valor_unitario": _decimal(servico_item.get("nValUnit")),
                    "aliquota_desconto": _decimal(
                        servico_item.get("nAliqDesconto")
                    ),
                    "valor_desconto": _decimal(
                        servico_item.get("nValorDesconto")
                    ),
                    "valor_acrescimos": _decimal(
                        servico_item.get("nValorAcrescimos")
                    ),
                    "valor_outras_retencoes": _decimal(
                        servico_item.get("nValorOutrasRetencoes")
                    ),
                    "aliquota_iss": _decimal(impostos.get("nAliqISS")),
                    "valor_iss": _decimal(impostos.get("nValorISS")),
                    "base_iss": _decimal(impostos.get("nBaseISS")),
                    "nao_gerar_financeiro": _sim_nao(
                        servico_item.get("cNaoGerarFinanceiro")
                    ),
                    "reembolso": _sim_nao(servico_item.get("cReembolso")),
                    "retem_iss": _sim_nao(servico_item.get("cRetemISS")),
                    "deduz_iss": bool(impostos.get("lDeduzISS")),
                    "impostos": impostos,
                    "dados_originais": servico_item,
                },
            )
            itens_ativos.add(codigo_item)

        OrdemServicoItemOmie.objects.filter(
            empresa=empresa,
            ordem_servico=ordem_servico,
        ).exclude(codigo_item__in=itens_ativos).delete()
        processados += 1
    return processados


def _salvar_contratos(empresa, itens):
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("cabecalho") or {}).get("nCodCli"))]
        if codigo is not None
    }
    codigos_contas = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("infAdic") or {}).get("nCodCC"))]
        if codigo is not None
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("infAdic") or {}).get("nCodProj"))]
        if codigo not in (None, 0)
    }
    codigos_categorias = {
        str((item.get("infAdic") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("infAdic") or {}).get("cCodCateg") or "").strip()
    }
    codigos_categorias.update(
        str((item.get("despesasReembolsaveis") or {}).get("cCodCategReemb") or "").strip()
        for item in itens
        if str((item.get("despesasReembolsaveis") or {}).get("cCodCategReemb") or "").strip()
    )
    codigos_servicos = {
        codigo
        for item in itens
        for detalhe in item.get("itensContrato") or []
        for codigo in [
            _inteiro_ou_none((detalhe.get("itemCabecalho") or {}).get("codServico"))
        ]
        if codigo not in (None, 0)
    }
    codigos_categorias.update(
        str((detalhe.get("itemCabecalho") or {}).get("cCodCategItem") or "").strip()
        for item in itens
        for detalhe in item.get("itensContrato") or []
        if str((detalhe.get("itemCabecalho") or {}).get("cCodCategItem") or "").strip()
    )

    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=codigos_contas,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    servicos = {
        servico.codigo_servico: servico
        for servico in ServicoOmie.objects.filter(
            empresa=empresa,
            codigo_servico__in=codigos_servicos,
        )
    }

    processados = 0
    for item in itens:
        cabecalho = item.get("cabecalho") or {}
        codigo_contrato = _inteiro_ou_none(cabecalho.get("nCodCtr"))
        if codigo_contrato is None:
            continue

        informacoes = item.get("infAdic") or {}
        despesas = item.get("despesasReembolsaveis") or {}
        codigo_cliente = _inteiro_ou_none(cabecalho.get("nCodCli"))
        codigo_conta = _inteiro_ou_none(informacoes.get("nCodCC"))
        codigo_projeto = _inteiro_ou_none(informacoes.get("nCodProj"))
        if codigo_projeto == 0:
            codigo_projeto = None
        codigo_categoria = str(informacoes.get("cCodCateg") or "").strip()
        codigo_categoria_reembolso = str(
            despesas.get("cCodCategReemb") or ""
        ).strip()

        contrato, _criado = ContratoOmie.objects.update_or_create(
            empresa=empresa,
            codigo_contrato=codigo_contrato,
            defaults={
                "codigo_integracao_contrato": str(cabecalho.get("cCodIntCtr") or ""),
                "numero_contrato": str(cabecalho.get("cNumCtr") or ""),
                "codigo_situacao": str(cabecalho.get("cCodSit") or ""),
                "tipo_faturamento": str(cabecalho.get("cTipoFat") or ""),
                "codigo_cliente": codigo_cliente,
                "cliente": clientes.get(codigo_cliente),
                "vigencia_inicial": _data_omie(cabecalho.get("dVigInicial")),
                "vigencia_final": _data_omie(cabecalho.get("dVigFinal")),
                "dia_faturamento": int(cabecalho.get("nDiaFat") or 0),
                "valor_total_mes": _decimal(cabecalho.get("nValTotMes")),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_categoria_reembolso": codigo_categoria_reembolso,
                "categoria_reembolso": categorias.get(codigo_categoria_reembolso),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "codigo_vendedor": _inteiro_ou_none(informacoes.get("nCodVend")),
                "cidade_prestacao": str(informacoes.get("cCidPrestServ") or ""),
                "uso_consumo": _sim_nao(informacoes.get("cUsoConsumo")),
                "cabecalho": cabecalho,
                "departamentos": item.get("departamentos") or [],
                "despesas_reembolsaveis": despesas,
                "email_cliente": item.get("emailCliente") or {},
                "informacoes_adicionais": informacoes,
                "observacoes": item.get("observacoes") or {},
                "venc_textos": item.get("vencTextos") or {},
                "dados_originais": item,
            },
        )

        itens_ativos = set()
        for detalhe in item.get("itensContrato") or []:
            item_cabecalho = detalhe.get("itemCabecalho") or {}
            codigo_item = _inteiro_ou_none(item_cabecalho.get("codItem"))
            if codigo_item is None:
                continue

            codigo_servico = _inteiro_ou_none(item_cabecalho.get("codServico"))
            if codigo_servico == 0:
                codigo_servico = None
            codigo_categoria_item = str(
                item_cabecalho.get("cCodCategItem") or ""
            ).strip()
            item_descricao = detalhe.get("itemDescrServ") or {}
            item_impostos = detalhe.get("itemImpostos") or {}
            ContratoItemOmie.objects.update_or_create(
                empresa=empresa,
                codigo_item=codigo_item,
                defaults={
                    "contrato": contrato,
                    "sequencia": int(item_cabecalho.get("seq") or 0),
                    "codigo_servico": codigo_servico,
                    "servico": servicos.get(codigo_servico),
                    "descricao": str(item_descricao.get("descrCompleta") or ""),
                    "codigo_categoria": codigo_categoria_item,
                    "categoria_principal": categorias.get(codigo_categoria_item),
                    "codigo_lc116": str(item_cabecalho.get("codLC116") or ""),
                    "codigo_servico_municipal": str(
                        item_cabecalho.get("codServMunic") or ""
                    ),
                    "codigo_nbs": str(item_cabecalho.get("codNBS") or ""),
                    "natureza_operacao": str(
                        item_cabecalho.get("natOperacao") or ""
                    ),
                    "nao_gerar_financeiro": _sim_nao(
                        item_cabecalho.get("cNaoGerarFinanceiro")
                    ),
                    "quantidade": _decimal(item_cabecalho.get("quant")),
                    "valor_unitario": _decimal(item_cabecalho.get("valorUnit")),
                    "valor_total": _decimal(item_cabecalho.get("valorTotal")),
                    "valor_acrescimo": _decimal(
                        item_cabecalho.get("valorAcrescimo")
                    ),
                    "valor_deducao": _decimal(item_cabecalho.get("valorDed")),
                    "valor_desconto": _decimal(
                        item_cabecalho.get("valorDesconto")
                    ),
                    "valor_outras_retencoes": _decimal(
                        item_cabecalho.get("valorOutrasRetencoes")
                    ),
                    "aliquota_desconto": _decimal(
                        item_cabecalho.get("aliqDesconto")
                    ),
                    "aliquota_iss": _decimal(item_impostos.get("aliqISS")),
                    "valor_iss": _decimal(item_impostos.get("valorISS")),
                    "ret_iss": _sim_nao(item_impostos.get("retISS")),
                    "deduz_iss": bool(item_impostos.get("lDeduzISS")),
                    "item_cabecalho": item_cabecalho,
                    "item_descricao_servico": item_descricao,
                    "item_impostos": item_impostos,
                    "item_lei_transparencia": detalhe.get("itemLeiTranspImp") or {},
                    "dados_originais": detalhe,
                },
            )
            itens_ativos.add(codigo_item)

        ContratoItemOmie.objects.filter(
            empresa=empresa,
            contrato=contrato,
        ).exclude(codigo_item__in=itens_ativos).delete()
        processados += 1
    return processados


def _salvar_categorias(empresa, itens):
    processados = 0
    for item in itens:
        codigo = str(item.get("codigo") or "").strip()
        if not codigo:
            continue
        CategoriaOmie.objects.update_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={
                "categoria_superior": str(item.get("categoria_superior") or ""),
                "descricao": str(item.get("descricao") or ""),
                "descricao_padrao": str(item.get("descricao_padrao") or ""),
                "codigo_dre": str(item.get("codigo_dre") or ""),
                "conta_despesa": _sim_nao(item.get("conta_despesa")),
                "conta_inativa": _sim_nao(item.get("conta_inativa")),
                "conta_receita": _sim_nao(item.get("conta_receita")),
                "definida_pelo_usuario": _sim_nao(
                    item.get("definida_pelo_usuario")
                ),
                "id_conta_contabil": str(item.get("id_conta_contabil") or ""),
                "nao_exibir": _sim_nao(item.get("nao_exibir")),
                "natureza": str(item.get("natureza") or ""),
                "tag_conta_contabil": str(item.get("tag_conta_contabil") or ""),
                "tipo_categoria": str(item.get("tipo_categoria") or ""),
                "totalizadora": _sim_nao(item.get("totalizadora")),
                "transferencia": _sim_nao(item.get("transferencia")),
                "dados_dre": item.get("dadosDRE") or {},
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_tipos_conta_corrente(empresa, itens):
    processados = 0
    for item in itens:
        codigo = str(item.get("cCodigo") or "").strip()
        if not codigo:
            continue
        TipoContaCorrenteOmie.objects.update_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={
                "descricao": str(item.get("cDescricao") or ""),
                "grupo": str(item.get("cGrupo") or ""),
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_contas_correntes(empresa, itens):
    processados = 0
    for item in itens:
        codigo = item.get("nCodCC")
        if codigo in (None, ""):
            continue
        tipo_codigo = str(
            item.get("tipo_conta_corrente") or item.get("tipo") or ""
        ).strip()
        tipo_conta = TipoContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo=tipo_codigo,
        ).first()
        ContaCorrenteOmie.objects.update_or_create(
            empresa=empresa,
            codigo_omie=int(codigo),
            defaults={
                "codigo_integracao": str(item.get("cCodCCInt") or ""),
                "tipo_conta": tipo_conta,
                "tipo_codigo": tipo_codigo,
                "codigo_banco": str(item.get("codigo_banco") or ""),
                "descricao": str(item.get("descricao") or ""),
                "codigo_agencia": str(item.get("codigo_agencia") or ""),
                "numero_conta_corrente": str(
                    item.get("numero_conta_corrente") or ""
                ),
                "saldo_inicial": _decimal(item.get("saldo_inicial")),
                "saldo_data": str(item.get("saldo_data") or ""),
                "valor_limite": _decimal(item.get("valor_limite")),
                "nao_fluxo": _sim_nao(item.get("nao_fluxo")),
                "nao_resumo": _sim_nao(item.get("nao_resumo")),
                "realiza_cobranca": _sim_nao(item.get("cobr_sn")),
                "emite_boleto": _sim_nao(item.get("bol_sn")),
                "emite_pix": _sim_nao(item.get("pix_sn")),
                "importado_api": _sim_nao(item.get("importado_api")),
                "bloqueado": _sim_nao(item.get("bloqueado")),
                "inativo": _sim_nao(item.get("inativo")),
                "observacao": str(item.get("observacao") or ""),
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _saldo_provisorio_extrato(dados):
    if "nSaldoProvisorio" in dados:
        return dados.get("nSaldoProvisorio")
    for chave in ("listaMovimentos", "movimentos", "extrato"):
        itens = dados.get(chave)
        if isinstance(itens, list):
            for item in reversed(itens):
                if isinstance(item, dict) and "nSaldoProvisorio" in item:
                    return item.get("nSaldoProvisorio")
    return None


def _atualizar_saldos_extrato_contas_correntes(empresa, integracao):
    contas = ContaCorrenteOmie.objects.filter(
        empresa=empresa,
        inativo=False,
    )
    processados = 0
    for conta in contas:
        dados = consultar_extrato_conta_corrente(integracao, conta)
        saldo = _saldo_provisorio_extrato(dados)
        if saldo is None:
            continue
        conta.saldo_atual = _decimal(saldo)
        conta.saldo_atualizado_em = timezone.now()
        conta.dados_originais = {
            **(conta.dados_originais or {}),
            "extrato": dados,
        }
        conta.save(
            update_fields=[
                "saldo_atual",
                "saldo_atualizado_em",
                "dados_originais",
                "sincronizado_em",
            ]
        )
        processados += 1
    return processados


def _saldo_contas_resumo_financeiro(dados):
    conta_corrente = dados.get("contaCorrente") or {}
    return conta_corrente.get("vTotal")


def _atualizar_resumo_financeiro_empresa(empresa, integracao):
    dados = consultar_resumo_financas(integracao)
    saldo = _saldo_contas_resumo_financeiro(dados)
    if saldo is None:
        return 0
    empresa.saldo_contas_omie = _decimal(saldo)
    empresa.saldo_contas_atualizado_em = timezone.now()
    empresa.resumo_financeiro_omie = dados
    empresa.save(
        update_fields=[
            "saldo_contas_omie",
            "saldo_contas_atualizado_em",
            "resumo_financeiro_omie",
            "atualizada_em",
        ]
    )
    return 1


def _salvar_contas_pagar(empresa, itens):
    agora = timezone.now()
    codigos_fornecedores = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("codigo_cliente_fornecedor"))]
        if codigo is not None
    }
    ids_contas_correntes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("id_conta_corrente"))]
        if codigo is not None
    }
    codigos_categorias = {
        str(item.get("codigo_categoria") or "").strip()
        for item in itens
        if str(item.get("codigo_categoria") or "").strip()
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("codigo_projeto"))]
        if codigo is not None
    }
    fornecedores = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_fornecedores,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=ids_contas_correntes,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }

    processados = 0
    for item in itens:
        codigo_lancamento = _inteiro_ou_none(
            item.get("codigo_lancamento_omie")
        )
        if codigo_lancamento is None:
            continue

        codigo_fornecedor = _inteiro_ou_none(
            item.get("codigo_cliente_fornecedor")
        )
        id_conta_corrente = _inteiro_ou_none(item.get("id_conta_corrente"))
        codigo_projeto = _inteiro_ou_none(item.get("codigo_projeto"))
        codigo_categoria = str(item.get("codigo_categoria") or "").strip()

        fornecedor = fornecedores.get(codigo_fornecedor)
        conta_corrente = contas_correntes.get(id_conta_corrente)
        categoria = categorias.get(codigo_categoria)
        projeto = projetos.get(codigo_projeto)

        valor_documento = _decimal(item.get("valor_documento"))
        valor_a_pagar = (
            _decimal(item.get("valor_pag"))
            if item.get("valor_pag") not in (None, "")
            else valor_documento
        )
        ContaPagarOmie.objects.update_or_create(
            empresa=empresa,
            codigo_lancamento_omie=codigo_lancamento,
            defaults={
                "codigo_lancamento_integracao": str(
                    item.get("codigo_lancamento_integracao") or ""
                ),
                "codigo_cliente_fornecedor": codigo_fornecedor,
                "fornecedor": fornecedor,
                "id_conta_corrente": id_conta_corrente,
                "conta_corrente": conta_corrente,
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categoria,
                "codigo_projeto": codigo_projeto,
                "projeto": projeto,
                "data_emissao": _data_omie(item.get("data_emissao")),
                "data_entrada": _data_omie(item.get("data_entrada")),
                "data_previsao": _data_omie(item.get("data_previsao")),
                "data_vencimento": _data_omie(item.get("data_vencimento")),
                "valor_documento": valor_documento,
                "valor_a_pagar": valor_a_pagar,
                "status_titulo": str(item.get("status_titulo") or ""),
                "numero_documento": str(item.get("numero_documento") or ""),
                "numero_documento_fiscal": str(
                    item.get("numero_documento_fiscal") or ""
                ),
                "numero_parcela": str(item.get("numero_parcela") or ""),
                "codigo_tipo_documento": str(
                    item.get("codigo_tipo_documento") or ""
                ),
                "id_origem": str(item.get("id_origem") or ""),
                "retem_cofins": _sim_nao(item.get("retem_cofins")),
                "retem_csll": _sim_nao(item.get("retem_csll")),
                "retem_inss": _sim_nao(item.get("retem_inss")),
                "retem_ir": _sim_nao(item.get("retem_ir")),
                "retem_iss": _sim_nao(item.get("retem_iss")),
                "retem_pis": _sim_nao(item.get("retem_pis")),
                "categorias": item.get("categorias") or [],
                "distribuicao": item.get("distribuicao") or [],
                "cnab_integracao_bancaria": (
                    item.get("cnab_integracao_bancaria") or {}
                ),
                "info": item.get("info") or {},
                "dados_originais": item,
                "ativo_omie": True,
                "ultima_presenca_omie": agora,
            },
        )
        processados += 1
    return processados


def _desativar_contas_pagar_ausentes_na_omie(empresa, inicio_sincronizacao):
    return ContaPagarOmie.objects.filter(
        empresa=empresa,
        ativo_omie=True,
    ).filter(
        Q(ultima_presenca_omie__isnull=True)
        | Q(ultima_presenca_omie__lt=inicio_sincronizacao)
    ).update(ativo_omie=False)


def _salvar_contas_receber(empresa, itens):
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("codigo_cliente_fornecedor"))]
        if codigo is not None
    }
    ids_contas_correntes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("id_conta_corrente"))]
        if codigo is not None
    }
    codigos_categorias = {
        str(item.get("codigo_categoria") or "").strip()
        for item in itens
        if str(item.get("codigo_categoria") or "").strip()
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none(item.get("codigo_projeto"))]
        if codigo is not None
    }
    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=ids_contas_correntes,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }

    processados = 0
    for item in itens:
        codigo_lancamento = _inteiro_ou_none(
            item.get("codigo_lancamento_omie")
        )
        if codigo_lancamento is None:
            continue

        codigo_cliente = _inteiro_ou_none(
            item.get("codigo_cliente_fornecedor")
        )
        id_conta_corrente = _inteiro_ou_none(item.get("id_conta_corrente"))
        codigo_projeto = _inteiro_ou_none(item.get("codigo_projeto"))
        codigo_categoria = str(item.get("codigo_categoria") or "").strip()
        valor_documento = _decimal(item.get("valor_documento"))

        ContaReceberOmie.objects.update_or_create(
            empresa=empresa,
            codigo_lancamento_omie=codigo_lancamento,
            defaults={
                "codigo_lancamento_integracao": str(
                    item.get("codigo_lancamento_integracao") or ""
                ),
                "codigo_cliente_fornecedor": codigo_cliente,
                "cliente": clientes.get(codigo_cliente),
                "id_conta_corrente": id_conta_corrente,
                "conta_corrente": contas_correntes.get(id_conta_corrente),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "data_emissao": _data_omie(item.get("data_emissao")),
                "data_previsao": _data_omie(item.get("data_previsao")),
                "data_registro": _data_omie(item.get("data_registro")),
                "data_vencimento": _data_omie(item.get("data_vencimento")),
                "valor_documento": valor_documento,
                "valor_a_receber": valor_documento,
                "status_titulo": str(item.get("status_titulo") or ""),
                "numero_documento": str(item.get("numero_documento") or ""),
                "numero_documento_fiscal": str(
                    item.get("numero_documento_fiscal") or ""
                ),
                "numero_parcela": str(item.get("numero_parcela") or ""),
                "numero_pedido": str(item.get("numero_pedido") or ""),
                "codigo_pedido_omie": _inteiro_ou_none(item.get("nCodPedido")),
                "codigo_tipo_documento": str(
                    item.get("codigo_tipo_documento") or ""
                ),
                "chave_nfe": str(item.get("chave_nfe") or ""),
                "id_origem": str(item.get("id_origem") or ""),
                "operacao": str(item.get("operacao") or ""),
                "tipo_agrupamento": str(item.get("tipo_agrupamento") or ""),
                "retem_cofins": _sim_nao(item.get("retem_cofins")),
                "retem_csll": _sim_nao(item.get("retem_csll")),
                "retem_inss": _sim_nao(item.get("retem_inss")),
                "retem_ir": _sim_nao(item.get("retem_ir")),
                "retem_iss": _sim_nao(item.get("retem_iss")),
                "retem_pis": _sim_nao(item.get("retem_pis")),
                "bloqueado": _sim_nao(item.get("bloqueado")),
                "bloquear_baixa": _sim_nao(item.get("bloquear_baixa")),
                "importado_api": _sim_nao(item.get("importado_api")),
                "boleto": item.get("boleto") or {},
                "categorias": item.get("categorias") or [],
                "distribuicao": item.get("distribuicao") or [],
                "info": item.get("info") or {},
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_lancamentos_conta_corrente(empresa, itens):
    codigos_contas = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("cabecalho") or {}).get("nCodCC")),
            _inteiro_ou_none(
                (item.get("transferencia") or {}).get("nCodCCDestino")
            ),
        ]
        if codigo is not None
    }
    codigos_categorias = {
        str((item.get("detalhes") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("detalhes") or {}).get("cCodCateg") or "").strip()
    }
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("detalhes") or {}).get("nCodCliente"))
        ]
        if codigo is not None
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("detalhes") or {}).get("nCodProjeto"))
        ]
        if codigo not in (None, 0)
    }
    codigos_contas_pagar = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("diversos") or {}).get("nCodLancCP"))
        ]
        if codigo not in (None, 0)
    }
    codigos_contas_receber = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("diversos") or {}).get("nCodLancCR"))
        ]
        if codigo not in (None, 0)
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=codigos_contas,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }
    contas_pagar = {
        conta.codigo_lancamento_omie: conta
        for conta in ContaPagarOmie.objects.filter(
            empresa=empresa,
            codigo_lancamento_omie__in=codigos_contas_pagar,
        )
    }
    contas_receber = {
        conta.codigo_lancamento_omie: conta
        for conta in ContaReceberOmie.objects.filter(
            empresa=empresa,
            codigo_lancamento_omie__in=codigos_contas_receber,
        )
    }

    processados = 0
    for item in itens:
        codigo_lancamento = _inteiro_ou_none(item.get("nCodLanc"))
        if codigo_lancamento is None:
            continue

        cabecalho = item.get("cabecalho") or {}
        detalhes = item.get("detalhes") or {}
        diversos = item.get("diversos") or {}
        transferencia = item.get("transferencia") or {}
        info = item.get("info") or {}
        codigo_conta = _inteiro_ou_none(cabecalho.get("nCodCC"))
        codigo_categoria = str(detalhes.get("cCodCateg") or "").strip()
        codigo_cliente = _inteiro_ou_none(detalhes.get("nCodCliente"))
        codigo_projeto = _inteiro_ou_none(detalhes.get("nCodProjeto"))
        codigo_conta_pagar = _inteiro_ou_none(diversos.get("nCodLancCP"))
        codigo_conta_receber = _inteiro_ou_none(diversos.get("nCodLancCR"))
        codigo_conta_destino = _inteiro_ou_none(
            transferencia.get("nCodCCDestino")
        )

        LancamentoContaCorrenteOmie.objects.update_or_create(
            empresa=empresa,
            codigo_lancamento_omie=codigo_lancamento,
            defaults={
                "codigo_lancamento_integracao": str(
                    item.get("cCodIntLanc") or ""
                ),
                "codigo_agrupamento": _inteiro_ou_none(item.get("nCodAgrup")),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "data_lancamento": _data_omie(cabecalho.get("dDtLanc")),
                "valor_lancamento": _decimal(cabecalho.get("nValorLanc")),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "tipo_documento": str(detalhes.get("cTipo") or ""),
                "numero_documento": str(detalhes.get("cNumDoc") or ""),
                "codigo_cliente_fornecedor": codigo_cliente,
                "cliente_fornecedor": clientes.get(codigo_cliente),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "observacao": str(detalhes.get("cObs") or ""),
                "natureza": str(diversos.get("cNatureza") or ""),
                "origem": str(diversos.get("cOrigem") or ""),
                "data_conciliacao": _data_omie(diversos.get("dDtConc")),
                "hora_conciliacao": str(diversos.get("cHrConc") or ""),
                "usuario_conciliacao": str(diversos.get("cUsConc") or ""),
                "identificacao_lancamento": str(
                    diversos.get("cIdentLanc") or ""
                ),
                "codigo_lancamento_conta_pagar": codigo_conta_pagar,
                "conta_pagar": contas_pagar.get(codigo_conta_pagar),
                "codigo_lancamento_conta_receber": codigo_conta_receber,
                "conta_receber": contas_receber.get(codigo_conta_receber),
                "codigo_conta_corrente_destino": codigo_conta_destino,
                "conta_corrente_destino": contas_correntes.get(
                    codigo_conta_destino
                ),
                "importado_api": _sim_nao(info.get("cImpAPI")),
                "categorias": detalhes.get("aCodCateg") or [],
                "departamentos": item.get("departamentos") or [],
                "cabecalho": cabecalho,
                "detalhes": detalhes,
                "diversos": diversos,
                "transferencia": transferencia,
                "info": info,
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_movimentos_financeiros(empresa, itens):
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("detalhes") or {}).get("nCodCliente"))]
        if codigo is not None
    }
    ids_contas_correntes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("detalhes") or {}).get("nCodCC"))]
        if codigo is not None
    }
    codigos_categorias = {
        str((item.get("detalhes") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("detalhes") or {}).get("cCodCateg") or "").strip()
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("detalhes") or {}).get("nCodProjeto"))]
        if codigo is not None
    }
    codigos_titulos = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("detalhes") or {}).get("nCodTitulo"))]
        if codigo is not None
    }

    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=ids_contas_correntes,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }
    contas_pagar = {
        conta.codigo_lancamento_omie: conta
        for conta in ContaPagarOmie.objects.filter(
            empresa=empresa,
            codigo_lancamento_omie__in=codigos_titulos,
        )
    }
    contas_receber = {
        conta.codigo_lancamento_omie: conta
        for conta in ContaReceberOmie.objects.filter(
            empresa=empresa,
            codigo_lancamento_omie__in=codigos_titulos,
        )
    }

    processados = 0
    for item in itens:
        detalhes = item.get("detalhes") or {}
        resumo = item.get("resumo") or {}
        codigo_titulo = _inteiro_ou_none(detalhes.get("nCodTitulo"))
        if codigo_titulo is None:
            continue

        codigo_cliente = _inteiro_ou_none(detalhes.get("nCodCliente"))
        codigo_conta = _inteiro_ou_none(detalhes.get("nCodCC"))
        codigo_projeto = _inteiro_ou_none(detalhes.get("nCodProjeto"))
        codigo_categoria = str(detalhes.get("cCodCateg") or "").strip()

        MovimentoFinanceiroOmie.objects.update_or_create(
            empresa=empresa,
            codigo_titulo=codigo_titulo,
            defaults={
                "codigo_titulo_repeticao": _inteiro_ou_none(
                    detalhes.get("nCodTitRepet")
                ),
                "codigo_cliente_fornecedor": codigo_cliente,
                "cliente_fornecedor": clientes.get(codigo_cliente),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "conta_pagar": contas_pagar.get(codigo_titulo),
                "conta_receber": contas_receber.get(codigo_titulo),
                "grupo": str(detalhes.get("cGrupo") or ""),
                "natureza": str(detalhes.get("cNatureza") or ""),
                "origem": str(detalhes.get("cOrigem") or ""),
                "status": str(detalhes.get("cStatus") or ""),
                "liquidado": _sim_nao(resumo.get("cLiquidado")),
                "tipo_documento": str(detalhes.get("cTipo") or ""),
                "numero_titulo": str(detalhes.get("cNumTitulo") or ""),
                "numero_boleto": str(detalhes.get("cNumBoleto") or ""),
                "numero_parcela": str(detalhes.get("cNumParcela") or ""),
                "cpf_cnpj_cliente": str(detalhes.get("cCPFCNPJCliente") or ""),
                "data_emissao": _data_omie(detalhes.get("dDtEmissao")),
                "data_pagamento": _data_omie(detalhes.get("dDtPagamento")),
                "data_previsao": _data_omie(detalhes.get("dDtPrevisao")),
                "data_registro": _data_omie(detalhes.get("dDtRegistro")),
                "data_vencimento": _data_omie(detalhes.get("dDtVenc")),
                "valor_titulo": _decimal(detalhes.get("nValorTitulo")),
                "valor_aberto": _decimal(resumo.get("nValAberto")),
                "valor_liquido": _decimal(resumo.get("nValLiquido")),
                "valor_pago": _decimal(resumo.get("nValPago")),
                "desconto": _decimal(resumo.get("nDesconto")),
                "juros": _decimal(resumo.get("nJuros")),
                "multa": _decimal(resumo.get("nMulta")),
                "detalhes": detalhes,
                "resumo": resumo,
                "dados_originais": item,
            },
        )
        processados += 1
    return processados


def _salvar_pedidos(empresa, itens):
    codigos_clientes = {
        codigo
        for item in itens
        for codigo in [_inteiro_ou_none((item.get("cabecalho") or {}).get("codigo_cliente"))]
        if codigo is not None
    }
    codigos_contas = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none(
                (item.get("informacoes_adicionais") or {}).get(
                    "codigo_conta_corrente"
                )
            )
        ]
        if codigo is not None
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("informacoes_adicionais") or {}).get("codProj"))
        ]
        if codigo not in (None, 0)
    }
    codigos_categorias = {
        str((item.get("informacoes_adicionais") or {}).get("codigo_categoria") or "").strip()
        for item in itens
        if str((item.get("informacoes_adicionais") or {}).get("codigo_categoria") or "").strip()
    }
    codigos_produtos = {
        codigo
        for item in itens
        for detalhe in item.get("det") or []
        for codigo in [_inteiro_ou_none((detalhe.get("produto") or {}).get("codigo_produto"))]
        if codigo is not None
    }
    codigos_categorias.update(
        str((detalhe.get("inf_adic") or {}).get("codigo_categoria_item") or "").strip()
        for item in itens
        for detalhe in item.get("det") or []
        if str((detalhe.get("inf_adic") or {}).get("codigo_categoria_item") or "").strip()
    )

    clientes = {
        cadastro.codigo_cliente_omie: cadastro
        for cadastro in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_clientes,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=codigos_contas,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    produtos = {
        produto.codigo_produto: produto
        for produto in ProdutoOmie.objects.filter(
            empresa=empresa,
            codigo_produto__in=codigos_produtos,
        )
    }

    processados = 0
    for item in itens:
        cabecalho = item.get("cabecalho") or {}
        codigo_pedido = _inteiro_ou_none(cabecalho.get("codigo_pedido"))
        if codigo_pedido is None:
            continue

        info = item.get("infoCadastro") or {}
        informacoes = item.get("informacoes_adicionais") or {}
        total = item.get("total_pedido") or {}
        frete = item.get("frete") or {}
        codigo_cliente = _inteiro_ou_none(cabecalho.get("codigo_cliente"))
        codigo_conta = _inteiro_ou_none(informacoes.get("codigo_conta_corrente"))
        codigo_projeto = _inteiro_ou_none(informacoes.get("codProj"))
        if codigo_projeto == 0:
            codigo_projeto = None
        codigo_categoria = str(informacoes.get("codigo_categoria") or "").strip()

        pedido, _criado = PedidoOmie.objects.update_or_create(
            empresa=empresa,
            codigo_pedido=codigo_pedido,
            defaults={
                "codigo_pedido_integracao": str(
                    cabecalho.get("codigo_pedido_integracao") or ""
                ),
                "numero_pedido": str(cabecalho.get("numero_pedido") or ""),
                "codigo_cliente": codigo_cliente,
                "cliente": clientes.get(codigo_cliente),
                "codigo_empresa_omie": _inteiro_ou_none(
                    cabecalho.get("codigo_empresa")
                ),
                "codigo_parcela": str(cabecalho.get("codigo_parcela") or ""),
                "codigo_cenario_impostos": str(
                    cabecalho.get("codigo_cenario_impostos") or ""
                ),
                "etapa": str(cabecalho.get("etapa") or ""),
                "origem_pedido": str(cabecalho.get("origem_pedido") or ""),
                "data_previsao": _data_omie(cabecalho.get("data_previsao")),
                "encerrado": _sim_nao(cabecalho.get("encerrado")),
                "bloqueado": _sim_nao(cabecalho.get("bloqueado")),
                "importado_api": _sim_nao(
                    cabecalho.get("importado_api") or info.get("cImpAPI")
                ),
                "quantidade_itens": int(cabecalho.get("quantidade_itens") or 0),
                "quantidade_parcelas": int(cabecalho.get("qtde_parcelas") or 0),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "codigo_vendedor": _inteiro_ou_none(informacoes.get("codVend")),
                "consumidor_final": _sim_nao(informacoes.get("consumidor_final")),
                "autorizado": _sim_nao(info.get("autorizado")),
                "cancelado": _sim_nao(info.get("cancelado")),
                "denegado": _sim_nao(info.get("denegado")),
                "devolvido": _sim_nao(info.get("devolvido")),
                "devolvido_parcial": _sim_nao(info.get("devolvido_parcial")),
                "faturado": _sim_nao(info.get("faturado")),
                "data_inclusao": _data_omie(info.get("dInc")),
                "data_alteracao": _data_omie(info.get("dAlt")),
                "data_faturamento": _data_omie(info.get("dFat")),
                "valor_mercadorias": _decimal(total.get("valor_mercadorias")),
                "valor_total_pedido": _decimal(total.get("valor_total_pedido")),
                "valor_descontos": _decimal(total.get("valor_descontos")),
                "valor_frete": _decimal(frete.get("valor_frete")),
                "valor_seguro": _decimal(frete.get("valor_seguro")),
                "cabecalho": cabecalho,
                "departamentos": item.get("departamentos") or [],
                "exportacao": item.get("exportacao") or {},
                "frete": frete,
                "info_cadastro": info,
                "informacoes_adicionais": informacoes,
                "lista_parcelas": item.get("lista_parcelas") or {},
                "observacoes": item.get("observacoes") or {},
                "total_pedido": total,
                "dados_originais": item,
            },
        )

        itens_ativos = set()
        for detalhe in item.get("det") or []:
            ide = detalhe.get("ide") or {}
            produto_dados = detalhe.get("produto") or {}
            inf_adic = detalhe.get("inf_adic") or {}
            codigo_item = _inteiro_ou_none(ide.get("codigo_item"))
            if codigo_item is None:
                continue

            codigo_produto = _inteiro_ou_none(produto_dados.get("codigo_produto"))
            codigo_categoria_item = str(
                inf_adic.get("codigo_categoria_item") or ""
            ).strip()
            PedidoItemOmie.objects.update_or_create(
                empresa=empresa,
                codigo_item=codigo_item,
                defaults={
                    "pedido": pedido,
                    "codigo_item_integracao": str(
                        ide.get("codigo_item_integracao") or ""
                    ),
                    "codigo_produto": codigo_produto,
                    "produto": produtos.get(codigo_produto),
                    "codigo_produto_texto": str(produto_dados.get("codigo") or ""),
                    "descricao": str(produto_dados.get("descricao") or ""),
                    "unidade": str(produto_dados.get("unidade") or ""),
                    "ncm": str(produto_dados.get("ncm") or ""),
                    "cfop": str(produto_dados.get("cfop") or ""),
                    "codigo_categoria": codigo_categoria_item,
                    "categoria_principal": categorias.get(codigo_categoria_item),
                    "codigo_local_estoque": _inteiro_ou_none(
                        inf_adic.get("codigo_local_estoque")
                    ),
                    "quantidade": _decimal(produto_dados.get("quantidade")),
                    "valor_unitario": _decimal(produto_dados.get("valor_unitario")),
                    "valor_total": _decimal(produto_dados.get("valor_total")),
                    "valor_mercadoria": _decimal(
                        produto_dados.get("valor_mercadoria")
                    ),
                    "valor_desconto": _decimal(produto_dados.get("valor_desconto")),
                    "percentual_desconto": _decimal(
                        produto_dados.get("percentual_desconto")
                    ),
                    "nao_gerar_financeiro": _sim_nao(
                        inf_adic.get("nao_gerar_financeiro")
                    ),
                    "nao_movimentar_estoque": _sim_nao(
                        inf_adic.get("nao_movimentar_estoque")
                    ),
                    "nao_somar_total": _sim_nao(inf_adic.get("nao_somar_total")),
                    "reservado": _sim_nao(produto_dados.get("reservado")),
                    "ide": ide,
                    "produto_dados": produto_dados,
                    "imposto": detalhe.get("imposto") or {},
                    "inf_adic": inf_adic,
                    "dados_originais": detalhe,
                },
            )
            itens_ativos.add(codigo_item)

        PedidoItemOmie.objects.filter(empresa=empresa, pedido=pedido).exclude(
            codigo_item__in=itens_ativos
        ).delete()
        processados += 1
    return processados


def _salvar_pedidos_compra(empresa, itens):
    codigos_fornecedores = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("cabecalho_consulta") or {}).get("nCodFor"))
        ]
        if codigo is not None
    }
    codigos_contas = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("cabecalho_consulta") or {}).get("nCodCC"))
        ]
        if codigo is not None
    }
    codigos_projetos = {
        codigo
        for item in itens
        for codigo in [
            _inteiro_ou_none((item.get("cabecalho_consulta") or {}).get("nCodProj"))
        ]
        if codigo not in (None, 0)
    }
    codigos_categorias = {
        str((item.get("cabecalho_consulta") or {}).get("cCodCateg") or "").strip()
        for item in itens
        if str((item.get("cabecalho_consulta") or {}).get("cCodCateg") or "").strip()
    }
    codigos_produtos = {
        codigo
        for item in itens
        for produto in item.get("produtos_consulta") or []
        for codigo in [_inteiro_ou_none(produto.get("nCodProd"))]
        if codigo is not None
    }

    fornecedores = {
        fornecedor.codigo_cliente_omie: fornecedor
        for fornecedor in CadastroOmie.objects.filter(
            empresa=empresa,
            codigo_cliente_omie__in=codigos_fornecedores,
        )
    }
    contas_correntes = {
        conta.codigo_omie: conta
        for conta in ContaCorrenteOmie.objects.filter(
            empresa=empresa,
            codigo_omie__in=codigos_contas,
        )
    }
    projetos = {
        projeto.codigo: projeto
        for projeto in ProjetoOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_projetos,
        )
    }
    categorias = {
        categoria.codigo: categoria
        for categoria in CategoriaOmie.objects.filter(
            empresa=empresa,
            codigo__in=codigos_categorias,
        )
    }
    produtos = {
        produto.codigo_produto: produto
        for produto in ProdutoOmie.objects.filter(
            empresa=empresa,
            codigo_produto__in=codigos_produtos,
        )
    }

    processados = 0
    for item in itens:
        cabecalho = item.get("cabecalho_consulta") or {}
        frete = item.get("frete_consulta") or {}
        codigo_pedido = _inteiro_ou_none(cabecalho.get("nCodPed"))
        if codigo_pedido is None:
            continue

        codigo_fornecedor = _inteiro_ou_none(cabecalho.get("nCodFor"))
        codigo_conta = _inteiro_ou_none(cabecalho.get("nCodCC"))
        codigo_projeto = _inteiro_ou_none(cabecalho.get("nCodProj"))
        if codigo_projeto == 0:
            codigo_projeto = None
        codigo_categoria = str(cabecalho.get("cCodCateg") or "").strip()
        produtos_consulta = item.get("produtos_consulta") or []
        valor_mercadorias = sum(
            (_decimal(produto.get("nValMerc")) for produto in produtos_consulta),
            Decimal("0"),
        )
        valor_total_pedido = sum(
            (_decimal(produto.get("nValTot")) for produto in produtos_consulta),
            Decimal("0"),
        )

        pedido, _criado = PedidoCompraOmie.objects.update_or_create(
            empresa=empresa,
            codigo_pedido=codigo_pedido,
            defaults={
                "codigo_pedido_integracao": str(cabecalho.get("cCodIntPed") or ""),
                "numero_pedido": str(cabecalho.get("cNumero") or ""),
                "numero_pedido_fornecedor": str(cabecalho.get("cNumPedido") or ""),
                "etapa": str(cabecalho.get("cEtapa") or ""),
                "contato": str(cabecalho.get("cContato") or ""),
                "observacao": str(cabecalho.get("cObs") or ""),
                "observacao_interna": str(cabecalho.get("cObsInt") or ""),
                "codigo_fornecedor": codigo_fornecedor,
                "fornecedor": fornecedores.get(codigo_fornecedor),
                "codigo_comprador": _inteiro_ou_none(cabecalho.get("nCodCompr")),
                "codigo_categoria": codigo_categoria,
                "categoria_principal": categorias.get(codigo_categoria),
                "codigo_conta_corrente": codigo_conta,
                "conta_corrente": contas_correntes.get(codigo_conta),
                "codigo_projeto": codigo_projeto,
                "projeto": projetos.get(codigo_projeto),
                "codigo_parcela": str(cabecalho.get("cCodParc") or ""),
                "quantidade_parcelas": int(cabecalho.get("nQtdeParc") or 0),
                "data_previsao": _data_omie(cabecalho.get("dDtPrevisao")),
                "data_inclusao": _data_omie(cabecalho.get("dIncData")),
                "hora_inclusao": str(cabecalho.get("cIncHora") or ""),
                "valor_mercadorias": valor_mercadorias,
                "valor_total_pedido": valor_total_pedido,
                "valor_frete": _decimal(frete.get("nValFrete")),
                "valor_seguro": _decimal(frete.get("nValSeguro")),
                "valor_outras_despesas": _decimal(frete.get("nValOutras")),
                "cabecalho_consulta": cabecalho,
                "caracteristicas_consulta": (
                    item.get("caracteristicas_consulta") or []
                ),
                "departamentos_consulta": item.get("departamentos_consulta") or [],
                "frete_consulta": frete,
                "parcelas_consulta": item.get("parcelas_consulta") or [],
                "dados_originais": item,
            },
        )

        itens_ativos = set()
        for detalhe in produtos_consulta:
            codigo_item = _inteiro_ou_none(detalhe.get("nCodItem"))
            if codigo_item is None:
                continue

            codigo_produto = _inteiro_ou_none(detalhe.get("nCodProd"))
            codigo_categoria_item = str(detalhe.get("cCodCateg") or "").strip()
            PedidoCompraItemOmie.objects.update_or_create(
                empresa=empresa,
                codigo_item=codigo_item,
                defaults={
                    "pedido": pedido,
                    "codigo_item_integracao": str(detalhe.get("cCodIntItem") or ""),
                    "codigo_produto": codigo_produto,
                    "produto": produtos.get(codigo_produto),
                    "codigo_produto_texto": str(detalhe.get("cProduto") or ""),
                    "descricao": str(detalhe.get("cDescricao") or ""),
                    "unidade": str(detalhe.get("cUnidade") or ""),
                    "ncm": str(detalhe.get("cNCM") or ""),
                    "ean": str(detalhe.get("cEAN") or ""),
                    "codigo_categoria": codigo_categoria_item,
                    "categoria_principal": categorias.get(codigo_categoria_item),
                    "codigo_local_estoque": _inteiro_ou_none(
                        detalhe.get("codigo_local_estoque")
                    ),
                    "quantidade": _decimal(detalhe.get("nQtde")),
                    "quantidade_recebida": _decimal(detalhe.get("nQtdeRec")),
                    "valor_unitario": _decimal(detalhe.get("nValUnit")),
                    "valor_total": _decimal(detalhe.get("nValTot")),
                    "valor_mercadoria": _decimal(detalhe.get("nValMerc")),
                    "valor_desconto": _decimal(detalhe.get("nDesconto")),
                    "valor_frete": _decimal(detalhe.get("nFrete")),
                    "valor_despesas": _decimal(detalhe.get("nDespesas")),
                    "valor_seguro": _decimal(detalhe.get("nSeguro")),
                    "valor_icms": _decimal(detalhe.get("nValorIcms")),
                    "valor_ipi": _decimal(detalhe.get("nValorIpi")),
                    "valor_pis": _decimal(detalhe.get("nValorPis")),
                    "valor_cofins": _decimal(detalhe.get("nValorCofins")),
                    "valor_st": _decimal(detalhe.get("nValorSt")),
                    "peso_bruto": _decimal(detalhe.get("nPesoBruto")),
                    "peso_liquido": _decimal(detalhe.get("nPesoLiq")),
                    "observacao": str(detalhe.get("cObs") or ""),
                    "dados_originais": detalhe,
                },
            )
            itens_ativos.add(codigo_item)

        PedidoCompraItemOmie.objects.filter(
            empresa=empresa,
            pedido=pedido,
        ).exclude(codigo_item__in=itens_ativos).delete()
        processados += 1
    return processados


def executar_sincronizacao_omie(sincronizacao_id):
    _fechar_conexoes_antigas_fora_de_transacao()
    sincronizacao = SincronizacaoOmie.objects.select_related(
        "empresa__integracao_omie"
    ).get(pk=sincronizacao_id)
    sincronizacao.status = SincronizacaoOmie.Status.EM_ANDAMENTO
    sincronizacao.iniciada_em = timezone.now()
    sincronizacao.mensagem = "Conectando à OMIE..."
    sincronizacao.save(
        update_fields=["status", "iniciada_em", "mensagem", "atualizada_em"]
    )

    try:
        integracao = sincronizacao.empresa.integracao_omie
        recursos = [
            {
                "nome": "Clientes e fornecedores",
                "consultar": consultar_clientes,
                "chave": "clientes_cadastro",
                "salvar": _salvar_clientes,
            },
            {
                "nome": "Projetos",
                "consultar": consultar_projetos,
                "chave": "cadastro",
                "salvar": _salvar_projetos,
            },
            {
                "nome": "Departamentos",
                "consultar": consultar_departamentos,
                "chave": "departamentos",
                "salvar": _salvar_departamentos,
            },
            {
                "nome": "Vendedores",
                "consultar": consultar_vendedores,
                "chave": "cadastro",
                "salvar": _salvar_vendedores,
            },
            {
                "nome": "Produtos",
                "consultar": consultar_produtos,
                "chave": "produto_servico_cadastro",
                "salvar": _salvar_produtos,
            },
            {
                "nome": "Posicoes de estoque",
                "consultar": consultar_posicoes_estoque,
                "chave": "produtos",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_posicoes_estoque,
            },
            {
                "nome": "Pedidos de compra",
                "consultar": consultar_pedidos_compra,
                "chave": "pedidos_pesquisa",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_pedidos_compra,
            },
            {
                "nome": "Categorias",
                "consultar": consultar_categorias,
                "chave": "categoria_cadastro",
                "salvar": _salvar_categorias,
            },
            {
                "nome": "Servicos",
                "consultar": consultar_servicos,
                "chave": "cadastros",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_servicos,
            },
            {
                "nome": "Tipos de conta corrente",
                "consultar": consultar_tipos_conta_corrente,
                "chave": "cadastros",
                "salvar": _salvar_tipos_conta_corrente,
            },
            {
                "nome": "Contas correntes",
                "consultar": consultar_contas_correntes,
                "chave": "ListarContasCorrentes",
                "salvar": _salvar_contas_correntes,
            },
            {
                "nome": "Contratos",
                "consultar": consultar_contratos,
                "chave": "contratoCadastro",
                "salvar": _salvar_contratos,
            },
            {
                "nome": "Ordens de servico",
                "consultar": consultar_ordens_servico,
                "chave": "osCadastro",
                "salvar": _salvar_ordens_servico,
            },
            {
                "nome": "Contas a pagar",
                "consultar": consultar_contas_pagar,
                "chave": "conta_pagar_cadastro",
                "salvar": _salvar_contas_pagar,
            },
            {
                "nome": "Contas a receber",
                "consultar": consultar_contas_receber,
                "chave": "conta_receber_cadastro",
                "salvar": _salvar_contas_receber,
            },
            {
                "nome": "Movimentos financeiros",
                "consultar": consultar_movimentos_financeiros,
                "chave": "movimentos",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_movimentos_financeiros,
            },
            {
                "nome": "Lançamentos de conta corrente",
                "consultar": consultar_lancamentos_conta_corrente,
                "chave": "listaLancamentos",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_lancamentos_conta_corrente,
            },
            {
                "nome": "Pedidos",
                "consultar": consultar_pedidos,
                "chave": "pedido_venda_produto",
                "salvar": _salvar_pedidos,
            },
        ]

        for recurso in recursos:
            contexto_atual = f"Consultando {recurso['nome']}"
            sincronizacao.mensagem = f"{contexto_atual}..."
            sincronizacao.save(update_fields=["mensagem", "atualizada_em"])
            recurso["primeira_resposta"] = recurso["consultar"](integracao, 1)
            chave_total_paginas = recurso.get(
                "chave_total_paginas",
                "total_de_paginas",
            )
            chave_total_registros = recurso.get(
                "chave_total_registros",
                "total_de_registros",
            )
            recurso["total_paginas"] = int(
                recurso["primeira_resposta"].get(chave_total_paginas) or 1
            )
            recurso["total_registros"] = int(
                recurso["primeira_resposta"].get(chave_total_registros) or 0
            )

        sincronizacao.total_paginas = sum(
            recurso["total_paginas"] for recurso in recursos
        )
        sincronizacao.total_registros = sum(
            recurso["total_registros"] for recurso in recursos
        )
        sincronizacao.mensagem = "Dados recebidos. Atualizando a base local..."
        sincronizacao.save(
            update_fields=[
                "total_paginas",
                "total_registros",
                "mensagem",
                "atualizada_em",
            ]
        )

        pagina_global = 0
        for recurso in recursos:
            inicio_recurso = timezone.now()
            for pagina in range(1, recurso["total_paginas"] + 1):
                contexto_atual = f"{recurso['nome']}: pagina {pagina}"
                resposta = (
                    recurso["primeira_resposta"]
                    if pagina == 1
                    else recurso["consultar"](integracao, pagina)
                )
                itens = resposta.get(recurso["chave"]) or []

                with transaction.atomic():
                    processados = recurso["salvar"](sincronizacao.empresa, itens)
                    pagina_global += 1
                    sincronizacao.pagina_atual = pagina_global
                    sincronizacao.registros_processados += processados
                    sincronizacao.mensagem = (
                        f"{recurso['nome']}: página {pagina} de "
                        f"{recurso['total_paginas']} processada."
                    )
                    sincronizacao.save(
                        update_fields=[
                            "pagina_atual",
                            "registros_processados",
                            "mensagem",
                            "atualizada_em",
                        ]
                    )
            if recurso["salvar"] == _salvar_contas_pagar:
                desativados = _desativar_contas_pagar_ausentes_na_omie(
                    sincronizacao.empresa,
                    inicio_recurso,
                )
                sincronizacao.mensagem = (
                    f"{recurso['nome']}: {desativados} lancamento(s) obsoleto(s)."
                )
                sincronizacao.save(update_fields=["mensagem", "atualizada_em"])

        processados = _atualizar_resumo_financeiro_empresa(
            sincronizacao.empresa,
            integracao,
        )
        sincronizacao.registros_processados += processados
        sincronizacao.mensagem = "Resumo financeiro atualizado."
        sincronizacao.save(
            update_fields=[
                "registros_processados",
                "mensagem",
                "atualizada_em",
            ]
        )

        processados = _atualizar_saldos_extrato_contas_correntes(
            sincronizacao.empresa,
            integracao,
        )
        sincronizacao.registros_processados += processados
        sincronizacao.mensagem = "Saldos provisorios das contas correntes atualizados."
        sincronizacao.save(
            update_fields=[
                "registros_processados",
                "mensagem",
                "atualizada_em",
            ]
        )

        sincronizacao.status = SincronizacaoOmie.Status.CONCLUIDA
        sincronizacao.finalizada_em = timezone.now()
        sincronizacao.mensagem = (
            f"{sincronizacao.registros_processados} registros atualizados."
        )
        sincronizacao.save(
            update_fields=["status", "finalizada_em", "mensagem", "atualizada_em"]
        )
    except Exception as exc:
        sincronizacao.status = SincronizacaoOmie.Status.ERRO
        sincronizacao.finalizada_em = timezone.now()
        contexto = locals().get("contexto_atual") or sincronizacao.mensagem
        sincronizacao.erro = f"{contexto}: {exc}"[:2000]
        sincronizacao.mensagem = "A sincronização não foi concluída."
        sincronizacao.save(
            update_fields=[
                "status",
                "finalizada_em",
                "erro",
                "mensagem",
                "atualizada_em",
            ]
        )
    finally:
        _fechar_conexoes_antigas_fora_de_transacao()


def iniciar_sincronizacao_omie(sincronizacao_id):
    return _executor.submit(executar_sincronizacao_omie, sincronizacao_id)
