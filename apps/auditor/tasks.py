from celery import shared_task
from celery.signals import task_failure
from django.utils import timezone
from .models import ExecucaoAuditoria
from .services import executar_auditoria


@shared_task(name="apps.auditor.executar", soft_time_limit=1740, time_limit=1800)
def executar_auditoria_task(execucao_id):
    executar_auditoria(execucao_id)


@task_failure.connect
def registrar_falha_worker(sender=None, args=None, **kwargs):
    if getattr(sender, "name", None) != "apps.auditor.executar" or not args:
        return
    ExecucaoAuditoria.objects.filter(pk=args[0], status__in=["fila", "executando"]).update(
        status="erro", finalizada_em=timezone.now(),
        erro="Execucao interrompida pelo worker. Evidencias parciais nao foram publicadas. Confira os logs antes de tentar novamente.",
    )
