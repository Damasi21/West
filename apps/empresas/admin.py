from django.contrib import admin

from .models import (
    CadastroOmie,
    CategoriaOmie,
    ContaDRE,
    DepartamentoOmie,
    Empresa,
    EmpresaUsuario,
    IntegracaoOmie,
    ProjetoOmie,
    SincronizacaoOmie,
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
