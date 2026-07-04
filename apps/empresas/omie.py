import json
import ssl
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import truststore
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import (
    CadastroOmie,
    CategoriaOmie,
    DepartamentoOmie,
    ProjetoOmie,
    SincronizacaoOmie,
)


CLIENTES_URL = "https://app.omie.com.br/api/v1/geral/clientes/"
PROJETOS_URL = "https://app.omie.com.br/api/v1/geral/projetos/"
DEPARTAMENTOS_URL = "https://app.omie.com.br/api/v1/geral/departamentos/"
CATEGORIAS_URL = "https://app.omie.com.br/api/v1/geral/categorias/"
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="omie-sync")


class OmieAPIError(Exception):
    pass


def _sim_nao(valor):
    return str(valor).upper() == "S"


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
        ]

        for recurso in recursos:
            recurso["primeira_resposta"] = recurso["consultar"](integracao, 1)
            recurso["total_paginas"] = int(
                recurso["primeira_resposta"].get("total_de_paginas") or 1
            )
            recurso["total_registros"] = int(
                recurso["primeira_resposta"].get("total_de_registros") or 0
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
