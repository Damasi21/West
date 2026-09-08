from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0043_movimentoestoqueomie"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProdutoFornecedorOmie",
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
                ("codigo_produto", models.BigIntegerField()),
                ("codigo_produto_integracao", models.CharField(blank=True, max_length=100)),
                ("codigo_produto_fornecedor", models.CharField(blank=True, max_length=60)),
                ("descricao_produto", models.CharField(blank=True, max_length=255)),
                ("codigo_fornecedor", models.BigIntegerField()),
                ("codigo_fornecedor_integracao", models.CharField(blank=True, max_length=100)),
                ("cnpj_cpf", models.CharField(blank=True, max_length=20)),
                ("razao_social", models.CharField(blank=True, max_length=120)),
                ("nome_fantasia", models.CharField(blank=True, max_length=120)),
                ("dados_originais", models.JSONField(blank=True, default=dict)),
                ("ativo_omie", models.BooleanField(default=True)),
                ("ultima_presenca_omie", models.DateTimeField(blank=True, null=True)),
                ("sincronizado_em", models.DateTimeField(auto_now=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "empresa",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="produtos_fornecedores_omie",
                        to="empresas.empresa",
                    ),
                ),
                (
                    "produto",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="fornecedores_omie",
                        to="empresas.produtoomie",
                    ),
                ),
            ],
            options={
                "verbose_name": "produto por fornecedor OMIE",
                "verbose_name_plural": "produtos por fornecedor OMIE",
                "ordering": ["nome_fantasia", "razao_social", "codigo_produto_fornecedor"],
            },
        ),
        migrations.AddConstraint(
            model_name="produtofornecedoromie",
            constraint=models.UniqueConstraint(
                fields=("empresa", "codigo_fornecedor", "codigo_produto"),
                name="prod_forn_omie_emp_forn_prod_unico",
            ),
        ),
        migrations.AddIndex(
            model_name="produtofornecedoromie",
            index=models.Index(fields=["empresa", "codigo_produto"], name="prod_forn_emp_prod_idx"),
        ),
        migrations.AddIndex(
            model_name="produtofornecedoromie",
            index=models.Index(fields=["empresa", "codigo_fornecedor"], name="prod_forn_emp_forn_idx"),
        ),
    ]
