from django.contrib import admin

from .models import (
    CadastroOmie,
    CategoriaOmie,
    ContaCorrenteOmie,
    ContaPagarOmie,
    ContaReceberOmie,
    ContaDRE,
    ContratoItemOmie,
    ContratoOmie,
    DepartamentoOmie,
    Empresa,
    EmpresaUsuario,
    IntegracaoOmie,
    LancamentoContaCorrenteOmie,
    OrdemServicoItemOmie,
    OrdemServicoOmie,
    PedidoItemOmie,
    PedidoOmie,
    ProdutoOmie,
    ProjetoOmie,
    ServicoOmie,
    SincronizacaoOmie,
    TipoContaCorrenteOmie,
    VendedorOmie,
)


class EmpresaUsuarioInline(admin.TabularInline):
    model = EmpresaUsuario
    extra = 1


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nome_fantasia", "cnpj", "ativa", "atualizada_em")
    list_filter = ("ativa",)
    search_fields = ("nome_fantasia", "nome", "cnpj")
    prepopulated_fields = {"slug": ("nome_fantasia",)}
    inlines = [EmpresaUsuarioInline]


@admin.register(EmpresaUsuario)
class EmpresaUsuarioAdmin(admin.ModelAdmin):
    list_display = ("usuario", "empresa", "papel", "ativo")
    list_filter = ("papel", "ativo")
    search_fields = ("usuario__username", "empresa__nome_fantasia")


@admin.register(IntegracaoOmie)
class IntegracaoOmieAdmin(admin.ModelAdmin):
    list_display = ("empresa", "app_key", "ativa", "atualizada_em")
    list_filter = ("ativa",)
    search_fields = ("empresa__nome_fantasia", "app_key")
    readonly_fields = ("app_secret_criptografado", "criada_em", "atualizada_em")


@admin.register(CadastroOmie)
class CadastroOmieAdmin(admin.ModelAdmin):
    list_display = (
        "razao_social",
        "cnpj_cpf",
        "tipo",
        "empresa",
        "inativo",
        "sincronizado_em",
    )
    list_filter = ("empresa", "tipo", "inativo")
    search_fields = (
        "razao_social",
        "nome_fantasia",
        "cnpj_cpf",
        "codigo_cliente_omie",
    )
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(ProjetoOmie)
class ProjetoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "codigo",
        "codigo_integracao",
        "empresa",
        "inativo",
        "sincronizado_em",
    )
    list_filter = ("empresa", "inativo")
    search_fields = ("nome", "codigo", "codigo_integracao")
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(DepartamentoOmie)
class DepartamentoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "codigo",
        "estrutura",
        "empresa",
        "inativo",
        "nivel_totalizador",
    )
    list_filter = ("empresa", "inativo", "nivel_totalizador")
    search_fields = ("descricao", "codigo", "estrutura")
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(VendedorOmie)
class VendedorOmieAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "codigo",
        "email",
        "comissao",
        "fatura_pedido",
        "visualiza_pedido",
        "empresa",
        "inativo",
    )
    list_filter = ("empresa", "inativo", "fatura_pedido", "visualiza_pedido")
    search_fields = ("nome", "email", "codigo", "codigo_integracao")
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(ProdutoOmie)
class ProdutoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "codigo",
        "unidade",
        "valor_unitario",
        "quantidade_estoque",
        "empresa",
        "inativo",
    )
    list_filter = ("empresa", "inativo", "bloqueado", "importado_api", "unidade")
    search_fields = (
        "descricao",
        "codigo",
        "codigo_produto",
        "codigo_produto_integracao",
        "ncm",
        "ean",
    )
    readonly_fields = (
        "info",
        "recomendacoes_fiscais",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(ServicoOmie)
class ServicoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "codigo",
        "preco_unitario",
        "aliquota_iss",
        "empresa",
        "inativo",
    )
    list_filter = ("empresa", "inativo", "importado_api", "ret_iss")
    search_fields = (
        "descricao",
        "descricao_completa",
        "codigo",
        "codigo_servico",
        "codigo_integracao_servico",
        "codigo_lc116",
    )
    readonly_fields = (
        "cabecalho",
        "descricao_dados",
        "impostos",
        "info",
        "int_listar",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


class OrdemServicoItemOmieInline(admin.TabularInline):
    model = OrdemServicoItemOmie
    extra = 0
    fields = (
        "codigo_item",
        "sequencia",
        "descricao",
        "quantidade",
        "valor_unitario",
        "reembolso",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OrdemServicoOmie)
class OrdemServicoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "numero_os",
        "codigo_os",
        "cliente",
        "data_previsao",
        "valor_total",
        "faturada",
        "cancelada",
        "empresa",
    )
    list_filter = ("empresa", "faturada", "cancelada", "etapa", "data_previsao")
    search_fields = (
        "numero_os",
        "codigo_os",
        "codigo_integracao_os",
        "cliente__razao_social",
        "cliente__nome_fantasia",
    )
    readonly_fields = (
        "cabecalho",
        "departamentos",
        "email",
        "info_cadastro",
        "informacoes_adicionais",
        "observacoes",
        "parcelas",
        "servicos_prestados",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )
    inlines = [OrdemServicoItemOmieInline]


