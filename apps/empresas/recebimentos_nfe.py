from django.db import transaction

from .models import RecebimentoNfeOmie, RecebimentoNfeTituloOmie


def codigos_titulos_recebimento(parcelas):
    lista = parcelas.get("parcelasLista", []) if isinstance(parcelas, dict) else []
    if not isinstance(lista, list):
        return set()
    codigos = set()
    for parcela in lista:
        valor = parcela.get("nIdTitulo") if isinstance(parcela, dict) else None
        texto = str(valor or "").strip()
        if texto.isascii() and texto.isdigit() and 0 < int(texto) <= 9223372036854775807:
            codigos.add(int(texto))
    return codigos


def atualizar_titulos_recebimento(recebimento):
    with transaction.atomic():
        # The row lock keeps replacement of the title index atomic for each receipt.
        recebimento = RecebimentoNfeOmie.objects.select_for_update().get(pk=recebimento.pk)
        codigos = codigos_titulos_recebimento(recebimento.parcelas)
        recebimento.titulos_financeiros.exclude(codigo_lancamento_omie__in=codigos).delete()
        RecebimentoNfeTituloOmie.objects.bulk_create([
            RecebimentoNfeTituloOmie(recebimento=recebimento, codigo_lancamento_omie=codigo)
            for codigo in codigos
        ], ignore_conflicts=True)
