from django.db import migrations


PADRAO = (
    ("5101", "Venda de producao propria"),
    ("5102", "Venda de mercadoria de terceiros"),
    ("5401", "Venda de producao propria com ST - substituto"),
    ("5402", "Venda de producao propria com ST entre substitutos"),
    ("5403", "Venda de mercadoria de terceiros com ST - substituto"),
    ("5405", "Venda de mercadoria de terceiros com ST - substituido"),
    ("6101", "Venda interestadual de producao propria"),
    ("6102", "Venda interestadual de mercadoria de terceiros"),
    ("6401", "Venda interestadual de producao propria com ST - substituto"),
    ("6402", "Venda interestadual de producao propria com ST entre substitutos"),
    ("6403", "Venda interestadual de mercadoria de terceiros com ST - substituto"),
    ("6404", "Venda interestadual de mercadoria com ST retida anteriormente"),
    ("7101", "Exportacao de producao propria"),
    ("7102", "Exportacao de mercadoria de terceiros"),
)


def preencher(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    Cfop = apps.get_model("empresas", "CfopVendaOmie")
    banco = schema_editor.connection.alias
    for empresa_id in Empresa.objects.using(banco).values_list("pk", flat=True).iterator():
        Cfop.objects.using(banco).bulk_create([
            Cfop(empresa_id=empresa_id, codigo=codigo, descricao=descricao)
            for codigo, descricao in PADRAO
        ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("empresas", "0050_cfop_venda")]
    operations = [migrations.RunPython(preencher, migrations.RunPython.noop)]