@admin.register(OrdemServicoItemOmie)
class OrdemServicoItemOmieAdmin(admin.ModelAdmin):
    list_display = (
        "ordem_servico",
        "codigo_item",
        "codigo_servico",
        "descricao",
        "quantidade",
        "valor_unitario",
        "reembolso",
        "empresa",
    )
    list_filter = ("empresa", "reembolso", "nao_gerar_financeiro")
    search_fields = (
        "ordem_servico__numero_os",
        "codigo_item",
        "codigo_servico",
        "descricao",
    )
    readonly_fields = (
        "impostos",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


class ContratoItemOmieInline(admin.TabularInline):
    model = ContratoItemOmie
    extra = 0
    fields = (
        "codigo_item",
        "sequencia",
        "descricao",
        "quantidade",
        "valor_unitario",
        "valor_total",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ContratoOmie)
class ContratoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "numero_contrato",
        "codigo_contrato",
        "cliente",
        "vigencia_inicial",
        "vigencia_final",
        "valor_total_mes",
        "codigo_situacao",
        "empresa",
    )
    list_filter = ("empresa", "codigo_situacao", "tipo_faturamento")
    search_fields = (
        "numero_contrato",
        "codigo_contrato",
        "codigo_integracao_contrato",
        "cliente__razao_social",
        "cliente__nome_fantasia",
    )
    readonly_fields = (
        "cabecalho",
        "departamentos",
        "despesas_reembolsaveis",
        "email_cliente",
        "informacoes_adicionais",
        "observacoes",
        "venc_textos",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )
    inlines = [ContratoItemOmieInline]


@admin.register(ContratoItemOmie)
class ContratoItemOmieAdmin(admin.ModelAdmin):
    list_display = (
        "contrato",
        "codigo_item",
        "codigo_servico",
        "descricao",
        "quantidade",
        "valor_total",
        "empresa",
    )
    list_filter = ("empresa", "nao_gerar_financeiro")
    search_fields = (
        "contrato__numero_contrato",
        "codigo_item",
        "codigo_servico",
        "descricao",
    )
    readonly_fields = (
        "item_cabecalho",
        "item_descricao_servico",
        "item_impostos",
        "item_lei_transparencia",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


class PedidoItemOmieInline(admin.TabularInline):
    model = PedidoItemOmie
    extra = 0
    fields = (
        "codigo_item",
        "codigo_produto_texto",
        "descricao",
        "quantidade",
        "valor_unitario",
        "valor_total",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PedidoOmie)
class PedidoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "numero_pedido",
        "codigo_pedido",
        "cliente",
        "data_previsao",
        "valor_total_pedido",
        "faturado",
        "cancelado",
        "empresa",
    )
    list_filter = ("empresa", "faturado", "cancelado", "etapa", "data_previsao")
    search_fields = (
        "numero_pedido",
        "codigo_pedido",
        "codigo_pedido_integracao",
        "cliente__razao_social",
        "cliente__nome_fantasia",
    )
    readonly_fields = (
        "cabecalho",
        "departamentos",
        "exportacao",
        "frete",
        "info_cadastro",
        "informacoes_adicionais",
        "lista_parcelas",
        "observacoes",
        "total_pedido",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )
    inlines = [PedidoItemOmieInline]


