from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("empresas", "0002_integracaoomie"),
    ]

    operations = [
        migrations.CreateModel(
            name="SincronizacaoOmie",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recurso", models.CharField(default="clientes", max_length=50)),
                ("status", models.CharField(choices=[("pendente", "Pendente"), ("em_andamento", "Em andamento"), ("concluida", "Concluída"), ("erro", "Erro")], default="pendente", max_length=20)),
                ("pagina_atual", models.PositiveIntegerField(default=0)),
                ("total_paginas", models.PositiveIntegerField(default=0)),
                ("registros_processados", models.PositiveIntegerField(default=0)),
                ("total_registros", models.PositiveIntegerField(default=0)),
                ("mensagem", models.CharField(blank=True, max_length=255)),
                ("erro", models.TextField(blank=True)),
                ("iniciada_em", models.DateTimeField(blank=True, null=True)),
                ("finalizada_em", models.DateTimeField(blank=True, null=True)),
                ("criada_em", models.DateTimeField(auto_now_add=True)),
                ("atualizada_em", models.DateTimeField(auto_now=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sincronizacoes_omie", to="empresas.empresa")),
            ],
            options={
                "verbose_name": "sincronização OMIE",
                "verbose_name_plural": "sincronizações OMIE",
                "ordering": ["-criada_em"],
            },
        ),
        migrations.CreateModel(
            name="CadastroOmie",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codigo_cliente_omie", models.BigIntegerField()),
                ("codigo_cliente_integracao", models.CharField(blank=True, max_length=100)),
                ("tipo", models.CharField(choices=[("cliente", "Cliente"), ("fornecedor", "Fornecedor"), ("ambos", "Cliente e fornecedor"), ("outro", "Outro")], default="outro", max_length=20)),
                ("razao_social", models.CharField(blank=True, max_length=255)),
                ("nome_fantasia", models.CharField(blank=True, max_length=255)),
                ("cnpj_cpf", models.CharField(blank=True, db_index=True, max_length=30)),
                ("pessoa_fisica", models.BooleanField(default=False)),
                ("inativo", models.BooleanField(default=False)),
                ("bloquear_faturamento", models.BooleanField(default=False)),
                ("exterior", models.BooleanField(default=False)),
                ("enviar_anexos", models.BooleanField(default=False)),
                ("inscricao_estadual", models.CharField(blank=True, max_length=50)),
                ("inscricao_municipal", models.CharField(blank=True, max_length=50)),
                ("endereco", models.CharField(blank=True, max_length=255)),
                ("endereco_numero", models.CharField(blank=True, max_length=60)),
                ("complemento", models.CharField(blank=True, max_length=255)),
                ("bairro", models.CharField(blank=True, max_length=120)),
                ("cidade", models.CharField(blank=True, max_length=120)),
                ("cidade_ibge", models.CharField(blank=True, max_length=30)),
                ("estado", models.CharField(blank=True, max_length=10)),
                ("cep", models.CharField(blank=True, max_length=20)),
                ("codigo_pais", models.CharField(blank=True, max_length=20)),
                ("dados_bancarios", models.JSONField(blank=True, default=dict)),
                ("endereco_entrega", models.JSONField(blank=True, default=dict)),
                ("recomendacoes", models.JSONField(blank=True, default=dict)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("info", models.JSONField(blank=True, default=dict)),
                ("dados_originais", models.JSONField(blank=True, default=dict)),
                ("sincronizado_em", models.DateTimeField(auto_now=True)),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cadastros_omie", to="empresas.empresa")),
            ],
            options={
                "verbose_name": "cadastro OMIE",
                "verbose_name_plural": "cadastros OMIE",
                "ordering": ["razao_social", "nome_fantasia"],
                "indexes": [models.Index(fields=["empresa", "tipo"], name="cad_omie_emp_tipo_idx"), models.Index(fields=["empresa", "inativo"], name="cad_omie_emp_ativo_idx")],
                "constraints": [models.UniqueConstraint(fields=("empresa", "codigo_cliente_omie"), name="cadastro_omie_empresa_codigo_unico")],
            },
        ),
    ]
