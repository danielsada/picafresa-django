from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_auditevent_active_scope_reference_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION audit_prevent_event_mutation()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION 'audit events are immutable'
                        USING ERRCODE = '42501';
                END;
                $$;

                CREATE TRIGGER audit_event_immutable
                BEFORE UPDATE OR DELETE ON audit_auditevent
                FOR EACH ROW
                EXECUTE FUNCTION audit_prevent_event_mutation();
            """,
            reverse_sql="""
                DROP TRIGGER audit_event_immutable ON audit_auditevent;
                DROP FUNCTION audit_prevent_event_mutation();
            """,
        ),
    ]
