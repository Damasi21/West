import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Empresa(models.Model):
    nome = models.CharField("razão social", max_length=180)
    nome_fantasia = models.CharField(max_length=120)
    cnpj = models.CharField(max_length=18, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    logo = models.ImageField(upload_to="clientes/", blank=True, null=True)
    ativa = models.BooleanField(default=True)
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


class CategoriaOmie(models.Model):
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="categorias_omie",
    )
    codigo = models.CharField(max_length=20)
    categoria_superior = models.CharField(max_length=20, blank=True)
    descricao = models.CharField(max_length=50, blank=True)
    descricao_padrao = models.CharField(max_length=50, blank=True)
    codigo_dre = models.CharField(max_length=10, blank=True)
    conta_despesa = models.BooleanField(default=False)
    conta_inativa = models.BooleanField(default=False)
    conta_receita = models.BooleanField(default=False)
    definida_pelo_usuario = models.BooleanField(default=False)
    id_conta_contabil = models.CharField(max_length=30, blank=True)
    nao_exibir = models.BooleanField(default=False)
    natureza = models.CharField(max_length=50, blank=True)
    tag_conta_contabil = models.CharField(max_length=20, blank=True)
    tipo_categoria = models.CharField(max_length=3, blank=True)
    totalizadora = models.BooleanField(default=False)
    transferencia = models.BooleanField(default=False)
    dados_dre = models.JSONField(default=dict, blank=True)
    dados_originais = models.JSONField(default=dict, blank=True)
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
        return re.fullmatch(r"\d+\.\d{2}\.\d{2}", self.codigo) is not None


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

    def __str__(self):
        return self.nome


class SincronizacaoOmie(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"
        ERRO = "erro", "Erro"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="sincronizacoes_omie",
    )
    recurso = models.CharField(max_length=50, default="clientes")
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
        verbose_name = "sincronização OMIE"
        verbose_name_plural = "sincronizações OMIE"

    @property
    def percentual(self):
        if self.status == self.Status.CONCLUIDA:
            return 100
        if self.total_paginas:
            return min(99, round((self.pagina_atual / self.total_paginas) * 100))
        return 0
