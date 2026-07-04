from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0006_contadre"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoriaOmie",
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
                ("codigo", models.CharField(max_length=20)),
                ("categoria_superior", models.CharField(blank=True, max_length=20)),
                ("descricao", models.CharField(blank=True, max_length=50)),
                ("descricao_padrao", models.CharField(blank=True, max_length=50)),
                ("codigo_dre", models.CharField(blank=True, max_length=10)),
                ("conta_despesa", models.BooleanField(default=False)),
                ("conta_inativa", models.BooleanField(default=False)),
                ("conta_receita", models.BooleanField(default=False)),
                ("definida_pelo_usuario", models.BooleanField(default=False)),
                ("id_conta_contabil", models.CharField(blank=True, max_length=30)),
                ("nao_exibir", models.BooleanField(default=False)),
                ("natureza", models.CharField(blank=True, max_length=50)),
                ("tag_conta_contabil", models.CharField(blank=True, max_length=20)),
                ("tipo_categoria", models.CharField(blank=True, max_length=3)),
                ("totalizadora", models.BooleanField(default=False)),
                ("transferencia", models.BooleanField(default=False)),
                ("dados_dre", models.JSONField(blank=True, default=dict)),
                ("dados_originais", models.JSONField(blank=True, default=dict)),
                ("sincronizado_em", models.DateTimeField(auto_now=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="categorias_omie",
                        to="empresas.empresa",
                    ),
                ),
            ],
            options={
                "verbose_name": "categoria OMIE",
                "verbose_name_plural": "categorias OMIE",
                "ordering": ["codigo"],
                "indexes": [
                    models.Index(
                        fields=["empresa", "conta_inativa"],
                        name="cat_omie_emp_ativo_idx",
                    ),
                    models.Index(
                        fields=["empresa", "totalizadora"],
                        name="cat_omie_emp_total_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("empresa", "codigo"),
                        name="categoria_omie_empresa_codigo_unico",
                    )
                ],
            },
        ),
    ]
