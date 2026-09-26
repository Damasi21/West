from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from apps.empresas.models import (
    AgendamentoSincronizacaoOmie,
    Empresa,
    IntegracaoOmie,
    SincronizacaoOmie,
)
from apps.empresas.omie import executar_sincronizacao_omie


TOLERANCIA_PADRAO_MINUTOS = 10
SINCRONIZACAO_EXPIRA_APOS = timedelta(minutes=30)


class Command(BaseCommand):
    help = "Executa sincronizacoes OMIE agendadas e vencidas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empresa",
            help="Slug da empresa para limitar a execucao.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria executado sem chamar a API.",
        )
        parser.add_argument(
            "--tolerancia-minutos",
            type=int,
            default=TOLERANCIA_PADRAO_MINUTOS,
            help=(
                "Janela maxima para executar um horario vencido. "
                "Padrao: 10 minutos."
            ),
        )

    def handle(self, *args, **options):
        agora = timezone.localtime()
        empresa_slug = options.get("empresa")
        dry_run = options.get("dry_run")
        tolerancia_minutos = max(1, options.get("tolerancia_minutos") or 1)
        self._encerrar_execucoes_obsoletas(agora, empresa_slug)
        pendentes_executadas = self._executar_pendentes(empresa_slug, dry_run)
        agendamentos = AgendamentoSincronizacaoOmie.objects.select_related(
            "empresa"
        ).filter(ativo=True, empresa__ativa=True)
        agendamentos = agendamentos.exclude(
            Q(empresa__tipo_conta=Empresa.TipoConta.TRIAL)
            & (
                Q(empresa__status_conta__in=[
                    Empresa.StatusConta.EXPIRADA,
                    Empresa.StatusConta.CANCELADA,
                ])
                | Q(empresa__trial_expira_em__lte=agora)
            )
        )
        if empresa_slug:
            agendamentos = agendamentos.filter(empresa__slug=empresa_slug)

        criadas = pendentes_executadas
        ignoradas = 0
        for agendamento in agendamentos:
            if not self._deve_rodar_hoje(agendamento, agora):
                ignoradas += 1
                continue
            if not IntegracaoOmie.objects.filter(
                empresa=agendamento.empresa,
                ativa=True,
            ).exists():
                self.stdout.write(
                    f"{agendamento.empresa}: integracao OMIE inativa ou ausente."
                )
                ignoradas += 1
                continue
            for item in agendamento.horarios_configurados:
                agendada_para = self._data_horario(agora, item["horario"])
                if not self._esta_dentro_da_janela(
                    agendada_para,
                    agora,
                    tolerancia_minutos,
                ):
                    continue
                if self._existe_execucao(agendamento, agendada_para):
                    continue
                if self._existe_execucao_ativa(agendamento.empresa):
                    self.stdout.write(
                        f"{agendamento.empresa}: ja existe sincronizacao em andamento."
                    )
                    ignoradas += 1
                    break
                if dry_run:
                    self.stdout.write(
                        f"[dry-run] {agendamento.empresa} em {agendada_para:%d/%m/%Y %H:%M}"
                    )
                    criadas += 1
                    continue
                sincronizacao = self._criar_execucao(
                    agendamento,
                    agendada_para,
                    item,
                )
                if not sincronizacao:
                    continue
                criadas += 1
                self.stdout.write(
                    (
                        f"Executando {sincronizacao.empresa} em "
                        f"{agendada_para:%d/%m/%Y %H:%M} "
                        f"({sincronizacao.recurso_label}, {sincronizacao.periodo_label})"
                    )
                )
                executar_sincronizacao_omie(sincronizacao.pk)

        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronizacoes criadas/executadas: {criadas}. Ignoradas: {ignoradas}."
            )
        )

    def _encerrar_execucoes_obsoletas(self, agora, empresa_slug=None):
        sincronizacoes = SincronizacaoOmie.objects.filter(
            status__in=[
                SincronizacaoOmie.Status.PENDENTE,
                SincronizacaoOmie.Status.EM_ANDAMENTO,
            ],
            atualizada_em__lt=agora - SINCRONIZACAO_EXPIRA_APOS,
        )
        if empresa_slug:
            sincronizacoes = sincronizacoes.filter(empresa__slug=empresa_slug)
        return sincronizacoes.update(
            status=SincronizacaoOmie.Status.ERRO,
            finalizada_em=agora,
            mensagem="Sincronizacao interrompida. Inicie uma nova atualizacao.",
            erro="A sincronizacao ficou sem atividade por mais de 30 minutos.",
        )

    def _executar_pendentes(self, empresa_slug=None, dry_run=False):
        sincronizacoes = SincronizacaoOmie.objects.select_related("empresa").filter(
            status=SincronizacaoOmie.Status.PENDENTE,
            empresa__ativa=True,
        )
        if empresa_slug:
            sincronizacoes = sincronizacoes.filter(empresa__slug=empresa_slug)
        sincronizacoes = sincronizacoes.order_by("criada_em")

        executadas = 0
        for sincronizacao in sincronizacoes:
            if self._existe_execucao_em_andamento(sincronizacao.empresa):
                continue
            if dry_run:
                self.stdout.write(f"[dry-run] pendente {sincronizacao.empresa}")
                executadas += 1
                continue
            self.stdout.write(
                (
                    f"Executando pendente {sincronizacao.empresa} "
                    f"({sincronizacao.recurso_label}, {sincronizacao.periodo_label})"
                )
            )
            executar_sincronizacao_omie(sincronizacao.pk)
            executadas += 1
        return executadas

    def _deve_rodar_hoje(self, agendamento, agora):
        if agendamento.tipo_agendamento == AgendamentoSincronizacaoOmie.Tipo.TODO_DIA:
            return True
        if agendamento.tipo_agendamento == AgendamentoSincronizacaoOmie.Tipo.DIAS_SEMANA:
            return agora.weekday() in [int(dia) for dia in agendamento.dias_semana or []]
        return False

    def _data_horario(self, agora, horario):
        hora = time.fromisoformat(horario)
        data_hora = datetime.combine(agora.date(), hora)
        return timezone.make_aware(data_hora, timezone.get_current_timezone())

    def _esta_dentro_da_janela(self, agendada_para, agora, tolerancia_minutos):
        if agendada_para > agora:
            return False
        atraso = agora - agendada_para
        return atraso.total_seconds() <= tolerancia_minutos * 60

    def _existe_execucao(self, agendamento, agendada_para):
        return SincronizacaoOmie.objects.filter(
            empresa=agendamento.empresa,
            agendamento=agendamento,
            agendada_para=agendada_para,
        ).exists()

    def _existe_execucao_ativa(self, empresa):
        return SincronizacaoOmie.objects.filter(
            empresa=empresa,
            status__in=[
                SincronizacaoOmie.Status.PENDENTE,
                SincronizacaoOmie.Status.EM_ANDAMENTO,
            ],
        ).exists()

    def _existe_execucao_em_andamento(self, empresa):
        return SincronizacaoOmie.objects.filter(
            empresa=empresa,
            status=SincronizacaoOmie.Status.EM_ANDAMENTO,
        ).exists()

    def _criar_execucao(self, agendamento, agendada_para, item):
        try:
            return SincronizacaoOmie.objects.create(
                empresa=agendamento.empresa,
                agendamento=agendamento,
                agendada_para=agendada_para,
                origem=SincronizacaoOmie.Origem.AGENDADA,
                recurso=item["recurso"],
                periodo=item["periodo"],
                mensagem="Sincronizacao automatica adicionada a fila.",
            )
        except IntegrityError:
            return None
