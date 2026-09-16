from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_permission_labels")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION organizations_protect_provider_contract_identity()
                RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.business_id IS DISTINCT FROM OLD.business_id
                       OR NEW.provider_id IS DISTINCT FROM OLD.provider_id THEN
                        RAISE EXCEPTION 'provider contract tenant and provider are permanent'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER organizations_provider_contract_identity
                BEFORE UPDATE ON organizations_providerassignment
                FOR EACH ROW
                EXECUTE FUNCTION organizations_protect_provider_contract_identity();
            """,
            reverse_sql="""
                DROP TRIGGER organizations_provider_contract_identity
                    ON organizations_providerassignment;
                DROP FUNCTION organizations_protect_provider_contract_identity();
            """,
        ),
    ]
