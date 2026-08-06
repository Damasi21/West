from django.db import models


class BudgetConfiguracaoCompra(models.Model):
    class TipoControle(models.TextChoices):
        PRODUTO = "produto", "Produto"
        FAMILIA_PRODUTO = "familia_produto", "Familia de produto"
        PROJETO = "projeto", "Projeto"
        FORNECEDOR = "fornecedor", "Fornecedor"

    empresa = models.OneToOneField(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="budget_compras",
    )
    tipo_controle = models.CharField(
        max_length=20,
        choices=TipoControle.choices,
        default=TipoControle.PRODUTO,
    )
    tipos_controle = models.JSONField(default=list, blank=True)
    modalidades_controle = models.JSONField(default=dict, blank=True)
    totais_grupo = models.JSONField(default=dict, blank=True)
    periodicidades_controle = models.JSONField(default=dict, blank=True)
    meses_controle = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuracao de budget de compras"
        verbose_name_plural = "configuracoes de budget de compras"

    def __str__(self):
        return f"Budget de compras - {self.empresa}"

    @property
    def tipos_selecionados(self):
        tipos_validos = set(self.TipoControle.values)
        tipos = [
            tipo
            for tipo in (self.tipos_controle or [])
            if tipo in tipos_validos
        ]
        if tipos:
            return tipos
        return [self.tipo_controle or self.TipoControle.PRODUTO]

    def definir_tipos(self, tipos):
        tipos_validos = set(self.TipoControle.values)
        selecionados = []
        for tipo in tipos:
            if tipo in tipos_validos and tipo not in selecionados:
                selecionados.append(tipo)
        if not selecionados:
            selecionados = [self.TipoControle.PRODUTO]
        self.tipos_controle = selecionados
        self.tipo_controle = selecionados[0]

    def rotulos_tipos(self):
        rotulos = dict(self.TipoControle.choices)
        return [rotulos[tipo] for tipo in self.tipos_selecionados]


class BudgetLimiteCompra(models.Model):
    empresa = models.ForeignKey(
        "empresas.Empresa",
        on_delete=models.CASCADE,
        related_name="limites_budget_compras",
    )
    configuracao = models.ForeignKey(
        BudgetConfiguracaoCompra,
        on_delete=models.CASCADE,
        related_name="limites",
    )
    tipo_controle = models.CharField(
        max_length=20,
        choices=BudgetConfiguracaoCompra.TipoControle.choices,
    )
    referencia_codigo = models.CharField(max_length=120)
    referencia_nome = models.CharField(max_length=255, blank=True)
    estoque_minimo = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    limite_compra = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["referencia_nome", "referencia_codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_controle", "referencia_codigo"],
                name="budget_limite_empresa_tipo_ref_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "tipo_controle"],
                name="budget_limite_emp_tipo_idx",
            )
        ]
        verbose_name = "limite de budget de compras"
        verbose_name_plural = "limites de budget de compras"

    def __str__(self):
        return f"{self.referencia_nome or self.referencia_codigo} - {self.limite_compra}"
