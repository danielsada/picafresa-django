from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("enrollments", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE FUNCTION enrollments_protect_plan_enrollment() RETURNS trigger
                LANGUAGE plpgsql AS $$
                DECLARE
                    member_business_id bigint;
                    plan_reseller_id bigint;
                    business_reseller_id bigint;
                    version_duration integer;
                    version_status text;
                    version_effective_from date;
                    version_effective_until date;
                    preceding record;
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'plan enrollment terms cannot be deleted'
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'UPDATE' THEN
                        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM
                           (to_jsonb(OLD) - 'status') THEN
                            RAISE EXCEPTION 'plan enrollment terms are immutable'
                                USING ERRCODE = '23514';
                        END IF;
                        IF NOT (
                            (OLD.status = 'pending_payment'
                                AND NEW.status IN ('active', 'cancelled'))
                            OR (OLD.status = 'active'
                                AND NEW.status IN ('suspended', 'expired', 'cancelled'))
                            OR (OLD.status = 'suspended'
                                AND NEW.status IN ('active', 'expired', 'cancelled'))
                        ) THEN
                            RAISE EXCEPTION 'invalid plan enrollment transition'
                                USING ERRCODE = '23514';
                        END IF;
                        RETURN NEW;
                    END IF;

                    IF NEW.status <> 'pending_payment' THEN
                        RAISE EXCEPTION 'plan enrollments must start pending payment'
                            USING ERRCODE = '23514';
                    END IF;

                    SELECT business_id INTO member_business_id
                    FROM enrollments_member WHERE id = NEW.member_id;
                    SELECT p.reseller_id, v.duration_months, v.status,
                           v.effective_from, v.effective_until
                    INTO plan_reseller_id, version_duration, version_status,
                         version_effective_from, version_effective_until
                    FROM catalog_planversion v
                    JOIN catalog_plan p ON p.id = v.plan_id
                    WHERE v.id = NEW.plan_version_id;
                    SELECT reseller_id INTO business_reseller_id
                    FROM organizations_business WHERE id = NEW.business_id;

                    IF member_business_id IS DISTINCT FROM NEW.business_id
                       OR plan_reseller_id IS DISTINCT FROM business_reseller_id
                       OR version_duration IS DISTINCT FROM NEW.duration_months
                       OR version_status IS DISTINCT FROM 'published'
                       OR NEW.start_date < version_effective_from
                       OR NEW.start_date >= version_effective_until THEN
                        RAISE EXCEPTION 'plan enrollment tenant and version terms must match'
                            USING ERRCODE = '23514';
                    END IF;

                    IF NEW.preceding_enrollment_id IS NOT NULL THEN
                        SELECT member_id, business_id, plan_version_id, end_date
                        INTO preceding
                        FROM enrollments_planenrollment
                        WHERE id = NEW.preceding_enrollment_id;
                        IF preceding.member_id IS DISTINCT FROM NEW.member_id
                           OR preceding.business_id IS DISTINCT FROM NEW.business_id
                           OR preceding.end_date IS DISTINCT FROM NEW.start_date
                           OR NOT EXISTS (
                               SELECT 1
                               FROM catalog_planversion old_version
                               JOIN catalog_planversion new_version
                                 ON new_version.plan_id = old_version.plan_id
                               WHERE old_version.id = preceding.plan_version_id
                                 AND new_version.id = NEW.plan_version_id
                           ) THEN
                            RAISE EXCEPTION 'renewal must continue the same member and plan'
                                USING ERRCODE = '23514';
                        END IF;
                    END IF;
                    RETURN NEW;
                END;
                $$;

                CREATE TRIGGER enrollments_plan_enrollment_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON enrollments_planenrollment
                FOR EACH ROW EXECUTE FUNCTION enrollments_protect_plan_enrollment();
            """,
            reverse_sql="""
                DROP TRIGGER enrollments_plan_enrollment_immutable
                    ON enrollments_planenrollment;
                DROP FUNCTION enrollments_protect_plan_enrollment();
            """,
        )
    ]
