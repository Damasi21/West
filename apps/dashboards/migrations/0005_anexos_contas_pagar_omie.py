import uuid

from django.db import migrations, models


def preencher_tokens(apps, schema_editor):
    Anexo = apps.get_model("dashboards", "AnexoContaPagarLocal")
    for pk in Anexo.objects.using(schema_editor.connection.alias).values_list("pk", flat=True).iterator():
        Anexo.objects.using(schema_editor.connection.alias).filter(pk=pk).update(token_integracao=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0004_envio_contas_omie")]
    operations = [
        migrations.AddField(model_name="anexocontapagarlocal", name="token_integracao", field=models.UUIDField(null=True, editable=False)),
        migrations.RunPython(preencher_tokens, migrations.RunPython.noop),
        migrations.AlterField(model_name="anexocontapagarlocal", name="token_integracao", field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
        migrations.AddField(model_name="anexocontapagarlocal", name="status_omie", field=models.CharField(max_length=20, default="pendente", choices=[("pendente", "Aguardando envio"), ("enviando", "Envio em processamento"), ("incerto", "Aguardando confirmacao OMIE"), ("erro", "Anexo nao enviado"), ("enviado", "Anexo enviado a OMIE")])),
        migrations.AddField(model_name="anexocontapagarlocal", name="codigo_anexo_omie", field=models.BigIntegerField(null=True, blank=True)),
        migrations.AddField(model_name="anexocontapagarlocal", name="enviado_em", field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name="anexocontapagarlocal", name="erro_omie", field=models.TextField(blank=True)),
    ]
