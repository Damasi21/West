from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("empresas", "0004_projetoomie"),
    ]

    operations = [
        migrations.CreateModel(
            name="DepartamentoOmie",
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
                ("codigo", models.CharField(max_length=40)),
                ("descricao", models.CharField(max_length=100)),
                ("estrutura", models.CharField(blank=True, max_length=40)),
                ("inativo", models.BooleanField(default=False)),
                ("nivel_totalizador", models.BooleanField(default=False)),
                ("dados_originais", models.JSONField(blank=True, default=dict)),
                ("sincronizado_em", models.DateTimeField(auto_now=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="departamentos_omie",
                        to="empresas.empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "departamento OMIE",
                "verbose_name_plural": "departamentos OMIE",
                "ordering": ["estrutura", "descricao"],
                "indexes": [
                    models.Index(
                        fields=["empresa", "inativo"],
                        name="dep_omie_emp_ativo_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("empresa", "codigo"),
                        name="departamento_omie_empresa_codigo_unico",
                    )
                ],
            },
        ),
    ]
