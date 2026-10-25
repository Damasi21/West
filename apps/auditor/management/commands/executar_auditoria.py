from django.core.management.base import BaseCommand, CommandError
from apps.empresas.models import Empresa
from apps.auditor.services import executar_auditoria, solicitar_execucao


class Command(BaseCommand):
    help = "Executa uma auditoria da base local, sem consultar a OMIE."

    def add_arguments(self, parser):
        parser.add_argument("--empresa", required=True, help="Slug da empresa")

    def handle(self, *args, **options):
        try:
            empresa = Empresa.objects.get(slug=options["empresa"], ativa=True)
        except Empresa.DoesNotExist:
            raise CommandError("Empresa nao encontrada.")
        execucao, nova = solicitar_execucao(empresa, None)
        if not nova:
            raise CommandError(f"Ja existe a execucao #{execucao.pk} ativa. Nenhuma analise iniciada.")
        executar_auditoria(execucao.pk)
        execucao.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(f"Execucao #{execucao.pk}: {execucao.get_status_display()} - {execucao.resumo.get('sinais', 0)} sinais."))
