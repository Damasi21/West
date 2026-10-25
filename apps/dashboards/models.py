from django.db import models
from django.conf import settings
import uuid

from .contas_pagar_storage import armazenamento_contas_pagar, caminho_anexo_conta


class Dashboard(models.Model):
    class Area(models.TextChoices):
        COMERCIAL = "comercial", "Comercial"
        FINANCEIRO = "financeiro", "Financeiro"
        COMPRAS = "compras", "Compras"
        ESTOQUE = "estoque", "Estoque"
        CRM = "crm", "CRM"

    area = models.CharField(max_length=20, choices=Area.choices, unique=True)
    titulo = models.CharField(max_length=100)
    descricao = models.CharField(max_length=240, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["area"]

    def __str__(self):
        return self.titulo


class EnvioContasPagarLocal(models.Model):
    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    operacao = models.CharField(max_length=20, default="inclusao")
    status = models.CharField(max_length=20, default="aguardando")
    criado_em = models.DateTimeField(auto_now_add=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    resposta = models.JSONField(default=dict, blank=True)
    erro = models.TextField(blank=True)
    contas_ids = models.JSONField(default=list)
    payloads = models.JSONField(default=list, blank=True)


class ContaPagarLocal(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "rascunho", "Rascunho local"
        ENVIANDO = "enviando", "Envio em processamento"
        CONFIRMAR = "confirmar", "Aguardando confirmacao OMIE"
        INCERTO = "incerto", "Resultado nao confirmado"
        ERRO = "erro", "Envio recusado"
        ENVIADO = "enviado", "Enviado ao OMIE"
    class FormaPagamento(models.TextChoices):
        PIX = "pix", "PIX"
        BOLETO = "boleto", "Boleto"
        TRANSFERENCIA = "transferencia", "Transferencia bancaria"
        DINHEIRO = "dinheiro", "Dinheiro"
        CARTAO = "cartao", "Cartao"
        OUTRO = "outro", "Outro"

    empresa = models.ForeignKey("empresas.Empresa", on_delete=models.CASCADE, related_name="contas_pagar_locais")
    fornecedor = models.ForeignKey("empresas.CadastroOmie", on_delete=models.RESTRICT)
    descricao = models.CharField(max_length=255)
    categoria = models.ForeignKey("empresas.CategoriaOmie", on_delete=models.RESTRICT)
    departamento = models.ForeignKey("empresas.DepartamentoOmie", on_delete=models.RESTRICT)
    valor = models.DecimalField(max_digits=18, decimal_places=2)
    data_emissao = models.DateField()
    data_vencimento = models.DateField()
    data_previsao = models.DateField(null=True, blank=True)
    conta_corrente = models.ForeignKey("empresas.ContaCorrenteOmie", null=True, blank=True, on_delete=models.RESTRICT)
    forma_pagamento = models.CharField(max_length=20, choices=FormaPagamento.choices)
    documento = models.CharField(max_length=60, blank=True)
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    criado_em = models.DateTimeField(auto_now_add=True)
    token_cadastro = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RASCUNHO)
    codigo_lancamento_omie = models.BigIntegerField(null=True, blank=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="contas_locais_enviadas")
    envio = models.ForeignKey(EnvioContasPagarLocal, null=True, blank=True, on_delete=models.SET_NULL, related_name="contas")
    dados_envio = models.JSONField(default=dict, blank=True)
    erro_envio = models.TextField(blank=True)

    @property
    def editavel(self):
        return self.status in {self.Status.RASCUNHO, self.Status.ERRO}

    @property
    def codigo_integracao(self):
        return f"WEST-CP-{self.token_cadastro.hex}"

    @property
    def anexos_pendentes(self):
        return any(a.status_omie != "enviado" for a in self.anexos.all())

    class Meta:
        ordering = ["-criado_em", "-pk"]
        constraints = [models.CheckConstraint(check=models.Q(valor__gt=0), name="conta_local_valor_positivo")]
        indexes = [models.Index(fields=["empresa", "criado_em"], name="conta_local_emp_data_idx")]


class AnexoContaPagarLocal(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Aguardando envio"
        ENVIANDO = "enviando", "Envio em processamento"
        INCERTO = "incerto", "Aguardando confirmacao OMIE"
        ERRO = "erro", "Anexo nao enviado"
        ENVIADO = "enviado", "Anexo enviado a OMIE"

    conta = models.ForeignKey(ContaPagarLocal, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(storage=armazenamento_contas_pagar, upload_to=caminho_anexo_conta)
    nome_original = models.CharField(max_length=150)
    tamanho = models.PositiveIntegerField()
    criado_em = models.DateTimeField(auto_now_add=True)
    token_integracao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status_omie = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    codigo_anexo_omie = models.BigIntegerField(null=True, blank=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    erro_omie = models.TextField(blank=True)

    @property
    def codigo_integracao(self):
        return f"WA{self.token_integracao.hex[:18]}"


class AprovacaoPagamento(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADO = "aprovado", "Aprovado"
        REAGENDADO = "reagendado", "Reagendado"
        ERRO_OMIE = "erro_omie", "Erro OMIE"

    conta_pagar = models.OneToOneField(
        "empresas.ContaPagarOmie",
        on_delete=models.CASCADE,
        related_name="aprovacao_pagamento",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    data_previsao_original = models.DateField(null=True, blank=True)
    data_previsao_aprovada = models.DateField(null=True, blank=True)
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="aprovacoes_pagamentos",
        null=True,
        blank=True,
    )
    resposta_omie = models.JSONField(default=dict, blank=True)
    erro_omie = models.TextField(blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-atualizado_em"]
        indexes = [
            models.Index(fields=["status"], name="aprov_pag_status_idx"),
            models.Index(fields=["data_previsao_aprovada"], name="aprov_pag_prev_idx"),
        ]
        verbose_name = "aprovacao de pagamento"
        verbose_name_plural = "aprovacoes de pagamentos"

    def __str__(self):
        return f"{self.conta_pagar_id} - {self.get_status_display()}"
