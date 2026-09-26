from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("empresas", "0046_sincronizacaoomie_periodo"),
    ]

    operations = [
        migrations.AddField(
            model_name="sincronizacaoomie",
            name="celery_task_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="sincronizacaoomie",
            name="enfileirada_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
