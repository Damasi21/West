from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compras", "0004_budgetconfiguracaocompra_periodicidades_controle"),
    ]

    operations = [
        migrations.AddField(
            model_name="budgetconfiguracaocompra",
            name="meses_controle",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
