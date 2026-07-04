from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("empresas", "0005_departamentoomie"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContaDRE",
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
                ("nome", models.CharField(max_length=150)),
                (
                    "sinal",
                    models.CharField(
                        choices=[
                            ("+", "Somatória (+)"),
                            ("-", "Subtração (-)"),
                            ("=", "Resultado (=)"),
                        ],
                        default="+",
                        max_length=1,
                    ),
                ),
                ("ordem", models.PositiveIntegerField(default=0)),
                ("criada_em", models.DateTimeField(auto_now_add=True)),
                ("atualizada_em", models.DateTimeField(auto_now=True)),
                (
                    "conta_pai",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contas_filhas",
                        to="empresas.contadre",
                    ),
                ),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contas_dre",
                        to="empresas.empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "conta do DRE",
                "verbose_name_plural": "contas do DRE",
                "ordering": ["ordem", "nome"],
                "indexes": [
                    models.Index(
                        fields=["empresa", "conta_pai", "ordem"],
                        name="conta_dre_arvore_idx",
                    )
                ],
            },
        ),
    ]
