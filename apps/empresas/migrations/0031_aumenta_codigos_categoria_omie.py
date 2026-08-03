from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0030_contapagaromie_ativo_omie_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="servicoomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="ordemservicoomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="ordemservicoitemomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="contratoomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="contratoitemomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="pedidoomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="pedidoitemomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="categoriaomie",
            name="codigo",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="categoriaomie",
            name="categoria_superior",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="categoriaomie",
            name="tag_conta_contabil",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="contapagaromie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="contareceberomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="lancamentocontacorrenteomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="movimentofinanceiroomie",
            name="codigo_categoria",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
