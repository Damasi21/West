import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Mantem o robo de sincronizacao OMIE rodando em intervalos regulares."

    def add_arguments(self, parser):
        parser.add_argument(
            "--intervalo-segundos",
            type=int,
            default=60,
            help="Intervalo entre verificacoes. Padrao: 60 segundos.",
        )
        parser.add_argument(
            "--empresa",
            help="Slug da empresa para limitar a execucao.",
        )
        parser.add_argument(
            "--tolerancia-minutos",
            type=int,
            default=10,
            help="Janela maxima para executar um horario vencido. Padrao: 10 minutos.",
        )

    def handle(self, *args, **options):
        intervalo = max(10, options["intervalo_segundos"])
        empresa_slug = options.get("empresa")
        tolerancia = max(1, options["tolerancia_minutos"])
        self.stdout.write(
            self.style.SUCCESS(
                "Monitor de sincronizacao OMIE iniciado. "
                "Pressione Ctrl+C para parar."
            )
        )
        try:
            while True:
                self.stdout.write(
                    f"Verificando agendamentos em {timezone.localtime():%d/%m/%Y %H:%M:%S}"
                )
                parametros = {
                    "tolerancia_minutos": tolerancia,
                    "stdout": self.stdout,
                }
                if empresa_slug:
                    parametros["empresa"] = empresa_slug
                call_command("executar_sincronizacoes_agendadas", **parametros)
                time.sleep(intervalo)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Monitor de sincronizacao parado."))
