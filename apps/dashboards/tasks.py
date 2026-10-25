from celery import shared_task

from .contas_pagar_envio import executar_envio


@shared_task(name="apps.dashboards.processar_contas_pagar_locais", acks_late=True, reject_on_worker_lost=True)
def processar_contas_pagar_locais(envio_id):
    return executar_envio(envio_id)
