from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION catalog_protect_plan_identity() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.provider_id IS DISTINCT FROM OLD.provider_id
                       OR NEW.reseller_id IS DISTINCT FROM OLD.reseller_id THEN
                        RAISE EXCEPTION 'plan provider and owner are permanent'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER catalog_plan_identity
                BEFORE UPDATE ON catalog_plan
                FOR EACH ROW EXECUTE FUNCTION catalog_protect_plan_identity();

                CREATE FUNCTION catalog_protect_version() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        IF NEW.status <> 'draft' THEN
                            RAISE EXCEPTION 'versions must start as drafts'
                                USING ERRCODE = '23514';
                        END IF;
                        RETURN NEW;
                    END IF;
                    IF OLD.status = 'published' THEN
                        RAISE EXCEPTION 'published plan versions are immutable'
                            USING ERRCODE = '23514';
                    END IF;
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    IF NEW.author_id IS DISTINCT FROM OLD.author_id
                       OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
                       OR NEW.number IS DISTINCT FROM OLD.number THEN
                        RAISE EXCEPTION 'version identity and author are permanent'
                            USING ERRCODE = '23514';
                    END IF;
                    IF NEW.status = 'published' THEN
                        IF (to_jsonb(NEW) - ARRAY['status', 'published_by_id', 'published_at'])
                           IS DISTINCT FROM
                           (to_jsonb(OLD) - ARRAY['status', 'published_by_id', 'published_at'])
                           OR NOT EXISTS (
                               SELECT 1 FROM catalog_planservice WHERE version_id = OLD.id
                           ) THEN
                            RAISE EXCEPTION 'publish existing draft terms with services'
                                USING ERRCODE = '23514';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER catalog_version_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON catalog_planversion
                FOR EACH ROW EXECUTE FUNCTION catalog_protect_version();

                CREATE FUNCTION catalog_protect_service() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    old_version bigint;
                    new_version bigint;
                    version_record record;
                BEGIN
                    IF TG_OP <> 'INSERT' THEN old_version := OLD.version_id; END IF;
                    IF TG_OP <> 'DELETE' THEN new_version := NEW.version_id; END IF;
                    -- Serialize service writes against publication, including reparenting.
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
                CREATE TRIGGER catalog_service_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON catalog_planservice
                FOR EACH ROW EXECUTE FUNCTION catalog_protect_service();
            """,
            reverse_sql="""
                DROP TRIGGER catalog_service_immutable ON catalog_planservice;
                DROP FUNCTION catalog_protect_service();
                DROP TRIGGER catalog_version_immutable ON catalog_planversion;
                DROP FUNCTION catalog_protect_version();
                DROP TRIGGER catalog_plan_identity ON catalog_plan;
                DROP FUNCTION catalog_protect_plan_identity();
            """,
        ),
    ]
