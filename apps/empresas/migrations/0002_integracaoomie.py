from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("empresas", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegracaoOmie",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("app_key", models.CharField(max_length=100, verbose_name="App Key")),
                ("app_secret_criptografado", models.TextField()),
                ("ativa", models.BooleanField(default=True)),
                ("criada_em", models.DateTimeField(auto_now_add=True)),
                ("atualizada_em", models.DateTimeField(auto_now=True)),
                (
                    "empresa",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integracao_omie",
                        to="empresas.empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "integração OMIE",
                "verbose_name_plural": "integrações OMIE",
            },
        ),
    ]
