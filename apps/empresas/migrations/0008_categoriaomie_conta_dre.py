from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0007_categoriaomie"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoriaomie",
            name="conta_dre",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="categorias_omie",
                to="empresas.contadre",
            ),
        ),
    ]
