from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("replicacao", "0007_alter_cadastrocategoria_status")]

    operations = [
        migrations.AddField(
            model_name="planoreplicacao",
            name="selecao_livre",
            field=models.BooleanField(default=False),
        ),
    ]
