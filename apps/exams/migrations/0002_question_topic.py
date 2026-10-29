from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exams", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="question",
            name="topic",
            # Questions created before this migration get an empty topic.
            field=models.CharField(default="", max_length=100),
            preserve_default=False,
        ),
    ]
