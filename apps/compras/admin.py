from django.contrib import admin

from .models import BudgetConfiguracaoCompra, BudgetLimiteCompra


@admin.register(BudgetConfiguracaoCompra)
class BudgetConfiguracaoCompraAdmin(admin.ModelAdmin):
    list_display = ("empresa", "controles", "atualizado_em")
    list_filter = ("tipo_controle",)
    search_fields = ("empresa__nome_fantasia", "empresa__nome")

    @admin.display(description="controles")
    def controles(self, obj):
        return ", ".join(obj.rotulos_tipos())


@admin.register(BudgetLimiteCompra)
class BudgetLimiteCompraAdmin(admin.ModelAdmin):
    list_display = (
        "empresa",
        "tipo_controle",
        "referencia_nome",
        "mes",
        "estoque_minimo",
        "limite_compra",
    )
    list_filter = ("tipo_controle", "mes")
    search_fields = ("empresa__nome_fantasia", "referencia_nome", "referencia_codigo")
