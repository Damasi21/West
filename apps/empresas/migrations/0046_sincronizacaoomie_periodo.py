from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0045_empresa_trial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sincronizacaoomie",
            name="periodo",
            field=models.CharField(
                choices=[
                    ("tudo", "Todos os dados"),
                    ("ano_atual", "Ano atual"),
                    ("mes_atual", "Mes atual"),
                    ("ultimos_30_dias", "Ultimos 30 dias"),
                ],
                default="tudo",
                max_length=30,
            ),
        ),
    ]
