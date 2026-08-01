"""Dados para o painel de aprovacao de pagamentos."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Trim, Upper
from django.utils.dateparse import parse_date

from apps.dashboards.dre_services import _formatar_moeda
from apps.dashboards.finance_filters import (
    contas_correntes_visiveis_financeiro,
    registros_com_conta_visivel_financeiro,
)
from apps.dashboards.fluxo_caixa_services import (
    STATUS_FECHADOS_PAGAR,
    STATUS_FECHADOS_RECEBER,
)
from apps.dashboards.models import AprovacaoPagamento
from apps.empresas.omie import OmieAPIError, alterar_conta_pagar
from apps.dashboards.visao_geral_services import _formatar_moeda_curta
from apps.empresas.models import (
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    IntegracaoOmie,
)


def _decimal(valor):
    if valor is None or valor == "":
        return Decimal("0")
    return Decimal(str(valor))


def _nome_fornecedor(conta):
    fornecedor = conta.fornecedor
    return (
        getattr(fornecedor, "nome_fantasia", "")
        or getattr(fornecedor, "razao_social", "")
        or conta.numero_documento
        or "Fornecedor nao informado"
    )


def _nome_cliente(conta):
    cliente = conta.cliente
    return (
        getattr(cliente, "nome_fantasia", "")
        or getattr(cliente, "razao_social", "")
        or conta.numero_documento
        or "Cliente nao informado"
    )


def _categoria(conta):
    return (
        getattr(conta.categoria_principal, "descricao", "")
        or conta.codigo_categoria
        or "Sem categoria"
    )


def _saldo_contas_correntes(empresas_ids):
    total = contas_correntes_visiveis_financeiro(
        ContaCorrenteOmie.objects.filter(
            empresa_id__in=empresas_ids,
            inativo=False,
            saldo_atual__isnull=False,
        )
    ).aggregate(total=Sum("saldo_atual"))["total"]
    return _decimal(total)


def _contas_pagar_do_periodo(inicio, fim, empresas_ids, projetos):
    queryset = ContaPagarOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_previsao__gte=inicio,
        data_previsao__lte=fim,
    ).annotate(
        status_titulo_normalizado=Upper(Trim("status_titulo"))
    ).exclude(
        status_titulo_normalizado__in=STATUS_FECHADOS_PAGAR
    )
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(
        queryset,
        "id_conta_corrente",
    ).select_related("empresa", "fornecedor", "categoria_principal")


def _contas_receber_do_periodo(inicio, fim, empresas_ids, projetos):
    queryset = ContaReceberOmie.objects.filter(
        empresa_id__in=empresas_ids,
        data_vencimento__gte=inicio,
        data_vencimento__lte=fim,
    ).exclude(status_titulo__in=STATUS_FECHADOS_RECEBER)
    if projetos:
        queryset = queryset.filter(codigo_projeto__in=projetos)
    return registros_com_conta_visivel_financeiro(
        queryset,
        "id_conta_corrente",
    ).select_related("empresa", "cliente", "categoria_principal")


def _linhas_pagamentos(contas):
    linhas = []
    for conta in contas.select_related("aprovacao_pagamento").order_by(
        "data_previsao",
        "data_vencimento",
        "codigo_lancamento_omie",
    ):
        valor = abs(_decimal(conta.valor_a_pagar or conta.valor_documento))
        previsao = conta.data_previsao
        vencimento = conta.data_vencimento
        aprovacao = getattr(conta, "aprovacao_pagamento", None)
        status = getattr(aprovacao, "status", AprovacaoPagamento.Status.PENDENTE)
        status_rotulos = {
            AprovacaoPagamento.Status.PENDENTE: "Pendente",
            AprovacaoPagamento.Status.APROVADO: "Aprovado",
            AprovacaoPagamento.Status.REAGENDADO: "Reagendado",
            AprovacaoPagamento.Status.ERRO_OMIE: "Erro OMIE",
        }
        status_classes = {
            AprovacaoPagamento.Status.PENDENTE: "pending",
            AprovacaoPagamento.Status.APROVADO: "approved",
            AprovacaoPagamento.Status.REAGENDADO: "rescheduled",
            AprovacaoPagamento.Status.ERRO_OMIE: "error",
        }
        enviado_omie = bool(getattr(aprovacao, "resposta_omie", None))
        linhas.append(
            {
                "id": conta.pk,
                "codigo_lancamento_omie": conta.codigo_lancamento_omie,
                "empresa": conta.empresa.nome_fantasia,
                "nome": _nome_fornecedor(conta),
                "categoria": _categoria(conta),
                "valor": valor,
                "valor_num": str(valor),
                "valor_fmt": _formatar_moeda(valor),
                "previsao": previsao.isoformat() if previsao else "",
                "previsao_fmt": previsao.strftime("%d/%m/%Y") if previsao else "-",
                "vencimento": vencimento.isoformat() if vencimento else "",
                "vencimento_fmt": vencimento.strftime("%d/%m/%Y") if vencimento else "-",
                "status": status_rotulos.get(status, "Pendente"),
                "status_valor": status_classes.get(status, "pending"),
                "status_classe": status_classes.get(status, "pending"),
                "erro_omie": getattr(aprovacao, "erro_omie", "") if aprovacao else "",
                "enviado_omie": enviado_omie,
            }
        )
    return linhas


def _linhas_recebimentos(contas):
    linhas = []
    for conta in contas.order_by("data_vencimento", "codigo_lancamento_omie"):
        valor = abs(_decimal(conta.valor_a_receber or conta.valor_documento))
        vencimento = conta.data_vencimento
        linhas.append(
            {
                "id": conta.pk,
                "empresa": conta.empresa.nome_fantasia,
                "nome": _nome_cliente(conta),
                "categoria": _categoria(conta),
                "valor_fmt": _formatar_moeda(valor),
                "vencimento_fmt": vencimento.strftime("%d/%m/%Y") if vencimento else "-",
                "status": conta.status_titulo or "Aberto",
            }
        )
    return linhas


def _categorias_pagamentos(linhas):
    totais = defaultdict(Decimal)
    for linha in linhas:
        totais[linha["categoria"]] += linha["valor"]
    ordenados = sorted(totais.items(), key=lambda item: item[1], reverse=True)[:5]
    maior = max((valor for _, valor in ordenados), default=Decimal("0"))
    return [
        {
            "nome": nome,
            "valor_fmt": _formatar_moeda(valor),
            "largura": int((valor / maior) * 100) if maior else 0,
        }
        for nome, valor in ordenados
    ]


def painel_aprovacao_pagamentos(
    empresa,
    empresas_ids=None,
    projetos_selecionados=None,
    periodo_inicio=None,
    periodo_fim=None,
    abrir_modal="",
):
    empresas_ids = empresas_ids or [empresa.pk]
    projetos = []
    for item in projetos_selecionados or []:
        try:
            _, codigo = item.split(":", 1)
            projetos.append(int(codigo))
        except (TypeError, ValueError):
            continue

    periodo_inicio = periodo_inicio or date.today()
    periodo_fim = periodo_fim or periodo_inicio
    saldo_atual = _saldo_contas_correntes(empresas_ids)
    contas_pagar = _contas_pagar_do_periodo(
        periodo_inicio,
        periodo_fim,
        empresas_ids,
        projetos,
    )
    contas_receber = _contas_receber_do_periodo(
        periodo_inicio,
        periodo_fim,
        empresas_ids,
        projetos,
    )
    pagamentos = _linhas_pagamentos(contas_pagar)
    recebimentos = _linhas_recebimentos(contas_receber)
    total_pagar = sum((linha["valor"] for linha in pagamentos), Decimal("0"))
    total_receber = sum(
        (
            abs(_decimal(conta.valor_a_receber or conta.valor_documento))
            for conta in contas_receber
        ),
        Decimal("0"),
    )
    comprometimento = (total_pagar / saldo_atual * 100) if saldo_atual > 0 else Decimal("0")
    comprometimento = max(Decimal("0"), comprometimento)
    aprovado_total = Decimal("0")
    pendente_total = Decimal("0")
    aprovados_count = 0
    reagendados_count = 0
    pendentes_count = 0
    for linha in pagamentos:
        if linha["status_valor"] == "approved":
            aprovado_total += linha["valor"]
            aprovados_count += 1
        elif linha["status_valor"] == "rescheduled":
            reagendados_count += 1
        else:
            pendente_total += linha["valor"]
            pendentes_count += 1
    taxa_aprovacao = round((aprovados_count / len(pagamentos)) * 100) if pagamentos else 0

    return {
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "periodo_inicio_iso": periodo_inicio.isoformat(),
        "periodo_fim_iso": periodo_fim.isoformat(),
        "periodo_rotulo": (
            periodo_inicio.strftime("%d/%m/%Y")
            if periodo_inicio == periodo_fim
            else f"{periodo_inicio:%d/%m/%Y} a {periodo_fim:%d/%m/%Y}"
        ),
        "abrir_modal": abrir_modal,
        "saldo_atual": _formatar_moeda(saldo_atual),
        "saldo_atual_curto": _formatar_moeda_curta(saldo_atual),
        "total_pagar": _formatar_moeda(total_pagar),
        "total_pagar_curto": _formatar_moeda_curta(total_pagar),
        "total_receber": _formatar_moeda(total_receber),
        "pendente_total": _formatar_moeda(pendente_total),
        "aprovado_total": _formatar_moeda(aprovado_total),
        "comprometimento": f"{comprometimento:.1f}".replace(".", ","),
        "comprometimento_largura": min(int(comprometimento), 100),
        "taxa_aprovacao": taxa_aprovacao,
        "pagamentos_count": len(pagamentos),
        "recebimentos_count": len(recebimentos),
        "pendentes_count": pendentes_count,
        "aprovados_count": aprovados_count,
        "reagendados_count": reagendados_count,
        "pagamentos": pagamentos,
        "recebimentos": recebimentos,
        "categorias": _categorias_pagamentos(pagamentos),
    }


def _formatar_data_omie(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


def _dados_alteracao_conta_pagar(conta, nova_previsao):
    obrigatorios = {
        "codigo_lancamento_omie": conta.codigo_lancamento_omie,
        "codigo_cliente_fornecedor": conta.codigo_cliente_fornecedor,
        "data_vencimento": _formatar_data_omie(conta.data_vencimento),
        "valor_documento": float(abs(_decimal(conta.valor_documento))),
        "codigo_categoria": conta.codigo_categoria,
        "data_previsao": _formatar_data_omie(nova_previsao),
        "id_conta_corrente": conta.id_conta_corrente,
    }
    faltando = [chave for chave, valor in obrigatorios.items() if valor in (None, "")]
    if faltando:
        raise ValueError(
            "Campos obrigatorios ausentes para AlterarContaPagar: "
            + ", ".join(faltando)
        )
    return obrigatorios


def _erro_omie_temporario(mensagem):
    mensagem = str(mensagem).upper()
    return "REDUNDANT" in mensagem or "CONSUMO REDUNDANTE" in mensagem


def salvar_aprovacoes_pagamentos(empresa, usuario, itens):
    ids = [item.get("id") for item in itens if item.get("id")]
    contas = {
        conta.pk: conta
        for conta in ContaPagarOmie.objects.filter(
            empresa=empresa,
            pk__in=ids,
        )
    }
    integracao = IntegracaoOmie.objects.filter(empresa=empresa, ativa=True).first()
    resultados = []
    erros = []

    for item in itens:
        conta = contas.get(item.get("id"))
        if not conta:
            erros.append({"id": item.get("id"), "erro": "Lancamento nao encontrado."})
            continue

        status = item.get("status")
        if status not in {"pending", "approved", "rescheduled"}:
            erros.append({"id": conta.pk, "erro": "Status invalido."})
            continue

        mapa_status = {
            "pending": AprovacaoPagamento.Status.PENDENTE,
            "approved": AprovacaoPagamento.Status.APROVADO,
            "rescheduled": AprovacaoPagamento.Status.REAGENDADO,
        }
        nova_previsao = parse_date(item.get("new_date") or item.get("nova_previsao") or "")

        aprovacao, _ = AprovacaoPagamento.objects.get_or_create(
            conta_pagar=conta,
            defaults={"data_previsao_original": conta.data_previsao},
        )
        if aprovacao.resposta_omie:
            erros.append(
                {
                    "id": conta.pk,
                    "erro": "Lancamento ja enviado ao Omie. Altere somente no Omie.",
                }
            )
            continue
        aprovacao.status = mapa_status[status]
        aprovacao.aprovado_por = usuario
        aprovacao.erro_omie = ""
        aprovacao.resposta_omie = {}
        if status == "rescheduled":
            if not nova_previsao:
                aprovacao.status = AprovacaoPagamento.Status.ERRO_OMIE
                aprovacao.erro_omie = "Nova previsao nao informada."
                aprovacao.save()
                erros.append({"id": conta.pk, "erro": aprovacao.erro_omie})
                continue
            if nova_previsao == conta.data_previsao:
                aprovacao.data_previsao_aprovada = nova_previsao
                aprovacao.save()
                resultados.append(
                    {
                        "id": conta.pk,
                        "status": status,
                        "data_previsao": nova_previsao.isoformat(),
                        "omie": "ignorado_sem_alteracao",
                    }
                )
                continue
            if not integracao:
                aprovacao.status = AprovacaoPagamento.Status.ERRO_OMIE
                aprovacao.erro_omie = "Integracao Omie ativa nao encontrada."
                aprovacao.data_previsao_aprovada = nova_previsao
                aprovacao.save()
                erros.append({"id": conta.pk, "erro": aprovacao.erro_omie})
                continue
            try:
                dados_alteracao = _dados_alteracao_conta_pagar(conta, nova_previsao)
                resposta = alterar_conta_pagar(integracao, dados_alteracao)
            except (OmieAPIError, ValueError) as exc:
                aprovacao.status = AprovacaoPagamento.Status.ERRO_OMIE
                aprovacao.erro_omie = str(exc)
                aprovacao.data_previsao_aprovada = nova_previsao
                aprovacao.save()
                erros.append(
                    {
                        "id": conta.pk,
                        "erro": str(exc),
                        "temporario": _erro_omie_temporario(exc),
                    }
                )
                continue

            conta.data_previsao = nova_previsao
            conta.dados_originais = {
                **(conta.dados_originais or {}),
                "data_previsao": _formatar_data_omie(nova_previsao),
            }
            conta.save(update_fields=["data_previsao", "dados_originais", "sincronizado_em"])
            aprovacao.data_previsao_aprovada = nova_previsao
            aprovacao.resposta_omie = resposta
        else:
            aprovacao.data_previsao_aprovada = conta.data_previsao

        aprovacao.save()
        resultados.append(
            {
                "id": conta.pk,
                "status": status,
                "data_previsao": (
                    aprovacao.data_previsao_aprovada.isoformat()
                    if aprovacao.data_previsao_aprovada
                    else ""
                ),
                "omie": "alterado" if status == "rescheduled" else "nao_aplicavel",
            }
        )

    return {
        "sucesso": not erros,
        "resultados": resultados,
        "erros": erros,
    }
