import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import (
    CadastroOmie,
    CategoriaOmie,
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    DepartamentoOmie,
    LancamentoContaCorrenteOmie,
    ProjetoOmie,
    SincronizacaoOmie,
    TipoContaCorrenteOmie,
)


CLIENTES_URL = "https://app.omie.com.br/api/v1/geral/clientes/"
PROJETOS_URL = "https://app.omie.com.br/api/v1/geral/projetos/"
DEPARTAMENTOS_URL = "https://app.omie.com.br/api/v1/geral/departamentos/"
CATEGORIAS_URL = "https://app.omie.com.br/api/v1/geral/categorias/"
TIPOS_CONTA_CORRENTE_URL = "https://app.omie.com.br/api/v1/geral/tipocc/"
CONTAS_CORRENTES_URL = "https://app.omie.com.br/api/v1/geral/contacorrente/"
CONTAS_PAGAR_URL = "https://app.omie.com.br/api/v1/financas/contapagar/"
CONTAS_RECEBER_URL = "https://app.omie.com.br/api/v1/financas/contareceber/"
LANCAMENTOS_CONTA_CORRENTE_URL = (
    "https://app.omie.com.br/api/v1/financas/contacorrentelancamentos/"
)
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="omie-sync")


class OmieAPIError(Exception):
    pass


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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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
        with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
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


def _salvar_contas_pagar(empresa, itens):
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
            },
        )
        processados += 1
    return processados


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


def executar_sincronizacao_omie(sincronizacao_id):
    close_old_connections()
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
                "nome": "Categorias",
                "consultar": consultar_categorias,
                "chave": "categoria_cadastro",
                "salvar": _salvar_categorias,
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
                "nome": "Lançamentos de conta corrente",
                "consultar": consultar_lancamentos_conta_corrente,
                "chave": "listaLancamentos",
                "chave_total_paginas": "nTotPaginas",
                "chave_total_registros": "nTotRegistros",
                "salvar": _salvar_lancamentos_conta_corrente,
            },
        ]

        for recurso in recursos:
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
            for pagina in range(1, recurso["total_paginas"] + 1):
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
        sincronizacao.erro = str(exc)[:2000]
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
        close_old_connections()


def iniciar_sincronizacao_omie(sincronizacao_id):
    return _executor.submit(executar_sincronizacao_omie, sincronizacao_id)
