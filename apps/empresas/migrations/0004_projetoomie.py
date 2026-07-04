from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("empresas", "0003_cadastroomie_sincronizacaoomie"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjetoOmie",
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
                ("codigo", models.BigIntegerField()),
                ("codigo_integracao", models.CharField(blank=True, max_length=20)),
                ("nome", models.CharField(max_length=100)),
                ("inativo", models.BooleanField(default=False)),
                ("info", models.JSONField(blank=True, default=dict)),
                ("dados_originais", models.JSONField(blank=True, default=dict)),
                ("sincronizado_em", models.DateTimeField(auto_now=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="projetos_omie",
                        to="empresas.empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "projeto OMIE",
                "verbose_name_plural": "projetos OMIE",
                "ordering": ["nome"],
                "indexes": [
                    models.Index(
                        fields=["empresa", "inativo"],
                        name="proj_omie_emp_ativo_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("empresa", "codigo"),
                        name="projeto_omie_empresa_codigo_unico",
                    )
                ],
            },
        ),
    ]
