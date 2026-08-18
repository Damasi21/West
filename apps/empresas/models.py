import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .categorias import eh_categoria_transferencia


def ano_atual():
    return timezone.localdate().year


def mes_atual():
    return timezone.localdate().month


class Empresa(models.Model):
    nome = models.CharField("razão social", max_length=180)
    nome_fantasia = models.CharField(max_length=120)
    cnpj = models.CharField(max_length=18, unique=True)
    grupo = models.CharField(max_length=120, blank=True, db_index=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    logo = models.ImageField(upload_to="clientes/", blank=True, null=True)
    ativa = models.BooleanField(default=True)
    saldo_contas_omie = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    saldo_contas_atualizado_em = models.DateTimeField(null=True, blank=True)
    resumo_financeiro_omie = models.JSONField(default=dict, blank=True)
    usuarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="EmpresaUsuario",
        related_name="empresas",
    )
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome_fantasia"]
        verbose_name = "empresa"
        verbose_name_plural = "empresas"

    def __str__(self):
        return self.nome_fantasia

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nome_fantasia) or "empresa"
            slug = base
            counter = 2
            while Empresa.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("dashboards:home", kwargs={"empresa_slug": self.slug})


class EmpresaUsuario(models.Model):
    class Papel(models.TextChoices):
        ADMINISTRADOR = "admin", "Administrador"
        GESTOR = "gestor", "Gestor"
        VISUALIZADOR = "viewer", "Visualizador"

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name="vinculos"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vinculos_empresas",
    )
    papel = models.CharField(
        max_length=10, choices=Papel.choices, default=Papel.VISUALIZADOR
    )
    areas_permitidas = models.JSONField(default=list, blank=True)
    dashboards_permitidos = models.JSONField(default=list, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "usuario"], name="empresa_usuario_unico"
            )
        ]
        verbose_name = "acesso à empresa"
        verbose_name_plural = "acessos às empresas"

    def __str__(self):
        return f"{self.usuario} - {self.empresa} ({self.get_papel_display()})"


class IntegracaoOmie(models.Model):
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name="integracao_omie",
    )
    app_key = models.CharField("App Key", max_length=100)
    app_secret_criptografado = models.TextField()
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "integração OMIE"
        verbose_name_plural = "integrações OMIE"

    def __str__(self):
        return f"OMIE - {self.empresa}"

    def definir_app_secret(self, valor):
        from .security import criptografar_credencial

        self.app_secret_criptografado = criptografar_credencial(valor)

    def obter_app_secret(self):
        from .security import descriptografar_credencial

        return descriptografar_credencial(self.app_secret_criptografado)


class CadastroOmie(models.Model):
    class Tipo(models.TextChoices):
        CLIENTE = "cliente", "Cliente"
        FORNECEDOR = "fornecedor", "Fornecedor"
        AMBOS = "ambos", "Cliente e fornecedor"
        OUTRO = "outro", "Outro"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="cadastros_omie",
    )
    codigo_cliente_omie = models.BigIntegerField()
    codigo_cliente_integracao = models.CharField(max_length=100, blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.OUTRO)
    razao_social = models.CharField(max_length=255, blank=True)
    nome_fantasia = models.CharField(max_length=255, blank=True)
    cnpj_cpf = models.CharField(max_length=30, blank=True, db_index=True)
    pessoa_fisica = models.BooleanField(default=False)
    inativo = models.BooleanField(default=False)
    bloquear_faturamento = models.BooleanField(default=False)
    exterior = models.BooleanField(default=False)
    enviar_anexos = models.BooleanField(default=False)
    inscricao_estadual = models.CharField(max_length=50, blank=True)
    inscricao_municipal = models.CharField(max_length=50, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
    endereco_numero = models.CharField(max_length=60, blank=True)
    complemento = models.CharField(max_length=255, blank=True)
    bairro = models.CharField(max_length=120, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    cidade_ibge = models.CharField(max_length=30, blank=True)
    estado = models.CharField(max_length=10, blank=True)
    cep = models.CharField(max_length=20, blank=True)
    codigo_pais = models.CharField(max_length=20, blank=True)
    dados_bancarios = models.JSONField(default=dict, blank=True)
    endereco_entrega = models.JSONField(default=dict, blank=True)
    recomendacoes = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    info = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["razao_social", "nome_fantasia"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_cliente_omie"],
                name="cadastro_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "tipo"], name="cad_omie_emp_tipo_idx"),
            models.Index(fields=["empresa", "inativo"], name="cad_omie_emp_ativo_idx"),
        ]
        verbose_name = "cadastro OMIE"
        verbose_name_plural = "cadastros OMIE"

    def __str__(self):
        return self.razao_social or self.nome_fantasia or str(self.codigo_cliente_omie)


class ProjetoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="projetos_omie",
    )
    codigo = models.BigIntegerField()
    codigo_integracao = models.CharField(max_length=20, blank=True)
    nome = models.CharField(max_length=100)
    inativo = models.BooleanField(default=False)
    info = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="projeto_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "inativo"], name="proj_omie_emp_ativo_idx")
        ]
        verbose_name = "projeto OMIE"
        verbose_name_plural = "projetos OMIE"

    def __str__(self):
        return self.nome


class DepartamentoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="departamentos_omie",
    )
    codigo = models.CharField(max_length=40)
    descricao = models.CharField(max_length=100)
    estrutura = models.CharField(max_length=40, blank=True)
    inativo = models.BooleanField(default=False)
    nivel_totalizador = models.BooleanField(default=False)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["estrutura", "descricao"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="departamento_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "inativo"], name="dep_omie_emp_ativo_idx")
        ]
        verbose_name = "departamento OMIE"
        verbose_name_plural = "departamentos OMIE"

    def __str__(self):
        return self.descricao


class VendedorOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="vendedores_omie",
    )
    codigo = models.BigIntegerField()
    codigo_integracao = models.CharField(max_length=100, blank=True)
    nome = models.CharField(max_length=150, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    comissao = models.DecimalField(max_digits=9, decimal_places=4, default=0)
    fatura_pedido = models.BooleanField(default=False)
    visualiza_pedido = models.BooleanField(default=False)
    inativo = models.BooleanField(default=False)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome", "codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="vendedor_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "inativo"],
                name="vend_omie_emp_ativo_idx",
            ),
        ]
        verbose_name = "vendedor OMIE"
        verbose_name_plural = "vendedores OMIE"

    def __str__(self):
        return self.nome or str(self.codigo)


class ProdutoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="produtos_omie",
    )
    codigo_produto = models.BigIntegerField()
    codigo = models.CharField(max_length=60, blank=True)
    codigo_produto_integracao = models.CharField(max_length=100, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    descr_detalhada = models.TextField(blank=True)
    unidade = models.CharField(max_length=10, blank=True)
    ncm = models.CharField(max_length=20, blank=True)
    ean = models.CharField(max_length=30, blank=True)
    marca = models.CharField(max_length=100, blank=True)
    modelo = models.CharField(max_length=100, blank=True)
    tipo_item = models.CharField(max_length=5, blank=True)
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    quantidade_estoque = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    estoque_minimo = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    peso_bruto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    peso_liq = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    altura = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    largura = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    profundidade = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    codigo_familia = models.BigIntegerField(null=True, blank=True)
    codigo_integracao_familia = models.CharField(max_length=100, blank=True)
    descricao_familia = models.CharField(max_length=120, blank=True)
    bloqueado = models.BooleanField(default=False)
    inativo = models.BooleanField(default=False)
    importado_api = models.BooleanField(default=False)
    produto_lote = models.BooleanField(default=False)
    produto_variacao = models.BooleanField(default=False)
    bloquear_exclusao = models.BooleanField(default=False)
    info = models.JSONField(default=dict, blank=True)
    recomendacoes_fiscais = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["descricao", "codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_produto"],
                name="produto_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "inativo"],
                name="prod_omie_emp_ativo_idx",
            ),
            models.Index(
                fields=["empresa", "codigo"],
                name="prod_omie_emp_codigo_idx",
            ),
        ]
        verbose_name = "produto OMIE"
        verbose_name_plural = "produtos OMIE"

    def __str__(self):
        return self.descricao or self.codigo or str(self.codigo_produto)


class PosicaoEstoqueOmie(models.Model):
    class Origem(models.TextChoices):
        MANUAL = "manual", "Manual"
        AGENDADA = "agendada", "Agendada"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="posicoes_estoque_omie",
    )
    produto = models.ForeignKey(
        ProdutoOmie,
        on_delete=models.SET_NULL,
        related_name="posicoes_estoque_omie",
        null=True,
        blank=True,
    )
    codigo_produto = models.BigIntegerField()
    codigo_local_estoque = models.BigIntegerField(default=0)
    codigo = models.CharField(max_length=60, blank=True)
    codigo_integracao = models.CharField(max_length=100, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    data_posicao = models.DateField(null=True, blank=True)
    estoque_minimo = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    fisico = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    pendente = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    reservado = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    saldo = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cmc = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    preco_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["descricao", "codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_produto", "codigo_local_estoque"],
                name="pos_est_emp_prod_local_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "codigo_produto"],
                name="pos_est_emp_prod_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_local_estoque"],
                name="pos_est_emp_local_idx",
            ),
        ]
        verbose_name = "posicao de estoque OMIE"
        verbose_name_plural = "posicoes de estoque OMIE"

    def __str__(self):
        return self.descricao or self.codigo or str(self.codigo_produto)


class ServicoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="servicos_omie",
    )
    codigo_servico = models.BigIntegerField()
    codigo_integracao_servico = models.CharField(max_length=100, blank=True)
    codigo = models.CharField(max_length=60, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    descricao_completa = models.TextField(blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="servicos_omie",
        null=True,
        blank=True,
    )
    codigo_lc116 = models.CharField(max_length=20, blank=True)
    codigo_servico_municipal = models.CharField(max_length=40, blank=True)
    id_tributacao = models.CharField(max_length=10, blank=True)
    tipo_desconto = models.CharField(max_length=10, blank=True)
    preco_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    aliquota_desconto = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
    )
    valor_desconto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    aliquota_iss = models.DecimalField(max_digits=9, decimal_places=4, default=0)
    ret_cofins = models.BooleanField(default=False)
    ret_csll = models.BooleanField(default=False)
    ret_inss = models.BooleanField(default=False)
    ret_ir = models.BooleanField(default=False)
    ret_iss = models.BooleanField(default=False)
    ret_pis = models.BooleanField(default=False)
    deduz_iss = models.BooleanField(default=False)
    importado_api = models.BooleanField(default=False)
    inativo = models.BooleanField(default=False)
    cabecalho = models.JSONField(default=dict, blank=True)
    descricao_dados = models.JSONField(default=dict, blank=True)
    impostos = models.JSONField(default=dict, blank=True)
    info = models.JSONField(default=dict, blank=True)
    int_listar = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["descricao", "codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_servico"],
                name="servico_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "inativo"],
                name="serv_omie_emp_ativo_idx",
            ),
            models.Index(
                fields=["empresa", "codigo"],
                name="serv_omie_emp_codigo_idx",
            ),
        ]
        verbose_name = "servico OMIE"
        verbose_name_plural = "servicos OMIE"

    def __str__(self):
        return self.descricao or self.codigo or str(self.codigo_servico)


class OrdemServicoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ordens_servico_omie",
    )
    codigo_os = models.BigIntegerField()
    codigo_integracao_os = models.CharField(max_length=100, blank=True)
    numero_os = models.CharField(max_length=30, blank=True)
    etapa = models.CharField(max_length=10, blank=True)
    codigo_parcela = models.CharField(max_length=20, blank=True)
    codigo_cliente = models.BigIntegerField(null=True, blank=True)
    cliente = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="ordens_servico_omie",
        null=True,
        blank=True,
    )
    data_previsao = models.DateField(null=True, blank=True)
    quantidade_parcelas = models.PositiveIntegerField(default=0)
    valor_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total_impostos_retidos = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="ordens_servico_omie",
        null=True,
        blank=True,
    )
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        "ContaCorrenteOmie",
        on_delete=models.SET_NULL,
        related_name="ordens_servico_omie",
        null=True,
        blank=True,
    )
    codigo_vendedor = models.BigIntegerField(null=True, blank=True)
    cidade_prestacao = models.CharField(max_length=120, blank=True)
    numero_contrato = models.CharField(max_length=60, blank=True)
    numero_recibo = models.CharField(max_length=40, blank=True)
    uso_consumo = models.BooleanField(default=False)
    cancelada = models.BooleanField(default=False)
    faturada = models.BooleanField(default=False)
    origem = models.CharField(max_length=10, blank=True)
    data_inclusao = models.DateField(null=True, blank=True)
    data_alteracao = models.DateField(null=True, blank=True)
    data_faturamento = models.DateField(null=True, blank=True)
    cabecalho = models.JSONField(default=dict, blank=True)
    departamentos = models.JSONField(default=list, blank=True)
    email = models.JSONField(default=dict, blank=True)
    info_cadastro = models.JSONField(default=dict, blank=True)
    informacoes_adicionais = models.JSONField(default=dict, blank=True)
    observacoes = models.JSONField(default=dict, blank=True)
    parcelas = models.JSONField(default=list, blank=True)
    servicos_prestados = models.JSONField(default=list, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_previsao", "-codigo_os"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_os"],
                name="os_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_previsao"],
                name="os_omie_emp_prev_idx",
            ),
            models.Index(
                fields=["empresa", "numero_os"],
                name="os_omie_emp_num_idx",
            ),
            models.Index(
                fields=["empresa", "faturada"],
                name="os_omie_emp_fat_idx",
            ),
        ]
        verbose_name = "ordem de servico OMIE"
        verbose_name_plural = "ordens de servico OMIE"

    def __str__(self):
        return self.numero_os or str(self.codigo_os)


class OrdemServicoItemOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="itens_ordem_servico_omie",
    )
    ordem_servico = models.ForeignKey(
        OrdemServicoOmie,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    codigo_item = models.BigIntegerField()
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sequencia = models.PositiveIntegerField(default=0)
    codigo_servico = models.BigIntegerField(null=True, blank=True)
    servico = models.ForeignKey(
        ServicoOmie,
        on_delete=models.SET_NULL,
        related_name="itens_ordem_servico_omie",
        null=True,
        blank=True,
    )
    descricao = models.TextField(blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="itens_ordem_servico_omie",
        null=True,
        blank=True,
    )
    codigo_lc116 = models.CharField(max_length=20, blank=True)
    codigo_servico_municipal = models.CharField(max_length=40, blank=True)
    tributacao_servico = models.CharField(max_length=10, blank=True)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    aliquota_desconto = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
    )
    valor_desconto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_acrescimos = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_outras_retencoes = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    aliquota_iss = models.DecimalField(max_digits=9, decimal_places=4, default=0)
    valor_iss = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    base_iss = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    nao_gerar_financeiro = models.BooleanField(default=False)
    reembolso = models.BooleanField(default=False)
    retem_iss = models.BooleanField(default=False)
    deduz_iss = models.BooleanField(default=False)
    impostos = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ordem_servico_id", "sequencia", "codigo_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_item"],
                name="os_item_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "codigo_servico"],
                name="os_item_emp_serv_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_categoria"],
                name="os_item_emp_cat_idx",
            ),
        ]
        verbose_name = "item de ordem de servico OMIE"
        verbose_name_plural = "itens de ordem de servico OMIE"

    def __str__(self):
        return self.descricao or str(self.codigo_item)


class ContratoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="contratos_omie",
    )
    codigo_contrato = models.BigIntegerField()
    codigo_integracao_contrato = models.CharField(max_length=100, blank=True)
    numero_contrato = models.CharField(max_length=60, blank=True)
    codigo_situacao = models.CharField(max_length=10, blank=True)
    tipo_faturamento = models.CharField(max_length=10, blank=True)
    codigo_cliente = models.BigIntegerField(null=True, blank=True)
    cliente = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="contratos_omie",
        null=True,
        blank=True,
    )
    vigencia_inicial = models.DateField(null=True, blank=True)
    vigencia_final = models.DateField(null=True, blank=True)
    dia_faturamento = models.PositiveIntegerField(default=0)
    valor_total_mes = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="contratos_omie",
        null=True,
        blank=True,
    )
    codigo_categoria_reembolso = models.CharField(max_length=80, blank=True)
    categoria_reembolso = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="contratos_reembolso_omie",
        null=True,
        blank=True,
    )
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        "ContaCorrenteOmie",
        on_delete=models.SET_NULL,
        related_name="contratos_omie",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="contratos_omie",
        null=True,
        blank=True,
    )
    codigo_vendedor = models.BigIntegerField(null=True, blank=True)
    cidade_prestacao = models.CharField(max_length=120, blank=True)
    uso_consumo = models.BooleanField(default=False)
    cabecalho = models.JSONField(default=dict, blank=True)
    departamentos = models.JSONField(default=list, blank=True)
    despesas_reembolsaveis = models.JSONField(default=dict, blank=True)
    email_cliente = models.JSONField(default=dict, blank=True)
    informacoes_adicionais = models.JSONField(default=dict, blank=True)
    observacoes = models.JSONField(default=dict, blank=True)
    venc_textos = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["numero_contrato", "codigo_contrato"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_contrato"],
                name="contrato_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "numero_contrato"],
                name="ctr_omie_emp_num_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_situacao"],
                name="ctr_omie_emp_sit_idx",
            ),
        ]
        verbose_name = "contrato OMIE"
        verbose_name_plural = "contratos OMIE"

    def __str__(self):
        return self.numero_contrato or str(self.codigo_contrato)


class ContratoItemOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="itens_contrato_omie",
    )
    contrato = models.ForeignKey(
        ContratoOmie,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    codigo_item = models.BigIntegerField()
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sequencia = models.PositiveIntegerField(default=0)
    codigo_servico = models.BigIntegerField(null=True, blank=True)
    servico = models.ForeignKey(
        ServicoOmie,
        on_delete=models.SET_NULL,
        related_name="itens_contrato_omie",
        null=True,
        blank=True,
    )
    descricao = models.TextField(blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="itens_contrato_omie",
        null=True,
        blank=True,
    )
    codigo_lc116 = models.CharField(max_length=20, blank=True)
    codigo_servico_municipal = models.CharField(max_length=40, blank=True)
    codigo_nbs = models.CharField(max_length=40, blank=True)
    natureza_operacao = models.CharField(max_length=10, blank=True)
    nao_gerar_financeiro = models.BooleanField(default=False)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_acrescimo = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_deducao = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_desconto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_outras_retencoes = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    aliquota_desconto = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
    )
    aliquota_iss = models.DecimalField(max_digits=9, decimal_places=4, default=0)
    valor_iss = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    ret_iss = models.BooleanField(default=False)
    deduz_iss = models.BooleanField(default=False)
    item_cabecalho = models.JSONField(default=dict, blank=True)
    item_descricao_servico = models.JSONField(default=dict, blank=True)
    item_impostos = models.JSONField(default=dict, blank=True)
    item_lei_transparencia = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["contrato_id", "sequencia", "codigo_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_item"],
                name="contrato_item_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "codigo_servico"],
                name="ctr_item_emp_serv_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_categoria"],
                name="ctr_item_emp_cat_idx",
            ),
        ]
        verbose_name = "item de contrato OMIE"
        verbose_name_plural = "itens de contrato OMIE"

    def __str__(self):
        return self.descricao or str(self.codigo_item)


class PedidoOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="pedidos_omie",
    )
    codigo_pedido = models.BigIntegerField()
    codigo_pedido_integracao = models.CharField(max_length=100, blank=True)
    numero_pedido = models.CharField(max_length=30, blank=True)
    codigo_cliente = models.BigIntegerField(null=True, blank=True)
    cliente = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="pedidos_omie",
        null=True,
        blank=True,
    )
    codigo_empresa_omie = models.BigIntegerField(null=True, blank=True)
    codigo_parcela = models.CharField(max_length=20, blank=True)
    codigo_cenario_impostos = models.CharField(max_length=30, blank=True)
    etapa = models.CharField(max_length=10, blank=True)
    origem_pedido = models.CharField(max_length=40, blank=True)
    data_previsao = models.DateField(null=True, blank=True)
    encerrado = models.BooleanField(default=False)
    bloqueado = models.BooleanField(default=False)
    importado_api = models.BooleanField(default=False)
    quantidade_itens = models.PositiveIntegerField(default=0)
    quantidade_parcelas = models.PositiveIntegerField(default=0)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="pedidos_omie",
        null=True,
        blank=True,
    )
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        "ContaCorrenteOmie",
        on_delete=models.SET_NULL,
        related_name="pedidos_omie",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="pedidos_omie",
        null=True,
        blank=True,
    )
    codigo_vendedor = models.BigIntegerField(null=True, blank=True)
    consumidor_final = models.BooleanField(default=False)
    autorizado = models.BooleanField(default=False)
    cancelado = models.BooleanField(default=False)
    denegado = models.BooleanField(default=False)
    devolvido = models.BooleanField(default=False)
    devolvido_parcial = models.BooleanField(default=False)
    faturado = models.BooleanField(default=False)
    data_inclusao = models.DateField(null=True, blank=True)
    data_alteracao = models.DateField(null=True, blank=True)
    data_faturamento = models.DateField(null=True, blank=True)
    valor_mercadorias = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total_pedido = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_descontos = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_frete = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_seguro = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    cabecalho = models.JSONField(default=dict, blank=True)
    departamentos = models.JSONField(default=list, blank=True)
    exportacao = models.JSONField(default=dict, blank=True)
    frete = models.JSONField(default=dict, blank=True)
    info_cadastro = models.JSONField(default=dict, blank=True)
    informacoes_adicionais = models.JSONField(default=dict, blank=True)
    lista_parcelas = models.JSONField(default=dict, blank=True)
    observacoes = models.JSONField(default=dict, blank=True)
    total_pedido = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_previsao", "-codigo_pedido"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_pedido"],
                name="pedido_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_previsao"],
                name="ped_omie_emp_prev_idx",
            ),
            models.Index(
                fields=["empresa", "numero_pedido"],
                name="ped_omie_emp_num_idx",
            ),
            models.Index(
                fields=["empresa", "faturado"],
                name="ped_omie_emp_fat_idx",
            ),
        ]
        verbose_name = "pedido OMIE"
        verbose_name_plural = "pedidos OMIE"

    def __str__(self):
        return self.numero_pedido or str(self.codigo_pedido)


class PedidoItemOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="itens_pedido_omie",
    )
    pedido = models.ForeignKey(
        PedidoOmie,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    codigo_item = models.BigIntegerField()
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    codigo_item_integracao = models.CharField(max_length=100, blank=True)
    codigo_produto = models.BigIntegerField(null=True, blank=True)
    produto = models.ForeignKey(
        ProdutoOmie,
        on_delete=models.SET_NULL,
        related_name="itens_pedido_omie",
        null=True,
        blank=True,
    )
    codigo_produto_texto = models.CharField(max_length=60, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    unidade = models.CharField(max_length=10, blank=True)
    ncm = models.CharField(max_length=20, blank=True)
    cfop = models.CharField(max_length=10, blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="itens_pedido_omie",
        null=True,
        blank=True,
    )
    codigo_local_estoque = models.BigIntegerField(null=True, blank=True)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_mercadoria = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_desconto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    percentual_desconto = models.DecimalField(
        max_digits=9,
        decimal_places=4,
        default=0,
    )
    nao_gerar_financeiro = models.BooleanField(default=False)
    nao_movimentar_estoque = models.BooleanField(default=False)
    nao_somar_total = models.BooleanField(default=False)
    reservado = models.BooleanField(default=False)
    ide = models.JSONField(default=dict, blank=True)
    produto_dados = models.JSONField(default=dict, blank=True)
    imposto = models.JSONField(default=dict, blank=True)
    inf_adic = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pedido_id", "codigo_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_item"],
                name="pedido_item_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "codigo_produto"],
                name="ped_item_emp_prod_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_categoria"],
                name="ped_item_emp_cat_idx",
            ),
        ]
        verbose_name = "item de pedido OMIE"
        verbose_name_plural = "itens de pedido OMIE"

    def __str__(self):
        return self.descricao or str(self.codigo_item)


class PedidoCompraOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="pedidos_compra_omie",
    )
    codigo_pedido = models.BigIntegerField()
    codigo_pedido_integracao = models.CharField(max_length=100, blank=True)
    numero_pedido = models.CharField(max_length=30, blank=True)
    numero_pedido_fornecedor = models.CharField(max_length=30, blank=True)
    etapa = models.CharField(max_length=10, blank=True)
    contato = models.CharField(max_length=120, blank=True)
    observacao = models.TextField(blank=True)
    observacao_interna = models.TextField(blank=True)
    codigo_fornecedor = models.BigIntegerField(null=True, blank=True)
    fornecedor = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="pedidos_compra_omie",
        null=True,
        blank=True,
    )
    codigo_comprador = models.BigIntegerField(null=True, blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="pedidos_compra_omie",
        null=True,
        blank=True,
    )
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        "ContaCorrenteOmie",
        on_delete=models.SET_NULL,
        related_name="pedidos_compra_omie",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="pedidos_compra_omie",
        null=True,
        blank=True,
    )
    codigo_parcela = models.CharField(max_length=20, blank=True)
    quantidade_parcelas = models.PositiveIntegerField(default=0)
    data_previsao = models.DateField(null=True, blank=True)
    data_inclusao = models.DateField(null=True, blank=True)
    hora_inclusao = models.CharField(max_length=10, blank=True)
    valor_mercadorias = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total_pedido = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_frete = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_seguro = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_outras_despesas = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    cabecalho_consulta = models.JSONField(default=dict, blank=True)
    caracteristicas_consulta = models.JSONField(default=list, blank=True)
    departamentos_consulta = models.JSONField(default=list, blank=True)
    frete_consulta = models.JSONField(default=dict, blank=True)
    parcelas_consulta = models.JSONField(default=list, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_previsao", "-codigo_pedido"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_pedido"],
                name="ped_compra_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_previsao"],
                name="ped_comp_emp_prev_idx",
            ),
            models.Index(
                fields=["empresa", "numero_pedido"],
                name="ped_comp_emp_num_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_fornecedor"],
                name="ped_comp_emp_forn_idx",
            ),
        ]
        verbose_name = "pedido de compra OMIE"
        verbose_name_plural = "pedidos de compra OMIE"

    def __str__(self):
        return self.numero_pedido or str(self.codigo_pedido)


class PedidoCompraItemOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="itens_pedido_compra_omie",
    )
    pedido = models.ForeignKey(
        PedidoCompraOmie,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    codigo_item = models.BigIntegerField()
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    codigo_item_integracao = models.CharField(max_length=100, blank=True)
    codigo_produto = models.BigIntegerField(null=True, blank=True)
    produto = models.ForeignKey(
        ProdutoOmie,
        on_delete=models.SET_NULL,
        related_name="itens_pedido_compra_omie",
        null=True,
        blank=True,
    )
    codigo_produto_texto = models.CharField(max_length=60, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    unidade = models.CharField(max_length=10, blank=True)
    ncm = models.CharField(max_length=20, blank=True)
    ean = models.CharField(max_length=30, blank=True)
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        "CategoriaOmie",
        on_delete=models.SET_NULL,
        related_name="itens_pedido_compra_omie",
        null=True,
        blank=True,
    )
    codigo_local_estoque = models.BigIntegerField(null=True, blank=True)
    quantidade = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    quantidade_recebida = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_mercadoria = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_desconto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_frete = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_despesas = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_seguro = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_icms = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_ipi = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_pis = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_cofins = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_st = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    peso_bruto = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    peso_liquido = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    observacao = models.TextField(blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pedido_id", "codigo_item"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_item"],
                name="ped_comp_item_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "codigo_produto"],
                name="ped_comp_item_emp_prod_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_categoria"],
                name="ped_comp_item_emp_cat_idx",
            ),
        ]
        verbose_name = "item de pedido de compra OMIE"
        verbose_name_plural = "itens de pedido de compra OMIE"

    def __str__(self):
        return self.descricao or str(self.codigo_item)


class RecebimentoNfeOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="recebimentos_nfe_omie",
    )
    codigo_recebimento = models.BigIntegerField()
    chave_nfe = models.CharField(max_length=60, blank=True)
    etapa = models.CharField(max_length=10, blank=True)
    modelo_nfe = models.CharField(max_length=10, blank=True)
    numero_nfe = models.CharField(max_length=30, blank=True)
    serie_nfe = models.CharField(max_length=10, blank=True)
    data_emissao_nfe = models.DateField(null=True, blank=True)
    data_registro = models.DateField(null=True, blank=True)
    codigo_fornecedor = models.BigIntegerField(null=True, blank=True)
    valor_nfe = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    categoria_compra = models.CharField(max_length=80, blank=True)
    codigo_conta = models.BigIntegerField(null=True, blank=True)
    cabec = models.JSONField(default=dict, blank=True)
    info_adicionais = models.JSONField(default=dict, blank=True)
    parcelas = models.JSONField(default=dict, blank=True)
    totais = models.JSONField(default=dict, blank=True)
    transporte = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_registro", "-codigo_recebimento"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_recebimento"],
                name="receb_nfe_omie_empresa_cod_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "chave_nfe"],
                name="receb_nfe_emp_chave_idx",
            ),
            models.Index(
                fields=["empresa", "data_registro"],
                name="receb_nfe_emp_data_idx",
            ),
        ]
        verbose_name = "recebimento de NF-e OMIE"
        verbose_name_plural = "recebimentos de NF-e OMIE"

    def __str__(self):
        return self.numero_nfe or str(self.codigo_recebimento)


class RecebimentoNfeItemOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="itens_recebimento_nfe_omie",
    )
    recebimento = models.ForeignKey(
        RecebimentoNfeOmie,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    codigo_recebimento = models.BigIntegerField()
    sequencia = models.PositiveIntegerField(default=0)
    numero_pedido_compra = models.CharField(max_length=30, blank=True)
    data_recebimento = models.DateField(null=True, blank=True)
    codigo_produto_texto = models.CharField(max_length=60, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    quantidade_nfe = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    quantidade_recebida = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=0,
    )
    preco_unitario = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    valor_total_item = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    item_cabec = models.JSONField(default=dict, blank=True)
    item_ajustes = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recebimento_id", "sequencia"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_recebimento", "sequencia"],
                name="receb_nfe_item_empresa_seq_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "numero_pedido_compra"],
                name="receb_item_emp_ped_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_produto_texto"],
                name="receb_item_emp_prod_idx",
            ),
            models.Index(
                fields=["empresa", "data_recebimento"],
                name="receb_item_emp_data_idx",
            ),
        ]
        verbose_name = "item de recebimento de NF-e OMIE"
        verbose_name_plural = "itens de recebimento de NF-e OMIE"

    def __str__(self):
        return f"{self.numero_pedido_compra} - {self.codigo_produto_texto}"


class CategoriaOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="categorias_omie",
    )
    codigo = models.CharField(max_length=80)
    categoria_superior = models.CharField(max_length=80, blank=True)
    descricao = models.CharField(max_length=100, blank=True)
    descricao_padrao = models.CharField(max_length=80, blank=True)
    codigo_dre = models.CharField(max_length=10, blank=True)
    conta_despesa = models.BooleanField(default=False)
    conta_inativa = models.BooleanField(default=False)
    conta_receita = models.BooleanField(default=False)
    definida_pelo_usuario = models.BooleanField(default=False)
    id_conta_contabil = models.CharField(max_length=30, blank=True)
    nao_exibir = models.BooleanField(default=False)
    natureza = models.TextField(blank=True)
    tag_conta_contabil = models.CharField(max_length=100, blank=True)
    tipo_categoria = models.CharField(max_length=3, blank=True)
    totalizadora = models.BooleanField(default=False)
    transferencia = models.BooleanField(default=False)
    dados_dre = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    conta_dre = models.ForeignKey(
        "ContaDRE",
        on_delete=models.SET_NULL,
        related_name="categorias_omie",
        null=True,
        blank=True,
    )
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="categoria_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "conta_inativa"],
                name="cat_omie_emp_ativo_idx",
            ),
            models.Index(
                fields=["empresa", "totalizadora"],
                name="cat_omie_emp_total_idx",
            ),
        ]
        verbose_name = "categoria OMIE"
        verbose_name_plural = "categorias OMIE"

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"

    @property
    def eh_conta_pai(self):
        return re.fullmatch(r"\d+\.\d{2}", self.codigo) is not None

    @property
    def permite_vinculo_dre(self):
        return (
            re.fullmatch(r"\d+\.\d{2}\.\d{2}", self.codigo) is not None
            and not eh_categoria_transferencia(self)
        )


class TipoContaCorrenteOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="tipos_conta_corrente_omie",
    )
    codigo = models.CharField(max_length=2)
    descricao = models.CharField(max_length=40)
    grupo = models.CharField(max_length=2, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="tipo_cc_omie_empresa_codigo_unico",
            )
        ]
        verbose_name = "tipo de conta corrente OMIE"
        verbose_name_plural = "tipos de conta corrente OMIE"

    def __str__(self):
        return f"{self.codigo} - {self.descricao}"


class ContaCorrenteOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="contas_correntes_omie",
    )
    codigo_omie = models.BigIntegerField()
    codigo_integracao = models.CharField(max_length=20, blank=True)
    tipo_conta = models.ForeignKey(
        TipoContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="contas_correntes",
        null=True,
        blank=True,
    )
    tipo_codigo = models.CharField(max_length=2, blank=True)
    codigo_banco = models.CharField(max_length=3, blank=True)
    descricao = models.CharField(max_length=100, blank=True)
    codigo_agencia = models.CharField(max_length=10, blank=True)
    numero_conta_corrente = models.CharField(max_length=25, blank=True)
    saldo_inicial = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    saldo_data = models.CharField(max_length=10, blank=True)
    saldo_atual = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    saldo_atualizado_em = models.DateTimeField(null=True, blank=True)
    valor_limite = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    nao_fluxo = models.BooleanField(default=False)
    nao_resumo = models.BooleanField(default=False)
    realiza_cobranca = models.BooleanField(default=False)
    emite_boleto = models.BooleanField(default=False)
    emite_pix = models.BooleanField(default=False)
    importado_api = models.BooleanField(default=False)
    bloqueado = models.BooleanField(default=False)
    inativo = models.BooleanField(default=False)
    observacao = models.TextField(blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["descricao", "codigo_omie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_omie"],
                name="conta_cc_omie_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "inativo"],
                name="conta_cc_emp_ativo_idx",
            ),
            models.Index(
                fields=["empresa", "tipo_codigo"],
                name="conta_cc_emp_tipo_idx",
            ),
        ]
        verbose_name = "conta corrente OMIE"
        verbose_name_plural = "contas correntes OMIE"

    def __str__(self):
        return self.descricao or str(self.codigo_omie)


class ContaPagarOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="contas_pagar_omie",
    )
    codigo_lancamento_omie = models.BigIntegerField()
    codigo_lancamento_integracao = models.CharField(max_length=60, blank=True)
    codigo_cliente_fornecedor = models.BigIntegerField(null=True, blank=True)
    fornecedor = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="contas_pagar",
        null=True,
        blank=True,
    )
    id_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        ContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="contas_pagar",
        null=True,
        blank=True,
    )
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        CategoriaOmie,
        on_delete=models.SET_NULL,
        related_name="contas_pagar",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="contas_pagar",
        null=True,
        blank=True,
    )
    data_emissao = models.DateField(null=True, blank=True)
    data_entrada = models.DateField(null=True, blank=True)
    data_previsao = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    valor_documento = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    valor_a_pagar = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status_titulo = models.CharField(max_length=30, blank=True)
    numero_documento = models.CharField(max_length=60, blank=True)
    numero_documento_fiscal = models.CharField(max_length=20, blank=True)
    numero_parcela = models.CharField(max_length=7, blank=True)
    codigo_tipo_documento = models.CharField(max_length=5, blank=True)
    id_origem = models.CharField(max_length=4, blank=True)
    retem_cofins = models.BooleanField(default=False)
    retem_csll = models.BooleanField(default=False)
    retem_inss = models.BooleanField(default=False)
    retem_ir = models.BooleanField(default=False)
    retem_iss = models.BooleanField(default=False)
    retem_pis = models.BooleanField(default=False)
    categorias = models.JSONField(default=list, blank=True)
    distribuicao = models.JSONField(default=list, blank=True)
    cnab_integracao_bancaria = models.JSONField(default=dict, blank=True)
    info = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_vencimento", "codigo_lancamento_omie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_lancamento_omie"],
                name="conta_pagar_empresa_lancamento_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_vencimento"],
                name="conta_pagar_emp_venc_idx",
            ),
            models.Index(
                fields=["empresa", "status_titulo"],
                name="conta_pagar_emp_status_idx",
            ),
            models.Index(
                fields=["empresa", "ativo_omie"],
                name="conta_pagar_emp_ativo_idx",
            ),
        ]
        verbose_name = "conta a pagar OMIE"
        verbose_name_plural = "contas a pagar OMIE"

    def __str__(self):
        return self.numero_documento or str(self.codigo_lancamento_omie)


class ContaReceberOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="contas_receber_omie",
    )
    codigo_lancamento_omie = models.BigIntegerField()
    codigo_lancamento_integracao = models.CharField(max_length=60, blank=True)
    codigo_cliente_fornecedor = models.BigIntegerField(null=True, blank=True)
    cliente = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="contas_receber",
        null=True,
        blank=True,
    )
    id_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        ContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="contas_receber",
        null=True,
        blank=True,
    )
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        CategoriaOmie,
        on_delete=models.SET_NULL,
        related_name="contas_receber",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="contas_receber",
        null=True,
        blank=True,
    )
    data_emissao = models.DateField(null=True, blank=True)
    data_previsao = models.DateField(null=True, blank=True)
    data_registro = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    valor_documento = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    valor_a_receber = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status_titulo = models.CharField(max_length=100, blank=True)
    numero_documento = models.CharField(max_length=60, blank=True)
    numero_documento_fiscal = models.CharField(max_length=20, blank=True)
    numero_parcela = models.CharField(max_length=7, blank=True)
    numero_pedido = models.CharField(max_length=15, blank=True)
    codigo_pedido_omie = models.BigIntegerField(null=True, blank=True)
    codigo_tipo_documento = models.CharField(max_length=5, blank=True)
    chave_nfe = models.CharField(max_length=44, blank=True)
    id_origem = models.CharField(max_length=4, blank=True)
    operacao = models.CharField(max_length=2, blank=True)
    tipo_agrupamento = models.CharField(max_length=1, blank=True)
    retem_cofins = models.BooleanField(default=False)
    retem_csll = models.BooleanField(default=False)
    retem_inss = models.BooleanField(default=False)
    retem_ir = models.BooleanField(default=False)
    retem_iss = models.BooleanField(default=False)
    retem_pis = models.BooleanField(default=False)
    bloqueado = models.BooleanField(default=False)
    bloquear_baixa = models.BooleanField(default=False)
    importado_api = models.BooleanField(default=False)
    boleto = models.JSONField(default=dict, blank=True)
    categorias = models.JSONField(default=list, blank=True)
    distribuicao = models.JSONField(default=list, blank=True)
    info = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_vencimento", "codigo_lancamento_omie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_lancamento_omie"],
                name="conta_receber_empresa_lancamento_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_vencimento"],
                name="conta_receber_emp_venc_idx",
            ),
            models.Index(
                fields=["empresa", "status_titulo"],
                name="conta_receber_emp_status_idx",
            ),
        ]
        verbose_name = "conta a receber OMIE"
        verbose_name_plural = "contas a receber OMIE"

    def __str__(self):
        return self.numero_documento or str(self.codigo_lancamento_omie)


class LancamentoContaCorrenteOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="lancamentos_conta_corrente_omie",
    )
    codigo_lancamento_omie = models.BigIntegerField()
    codigo_lancamento_integracao = models.CharField(max_length=20, blank=True)
    codigo_agrupamento = models.BigIntegerField(null=True, blank=True)
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        ContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos",
        null=True,
        blank=True,
    )
    data_lancamento = models.DateField(null=True, blank=True)
    valor_lancamento = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
    )
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        CategoriaOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos_conta_corrente",
        null=True,
        blank=True,
    )
    tipo_documento = models.CharField(max_length=5, blank=True)
    numero_documento = models.CharField(max_length=60, blank=True)
    codigo_cliente_fornecedor = models.BigIntegerField(null=True, blank=True)
    cliente_fornecedor = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos_conta_corrente",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos_conta_corrente",
        null=True,
        blank=True,
    )
    observacao = models.TextField(blank=True)
    natureza = models.CharField(max_length=1, blank=True)
    origem = models.CharField(max_length=4, blank=True)
    data_conciliacao = models.DateField(null=True, blank=True)
    hora_conciliacao = models.CharField(max_length=8, blank=True)
    usuario_conciliacao = models.CharField(max_length=10, blank=True)
    identificacao_lancamento = models.CharField(max_length=40, blank=True)
    codigo_lancamento_conta_pagar = models.BigIntegerField(null=True, blank=True)
    conta_pagar = models.ForeignKey(
        ContaPagarOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos_conta_corrente",
        null=True,
        blank=True,
    )
    codigo_lancamento_conta_receber = models.BigIntegerField(null=True, blank=True)
    conta_receber = models.ForeignKey(
        ContaReceberOmie,
        on_delete=models.SET_NULL,
        related_name="lancamentos_conta_corrente",
        null=True,
        blank=True,
    )
    codigo_conta_corrente_destino = models.BigIntegerField(null=True, blank=True)
    conta_corrente_destino = models.ForeignKey(
        ContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="transferencias_recebidas",
        null=True,
        blank=True,
    )
    importado_api = models.BooleanField(default=False)
    categorias = models.JSONField(default=list, blank=True)
    departamentos = models.JSONField(default=list, blank=True)
    cabecalho = models.JSONField(default=dict, blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    diversos = models.JSONField(default=dict, blank=True)
    transferencia = models.JSONField(default=dict, blank=True)
    info = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_lancamento", "codigo_lancamento_omie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_lancamento_omie"],
                name="lanc_cc_empresa_codigo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_lancamento"],
                name="lanc_cc_emp_data_idx",
            ),
            models.Index(
                fields=["empresa", "natureza"],
                name="lanc_cc_emp_natureza_idx",
            ),
            models.Index(
                fields=["empresa", "codigo_conta_corrente"],
                name="lanc_cc_emp_conta_idx",
            ),
        ]
        verbose_name = "lançamento de conta corrente OMIE"
        verbose_name_plural = "lançamentos de conta corrente OMIE"

    def __str__(self):
        return self.numero_documento or str(self.codigo_lancamento_omie)


class MovimentoFinanceiroOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="movimentos_financeiros_omie",
    )
    codigo_titulo = models.BigIntegerField()
    codigo_titulo_repeticao = models.BigIntegerField(null=True, blank=True)
    codigo_cliente_fornecedor = models.BigIntegerField(null=True, blank=True)
    cliente_fornecedor = models.ForeignKey(
        CadastroOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    codigo_conta_corrente = models.BigIntegerField(null=True, blank=True)
    conta_corrente = models.ForeignKey(
        ContaCorrenteOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    codigo_categoria = models.CharField(max_length=80, blank=True)
    categoria_principal = models.ForeignKey(
        CategoriaOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    codigo_projeto = models.BigIntegerField(null=True, blank=True)
    projeto = models.ForeignKey(
        ProjetoOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    conta_pagar = models.ForeignKey(
        ContaPagarOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    conta_receber = models.ForeignKey(
        ContaReceberOmie,
        on_delete=models.SET_NULL,
        related_name="movimentos_financeiros",
        null=True,
        blank=True,
    )
    grupo = models.CharField(max_length=30, blank=True)
    natureza = models.CharField(max_length=1, blank=True)
    origem = models.CharField(max_length=4, blank=True)
    status = models.CharField(max_length=30, blank=True)
    liquidado = models.BooleanField(default=False)
    tipo_documento = models.CharField(max_length=5, blank=True)
    numero_titulo = models.CharField(max_length=60, blank=True)
    numero_boleto = models.CharField(max_length=60, blank=True)
    numero_parcela = models.CharField(max_length=10, blank=True)
    cpf_cnpj_cliente = models.CharField(max_length=20, blank=True)
    data_emissao = models.DateField(null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    data_previsao = models.DateField(null=True, blank=True)
    data_registro = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)
    valor_titulo = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    valor_aberto = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    valor_liquido = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    desconto = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    juros = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    multa = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    detalhes = models.JSONField(default=dict, blank=True)
    resumo = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
    ativo_omie = models.BooleanField(default=True)
    ultima_presenca_omie = models.DateTimeField(null=True, blank=True)
    sincronizado_em = models.DateTimeField(auto_now=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_vencimento", "codigo_titulo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo_titulo"],
                name="mov_fin_empresa_titulo_unico",
            )
        ]
        indexes = [
            models.Index(
                fields=["empresa", "data_vencimento"],
                name="mov_fin_emp_venc_idx",
            ),
            models.Index(
                fields=["empresa", "grupo", "natureza"],
                name="mov_fin_emp_grupo_nat_idx",
            ),
            models.Index(
                fields=["empresa", "liquidado"],
                name="mov_fin_emp_liq_idx",
            ),
        ]
        verbose_name = "movimento financeiro OMIE"
        verbose_name_plural = "movimentos financeiros OMIE"

    def __str__(self):
        return self.numero_titulo or str(self.codigo_titulo)


class ContaDRE(models.Model):
    class Sinal(models.TextChoices):
        SOMA = "+", "Somatória (+)"
        SUBTRACAO = "-", "Subtração (-)"
        RESULTADO = "=", "Resultado (=)"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="contas_dre",
    )
    nome = models.CharField(max_length=150)
    conta_pai = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="contas_filhas",
        null=True,
        blank=True,
    )
    sinal = models.CharField(max_length=1, choices=Sinal.choices, default=Sinal.SOMA)
    ordem = models.PositiveIntegerField(default=0)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordem", "nome"]
        indexes = [
            models.Index(
                fields=["empresa", "conta_pai", "ordem"],
                name="conta_dre_arvore_idx",
            )
        ]
        verbose_name = "conta do DRE"
        verbose_name_plural = "contas do DRE"

    @property
    def nivel(self):
        return 2 if self.conta_pai_id else 1

    @property
    def eh_resultado(self):
        return self.sinal == self.Sinal.RESULTADO and self.conta_pai_id is None

    def __str__(self):
        return self.nome


class MetaVendedorComercial(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="metas_vendedores_comerciais",
    )
    vendedor = models.ForeignKey(
        VendedorOmie,
        on_delete=models.CASCADE,
        related_name="metas_comerciais",
    )
    ano = models.PositiveSmallIntegerField(default=ano_atual)
    mes = models.PositiveSmallIntegerField(default=mes_atual)
    valor_mensal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    atualizada_em = models.DateTimeField(auto_now=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["ano", "mes", "vendedor__nome", "vendedor__codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "vendedor", "ano", "mes"],
                name="meta_vendedor_empresa_vendedor_periodo_unico",
            )
        ]
        verbose_name = "meta comercial por vendedor"
        verbose_name_plural = "metas comerciais por vendedor"

    def __str__(self):
        return f"{self.vendedor} - {self.valor_mensal}"


class SincronizacaoOmie(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"
        ERRO = "erro", "Erro"

    class Origem(models.TextChoices):
        MANUAL = "manual", "Manual"
        AGENDADA = "agendada", "Agendada"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="sincronizacoes_omie",
    )
    agendamento = models.ForeignKey(
        "AgendamentoSincronizacaoOmie",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execucoes",
    )
    disparada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sincronizacoes_omie_disparadas",
    )
    origem = models.CharField(
        max_length=20,
        choices=Origem.choices,
        default=Origem.MANUAL,
    )
    recurso = models.CharField(max_length=50, default="clientes")
    agendada_para = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    pagina_atual = models.PositiveIntegerField(default=0)
    total_paginas = models.PositiveIntegerField(default=0)
    registros_processados = models.PositiveIntegerField(default=0)
    total_registros = models.PositiveIntegerField(default=0)
    mensagem = models.CharField(max_length=255, blank=True)
    erro = models.TextField(blank=True)
    iniciada_em = models.DateTimeField(null=True, blank=True)
    finalizada_em = models.DateTimeField(null=True, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criada_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "agendamento", "agendada_para"],
                name="sync_omie_agendamento_horario_unico",
            )
        ]
        verbose_name = "sincronização OMIE"
        verbose_name_plural = "sincronizações OMIE"

    @property
    def percentual(self):
        if self.status == self.Status.CONCLUIDA:
            return 100
        if self.total_paginas:
            return min(99, round((self.pagina_atual / self.total_paginas) * 100))
        return 0


class AgendamentoSincronizacaoOmie(models.Model):
    class Tipo(models.TextChoices):
        DIAS_SEMANA = "dias_semana", "Dia da semana"
        TODO_DIA = "todo_dia", "Todo dia"

    DIAS_SEMANA = (
        (0, "Segunda"),
        (1, "Terca"),
        (2, "Quarta"),
        (3, "Quinta"),
        (4, "Sexta"),
        (5, "Sabado"),
        (6, "Domingo"),
    )

    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name="agendamento_sincronizacao_omie",
    )
    ativo = models.BooleanField(default=False)
    tipo_agendamento = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.TODO_DIA,
    )
    dias_semana = models.JSONField(default=list, blank=True)
    dia_mes = models.PositiveSmallIntegerField(null=True, blank=True)
    horarios = models.JSONField(default=list, blank=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos_sincronizacao_omie_atualizados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["empresa__nome_fantasia"]
        verbose_name = "agendamento de sincronizacao OMIE"
        verbose_name_plural = "agendamentos de sincronizacao OMIE"

    def clean(self):
        horarios = self.horarios or []
        if len(horarios) > 4:
            raise ValidationError({"horarios": "Informe no maximo 4 horarios por dia."})
        if self.ativo and not horarios:
            raise ValidationError({"horarios": "Informe ao menos um horario."})
        if self.tipo_agendamento == self.Tipo.DIAS_SEMANA and not self.dias_semana:
            raise ValidationError({"dias_semana": "Selecione ao menos um dia da semana."})

    @property
    def horarios_texto(self):
        return ", ".join(self.horarios or []) or "Nenhum horario"

    @property
    def dias_semana_texto(self):
        mapa = {str(valor): rotulo for valor, rotulo in self.DIAS_SEMANA}
        return ", ".join(mapa.get(str(dia), str(dia)) for dia in self.dias_semana or [])

    def __str__(self):
        return f"{self.empresa} - {self.get_tipo_agendamento_display()}"
