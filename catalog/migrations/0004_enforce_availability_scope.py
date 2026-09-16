from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_plan_availability_planbusinessavailability_and_more")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION catalog_validate_business_availability() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM catalog_plan plan
                        JOIN organizations_business business
                          ON business.id = NEW.business_id
                        WHERE plan.id = NEW.plan_id
                          AND plan.reseller_id = business.reseller_id
                    ) THEN
                        RAISE EXCEPTION 'plan and business must belong to the same reseller'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER catalog_business_availability_scope
                BEFORE INSERT OR UPDATE ON catalog_planbusinessavailability
                FOR EACH ROW EXECUTE FUNCTION catalog_validate_business_availability();

                CREATE FUNCTION catalog_protect_available_business_owner() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.reseller_id IS DISTINCT FROM OLD.reseller_id
                       AND EXISTS (
                           SELECT 1
                           FROM catalog_planbusinessavailability availability
                           JOIN catalog_plan plan ON plan.id = availability.plan_id
                           WHERE availability.business_id = OLD.id
                             AND plan.reseller_id <> NEW.reseller_id
                       ) THEN
                        RAISE EXCEPTION 'business owner conflicts with plan availability'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER catalog_available_business_owner
                BEFORE UPDATE OF reseller_id ON organizations_business
                FOR EACH ROW EXECUTE FUNCTION catalog_protect_available_business_owner();
            """,
            reverse_sql="""
                DROP TRIGGER catalog_available_business_owner ON organizations_business;
                DROP FUNCTION catalog_protect_available_business_owner();
                DROP TRIGGER catalog_business_availability_scope
                    ON catalog_planbusinessavailability;
                DROP FUNCTION catalog_validate_business_availability();
            """,
        ),
    ]
