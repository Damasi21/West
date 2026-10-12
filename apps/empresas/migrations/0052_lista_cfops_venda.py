from django.db import migrations


PADRAO = (
    ("5101", "Venda interna - producao propria"),
    ("5102", "Venda interna - mercadoria de terceiros"),
    ("5103", "Venda interna - producao propria fora do estabelecimento"),
    ("5104", "Venda interna - mercadoria de terceiros fora do estabelecimento"),
    ("5105", "Venda interna - producao propria sem transito pelo estabelecimento"),
    ("5106", "Venda interna - mercadoria de terceiros sem transito pelo estabelecimento"),
    ("5109", "Venda interna - producao propria para ZFM ou area de livre comercio"),
    ("5110", "Venda interna - mercadoria de terceiros para ZFM ou area de livre comercio"),
    ("5111", "Venda interna - producao propria em consignacao industrial"),
    ("5112", "Venda interna - mercadoria de terceiros em consignacao industrial"),
    ("5113", "Venda interna - producao propria remetida em consignacao mercantil"),
    ("5114", "Venda interna - mercadoria de terceiros remetida em consignacao mercantil"),
    ("5115", "Venda interna - mercadoria de terceiros recebida em consignacao mercantil"),
    ("5116", "Venda interna - producao propria de encomenda para entrega futura"),
    ("5117", "Venda interna - mercadoria de terceiros de encomenda para entrega futura"),
    ("5118", "Venda interna - producao propria entregue por conta e ordem"),
    ("5119", "Venda interna - mercadoria de terceiros entregue por conta e ordem"),
    ("5120", "Venda interna - mercadoria de terceiros entregue pelo vendedor remetente"),
    ("5122", "Venda interna - producao propria para industrializacao por conta e ordem"),
    ("5123", "Venda interna - mercadoria de terceiros para industrializacao por conta e ordem"),
    ("5401", "Venda interna - producao propria com ST - substituto"),
    ("5402", "Venda interna - producao propria com ST entre substitutos"),
    ("5403", "Venda interna - mercadoria de terceiros com ST - substituto"),
    ("5405", "Venda interna - mercadoria de terceiros com ST - substituido"),
    ("5651", "Venda interna - combustivel proprio para industrializacao"),
    ("5652", "Venda interna - combustivel proprio para comercializacao"),
    ("5653", "Venda interna - combustivel proprio para consumidor final"),
    ("5654", "Venda interna - combustivel de terceiros para industrializacao"),
    ("5655", "Venda interna - combustivel de terceiros para comercializacao"),
    ("5656", "Venda interna - combustivel de terceiros para consumidor final"),
    ("6101", "Venda interestadual - producao propria"),
    ("6102", "Venda interestadual - mercadoria de terceiros"),
    ("6103", "Venda interestadual - producao propria fora do estabelecimento"),
    ("6104", "Venda interestadual - mercadoria de terceiros fora do estabelecimento"),
    ("6105", "Venda interestadual - producao propria sem transito pelo estabelecimento"),
    ("6106", "Venda interestadual - mercadoria de terceiros sem transito pelo estabelecimento"),
    ("6107", "Venda interestadual - producao propria para nao contribuinte"),
    ("6108", "Venda interestadual - mercadoria de terceiros para nao contribuinte"),
    ("6109", "Venda interestadual - producao propria para ZFM ou area de livre comercio"),
    ("6110", "Venda interestadual - mercadoria de terceiros para ZFM ou area de livre comercio"),
    ("6111", "Venda interestadual - producao propria em consignacao industrial"),
    ("6112", "Venda interestadual - mercadoria de terceiros em consignacao industrial"),
    ("6113", "Venda interestadual - producao propria remetida em consignacao mercantil"),
    ("6114", "Venda interestadual - mercadoria de terceiros remetida em consignacao mercantil"),
    ("6115", "Venda interestadual - mercadoria de terceiros recebida em consignacao mercantil"),
    ("6116", "Venda interestadual - producao propria de encomenda para entrega futura"),
    ("6117", "Venda interestadual - mercadoria de terceiros de encomenda para entrega futura"),
    ("6118", "Venda interestadual - producao propria entregue por conta e ordem"),
    ("6119", "Venda interestadual - mercadoria de terceiros entregue por conta e ordem"),
    ("6120", "Venda interestadual - mercadoria de terceiros entregue pelo vendedor remetente"),
    ("6122", "Venda interestadual - producao propria para industrializacao por conta e ordem"),
    ("6123", "Venda interestadual - mercadoria de terceiros para industrializacao por conta e ordem"),
    ("6401", "Venda interestadual - producao propria com ST - substituto"),
    ("6402", "Venda interestadual - producao propria com ST entre substitutos"),
    ("6403", "Venda interestadual - mercadoria de terceiros com ST - substituto"),
    ("6404", "Venda interestadual - mercadoria com ST retida anteriormente"),
    ("6651", "Venda interestadual - combustivel proprio para industrializacao"),
    ("6652", "Venda interestadual - combustivel proprio para comercializacao"),
    ("6653", "Venda interestadual - combustivel proprio para consumidor final"),
    ("6654", "Venda interestadual - combustivel de terceiros para industrializacao"),
    ("6655", "Venda interestadual - combustivel de terceiros para comercializacao"),
    ("6656", "Venda interestadual - combustivel de terceiros para consumidor final"),
)


def atualizar_lista(apps, schema_editor):
    Empresa = apps.get_model("empresas", "Empresa")
    Cfop = apps.get_model("empresas", "CfopVendaOmie")
    banco = schema_editor.connection.alias
    # Remove only the untouched export defaults from the initial list.
    Cfop.objects.using(banco).filter(codigo="7101", descricao="Exportacao de producao propria").delete()
    Cfop.objects.using(banco).filter(codigo="7102", descricao="Exportacao de mercadoria de terceiros").delete()
    for empresa_id in Empresa.objects.using(banco).values_list("pk", flat=True).iterator():
        Cfop.objects.using(banco).bulk_create([
            Cfop(empresa_id=empresa_id, codigo=codigo, descricao=descricao)
            for codigo, descricao in PADRAO
        ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("empresas", "0051_cfops_venda_padrao")]
    operations = [migrations.RunPython(atualizar_lista, migrations.RunPython.noop)]
