from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0003_minimal_rag'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='evidenceunit',
            name='knowledge_type',
        ),
    ]