@admin.register(PedidoItemOmie)
class PedidoItemOmieAdmin(admin.ModelAdmin):
    list_display = (
        "pedido",
        "codigo_item",
        "codigo_produto_texto",
        "descricao",
        "quantidade",
        "valor_total",
        "empresa",
    )
    list_filter = ("empresa", "unidade", "cfop")
    search_fields = (
        "pedido__numero_pedido",
        "codigo_item",
        "codigo_produto_texto",
        "descricao",
    )
    readonly_fields = (
        "ide",
        "produto_dados",
        "imposto",
        "inf_adic",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(CategoriaOmie)
class CategoriaOmieAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "descricao",
        "empresa",
        "totalizadora",
        "conta_inativa",
        "codigo_dre",
        "conta_dre",
    )
    list_filter = (
        "empresa",
        "conta_inativa",
        "totalizadora",
        "conta_receita",
        "conta_despesa",
    )
    search_fields = (
        "codigo",
        "descricao",
        "descricao_padrao",
        "codigo_dre",
        "conta_dre__nome",
    )
    readonly_fields = (
        "dados_dre",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(TipoContaCorrenteOmie)
class TipoContaCorrenteOmieAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descricao", "grupo", "empresa", "sincronizado_em")
    list_filter = ("empresa", "grupo")
    search_fields = ("codigo", "descricao", "grupo")
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(ContaCorrenteOmie)
class ContaCorrenteOmieAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "codigo_omie",
        "tipo_codigo",
        "codigo_banco",
        "empresa",
        "inativo",
    )
    list_filter = ("empresa", "tipo_codigo", "inativo", "bloqueado")
    search_fields = (
        "descricao",
        "codigo_omie",
        "codigo_integracao",
        "codigo_agencia",
        "numero_conta_corrente",
    )
    readonly_fields = ("dados_originais", "sincronizado_em", "criado_em")


@admin.register(ContaPagarOmie)
class ContaPagarOmieAdmin(admin.ModelAdmin):
    list_display = (
        "numero_documento",
        "codigo_lancamento_omie",
        "fornecedor",
        "data_vencimento",
        "valor_documento",
        "status_titulo",
        "empresa",
    )
    list_filter = ("empresa", "status_titulo", "data_vencimento")
    search_fields = (
        "numero_documento",
        "numero_documento_fiscal",
        "codigo_lancamento_omie",
        "codigo_lancamento_integracao",
        "fornecedor__razao_social",
        "fornecedor__nome_fantasia",
    )
    readonly_fields = (
        "categorias",
        "distribuicao",
        "cnab_integracao_bancaria",
        "info",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(ContaReceberOmie)
class ContaReceberOmieAdmin(admin.ModelAdmin):
    list_display = (
        "numero_documento",
        "codigo_lancamento_omie",
        "cliente",
        "data_vencimento",
        "valor_documento",
        "status_titulo",
        "empresa",
    )
    list_filter = ("empresa", "status_titulo", "data_vencimento")
    search_fields = (
        "numero_documento",
        "numero_documento_fiscal",
        "codigo_lancamento_omie",
        "codigo_lancamento_integracao",
        "cliente__razao_social",
        "cliente__nome_fantasia",
    )
    readonly_fields = (
        "boleto",
        "categorias",
        "distribuicao",
        "info",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(LancamentoContaCorrenteOmie)
class LancamentoContaCorrenteOmieAdmin(admin.ModelAdmin):
    list_display = (
        "codigo_lancamento_omie",
        "data_lancamento",
        "conta_corrente",
        "valor_lancamento",
        "natureza",
        "origem",
        "empresa",
    )
    list_filter = ("empresa", "natureza", "origem", "data_lancamento")
    search_fields = (
        "codigo_lancamento_omie",
        "codigo_lancamento_integracao",
        "numero_documento",
        "observacao",
        "cliente_fornecedor__razao_social",
        "cliente_fornecedor__nome_fantasia",
    )
    readonly_fields = (
        "categorias",
        "departamentos",
        "cabecalho",
        "detalhes",
        "diversos",
        "transferencia",
        "info",
        "dados_originais",
        "sincronizado_em",
        "criado_em",
    )


@admin.register(ContaDRE)
class ContaDREAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "conta_pai", "sinal", "ordem")
    list_filter = ("empresa", "sinal")
    search_fields = ("nome",)
    ordering = ("empresa", "conta_pai_id", "ordem")


@admin.register(SincronizacaoOmie)
class SincronizacaoOmieAdmin(admin.ModelAdmin):
    list_display = (
        "empresa",
        "recurso",
        "status",
        "registros_processados",
        "total_registros",
        "criada_em",
    )
    list_filter = ("empresa", "status", "recurso")
    readonly_fields = (
        "criada_em",
        "atualizada_em",
        "iniciada_em",
        "finalizada_em",
    )
