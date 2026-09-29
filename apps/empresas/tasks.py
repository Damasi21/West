from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import SincronizacaoOmie
from .omie import executar_sincronizacao_omie


FILA_OMIE_FAST = "omie_fast"
FILA_OMIE_NORMAL = "omie_normal"
FILA_OMIE_FULL = "omie_full"
FILA_OMIE_MANUAL = "omie_manual"


def fila_sincronizacao_omie(sincronizacao):
    if sincronizacao.origem == SincronizacaoOmie.Origem.MANUAL:
        return FILA_OMIE_MANUAL
    if (
        sincronizacao.recurso == SincronizacaoOmie.Recurso.COMPLETA
        or sincronizacao.periodo == SincronizacaoOmie.Periodo.TUDO
    ):
        return FILA_OMIE_FULL
    if sincronizacao.periodo in {
        SincronizacaoOmie.Periodo.MES_ATUAL,
        SincronizacaoOmie.Periodo.ULTIMOS_30_DIAS,
        SincronizacaoOmie.Periodo.ANO_ATUAL,
    } and sincronizacao.recurso in {
        SincronizacaoOmie.Recurso.FINANCEIRO,
        SincronizacaoOmie.Recurso.COMERCIAL,
        SincronizacaoOmie.Recurso.COMPRAS,
        SincronizacaoOmie.Recurso.ESTOQUE,
    }:
        return FILA_OMIE_FAST
    return FILA_OMIE_NORMAL


def enfileirar_sincronizacao_omie(sincronizacao):
    if sincronizacao.enfileirada_em:
        return None
    fila = fila_sincronizacao_omie(sincronizacao)
    resultado = executar_sincronizacao_omie_task.apply_async(
        args=[sincronizacao.pk],
        queue=fila,
    )
    agora = timezone.now()
    mensagem = sincronizacao.mensagem
    if fila == FILA_OMIE_MANUAL:
        mensagem = "Sincronizacao manual adicionada a fila. Aguardando inicio."
    SincronizacaoOmie.objects.filter(
        pk=sincronizacao.pk,
        enfileirada_em__isnull=True,
    ).update(
        enfileirada_em=agora,
        celery_task_id=resultado.id,
        mensagem=mensagem,
    )
    sincronizacao.enfileirada_em = agora
    sincronizacao.celery_task_id = resultado.id
    sincronizacao.mensagem = mensagem
    return resultado


@shared_task(
    bind=True,
    name="apps.empresas.executar_sincronizacao_omie",
    max_retries=None,
)
def executar_sincronizacao_omie_task(self, sincronizacao_id):
    with transaction.atomic():
        sincronizacao = (
            SincronizacaoOmie.objects.select_for_update()
            .select_related("empresa")
            .get(pk=sincronizacao_id)
        )
        if sincronizacao.status != SincronizacaoOmie.Status.PENDENTE:
            return "ignorada"

        sincronizacao_manual = (
            sincronizacao.origem == SincronizacaoOmie.Origem.MANUAL
        )
        outra_em_andamento = (
            SincronizacaoOmie.objects.select_for_update()
            .filter(
                empresa=sincronizacao.empresa,
                status=SincronizacaoOmie.Status.EM_ANDAMENTO,
            )
            .exclude(pk=sincronizacao.pk)
            .exists()
        )
        pendente_anterior = False
        if not sincronizacao_manual:
            pendente_anterior = (
                SincronizacaoOmie.objects.select_for_update()
                .filter(
                    empresa=sincronizacao.empresa,
                    status=SincronizacaoOmie.Status.PENDENTE,
                    criada_em__lt=sincronizacao.criada_em,
                )
                .exclude(pk=sincronizacao.pk)
                .exists()
            )
        if outra_em_andamento or pendente_anterior:
            raise self.retry(countdown=60)

    executar_sincronizacao_omie(sincronizacao_id)
    return "concluida"
