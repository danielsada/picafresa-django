from django.db import migrations, models

import catalog.models


def populate_coverage_contents(apps, schema_editor):
    del schema_editor
    plan_service = apps.get_model("catalog", "PlanService")
    version_ids = plan_service.objects.values_list("version_id", flat=True).distinct()
    for version_id in version_ids.iterator():
        services = plan_service.objects.filter(version_id=version_id).order_by("pk")
        for position, service in enumerate(services.iterator(), start=1):
            service.position = position
            service.service_channels = ["online"]
            service.save(update_fields=["position", "service_channels"])


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_enforce_availability_scope")]

    operations = [
        migrations.AlterModelOptions(
            name="planservice",
            options={
                "ordering": ("position", "pk"),
                "verbose_name": "servicio de Plan",
                "verbose_name_plural": "servicios de Plan",
            },
        ),
        migrations.AddField(
            model_name="planservice",
            name="position",
            field=models.PositiveSmallIntegerField(null=True, verbose_name="posición"),
        ),
        migrations.AddField(
            model_name="planservice",
            name="service_channels",
            field=models.JSONField(default=list, verbose_name="canales de servicio"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="planservice",
            name="limit_text",
            field=models.TextField(blank=True, verbose_name="límites o condiciones para el Afiliado"),
        ),
        migrations.AddField(
            model_name="planservice",
            name="internal_notes",
            field=models.TextField(blank=True, verbose_name="notas internas de atención"),
        ),
        migrations.AddField(
            model_name="planservice",
            name="public_description",
            field=models.TextField(blank=True, verbose_name="descripción pública"),
        ),
        migrations.AddField(
            model_name="planservice",
            name="marketing_text",
            field=models.TextField(blank=True, verbose_name="texto de marketing"),
        ),
        migrations.AddField(
            model_name="planservice",
            name="image_reference",
            field=models.CharField(
                blank=True,
                max_length=500,
                validators=[catalog.models.validate_coverage_image_reference],
                verbose_name="referencia de imagen",
            ),
        ),
        migrations.AddField(
            model_name="planservice",
            name="presentation_visible",
            field=models.BooleanField(default=False, verbose_name="presentación visible"),
        ),
        migrations.RunPython(populate_coverage_contents, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="planservice",
            name="position",
            field=models.PositiveSmallIntegerField(verbose_name="posición"),
        ),
        migrations.AlterField(
            model_name="planservice",
            name="service_channels",
            field=models.JSONField(
                validators=[catalog.models.validate_service_channels],
                verbose_name="canales de servicio",
            ),
        ),
        migrations.AddConstraint(
            model_name="planservice",
            constraint=models.CheckConstraint(
                condition=models.Q(("position__gt", 0)),
                name="ck_plan_service_positive_position",
            ),
        ),
        migrations.AddConstraint(
            model_name="planservice",
            constraint=models.UniqueConstraint(
                fields=("version", "position"),
                name="uq_plan_service_version_position",
            ),
        ),
        migrations.AddConstraint(
            model_name="planservice",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("service_channels__0__isnull", False),
                    ("service_channels__contained_by", ["online", "call_center"]),
                ),
                name="ck_plan_service_supported_channels",
            ),
        ),
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION catalog_protect_service() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    old_version bigint;
                    new_version bigint;
                    version_record record;
                BEGIN
                    IF TG_OP <> 'INSERT' THEN old_version := OLD.version_id; END IF;
                    IF TG_OP <> 'DELETE' THEN new_version := NEW.version_id; END IF;
                    FOR version_record IN
                        SELECT status FROM catalog_planversion
                        WHERE id = old_version OR id = new_version ORDER BY id FOR UPDATE
                    LOOP
                        IF version_record.status = 'published'
                           AND (
                               TG_OP <> 'UPDATE'
                               OR (to_jsonb(NEW) - ARRAY[
                                      'internal_notes',
                                      'public_description',
                                      'marketing_text',
                                      'image_reference',
                                      'presentation_visible'
                                  ]) IS DISTINCT FROM
                                  (to_jsonb(OLD) - ARRAY[
                                      'internal_notes',
                                      'public_description',
                                      'marketing_text',
                                      'image_reference',
                                      'presentation_visible'
                                  ])
                           ) THEN
                            RAISE EXCEPTION 'published Plan coverage terms are immutable'
                                USING ERRCODE = '23514';
                        END IF;
                    END LOOP;
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END;
                $$;
            """,
            reverse_sql="""
                CREATE OR REPLACE FUNCTION catalog_protect_service() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    old_version bigint;
                    new_version bigint;
                    version_record record;
                BEGIN
                    IF TG_OP <> 'INSERT' THEN old_version := OLD.version_id; END IF;
                    IF TG_OP <> 'DELETE' THEN new_version := NEW.version_id; END IF;
                    FOR version_record IN
                        SELECT status FROM catalog_planversion
                        WHERE id = old_version OR id = new_version ORDER BY id FOR UPDATE
                    LOOP
                        IF version_record.status = 'published' THEN
                            RAISE EXCEPTION 'published plan services are immutable'
                                USING ERRCODE = '23514';
                        END IF;
                    END LOOP;
                    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                    RETURN NEW;
                END;
                $$;
            """,
        ),
    ]
