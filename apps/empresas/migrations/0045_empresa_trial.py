from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0044_produtofornecedoromie"),
    ]

    operations = [
        migrations.AddField(
            model_name="empresa",
            name="tipo_conta",
            field=models.CharField(
                choices=[("cliente", "Cliente"), ("trial", "Trial")],
                db_index=True,
                default="cliente",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="empresa",
            name="status_conta",
            field=models.CharField(
                choices=[
                    ("ativa", "Ativa"),
                    ("expirada", "Expirada"),
                    ("cancelada", "Cancelada"),
                ],
                db_index=True,
                default="ativa",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_inicio",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_expira_em",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_convertido_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_cancelado_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_responsavel_nome",
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_responsavel_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="empresa",
            name="trial_responsavel_telefone",
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
