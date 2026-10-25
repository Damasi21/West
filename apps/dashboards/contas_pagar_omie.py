"""Financial writes use a single HTTP attempt, unlike retryable listing calls."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from apps.empresas.omie import CONTAS_PAGAR_URL, SSL_CONTEXT


class ResultadoOmieIncerto(Exception):
    pass


ANEXOS_URL = "https://app.omie.com.br/api/v1/geral/anexo/"


def chamada_conta_pagar(integracao, metodo, parametros, *, url=CONTAS_PAGAR_URL):
    segredo = integracao.obter_app_secret()
    payload = {"call": metodo, "param": [parametros], "app_key": integracao.app_key, "app_secret": segredo}
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=getattr(settings, "OMIE_API_TIMEOUT", 45), context=SSL_CONTEXT) as response:
            dados = json.loads(response.read().decode("utf-8"))
        if not isinstance(dados, dict) or "faultstring" in dados:
            raise ResultadoOmieIncerto("A OMIE nao confirmou a operacao. Verifique o resultado antes de qualquer novo envio.")
        return dados
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        # Never expose credentials/raw response bodies or repeat an ambiguous write.
        raise ResultadoOmieIncerto("Comunicacao sem confirmacao da OMIE. Use Verificar na OMIE; o envio nao sera repetido automaticamente.") from exc


def incluir_conta_pagar(integracao, dados):
    return chamada_conta_pagar(integracao, "IncluirContaPagar", dados)


def incluir_contas_pagar_lote(integracao, lote, contas):
    return chamada_conta_pagar(integracao, "IncluirContaPagarPorLote", {"lote": lote, "conta_pagar_cadastro": contas})


def consultar_conta_por_integracao(integracao, codigo):
    return chamada_conta_pagar(integracao, "ConsultarContaPagar", {"codigo_lancamento_integracao": codigo})


def incluir_anexo(integracao, dados):
    return chamada_conta_pagar(integracao, "IncluirAnexo", dados, url=ANEXOS_URL)


def consultar_anexo(integracao, codigo, titulo_id):
    return chamada_conta_pagar(integracao, "ConsultarAnexo", {
        "cCodIntAnexo": codigo, "cTabela": "conta-pagar", "nId": titulo_id,
    }, url=ANEXOS_URL)
