-- Correction de authenticate_user() pour résoudre l'ambiguïté des colonnes de retour
-- Le problème : les noms des colonnes RETURNS TABLE (user_id, email...)
-- créent une ambiguïté avec les variables PL/pgSQL v_user.user_id
-- Solution : renommer les colonnes de sortie avec le préfixe "out_"

CREATE OR REPLACE FUNCTION authenticate_user(
    p_email          VARCHAR,
    p_plain_password VARCHAR,
    p_ip_address     INET DEFAULT NULL,
    p_user_agent     VARCHAR DEFAULT NULL
) RETURNS TABLE (
    out_user_id             UUID,
    out_email               VARCHAR,
    out_first_name          VARCHAR,
    out_last_name           VARCHAR,
    out_role_code           VARCHAR,
    out_role_label          VARCHAR,
    out_is_active           BOOLEAN,
    out_is_email_verified   BOOLEAN,
    out_preferred_language  VARCHAR,
    out_timezone            VARCHAR
) AS $$
DECLARE
    v_user RECORD;
BEGIN
    SELECT u.user_id, u.email, u.first_name, u.last_name,
           u.password_hash, u.is_active, u.is_email_verified,
           u.failed_login_count, u.locked_until,
           u.preferred_language, u.timezone,
           r.role_code, r.role_label
    INTO v_user
    FROM app_user u
    JOIN user_role r ON r.role_id = u.role_id
    WHERE u.email = p_email;

    IF v_user IS NULL THEN
        INSERT INTO user_login_log (user_id, action, ip_address, user_agent, details)
        VALUES (NULL, 'login_failure', p_ip_address, p_user_agent,
                jsonb_build_object('reason', 'unknown_email', 'attempted_email', p_email));
        RETURN;
    END IF;

    IF NOT v_user.is_active THEN
        INSERT INTO user_login_log (user_id, action, ip_address, user_agent, details)
        VALUES (v_user.user_id, 'login_failure', p_ip_address, p_user_agent,
                jsonb_build_object('reason', 'account_inactive'));
        RETURN;
    END IF;

    IF v_user.locked_until IS NOT NULL AND v_user.locked_until > NOW() THEN
        INSERT INTO user_login_log (user_id, action, ip_address, user_agent, details)
        VALUES (v_user.user_id, 'login_failure', p_ip_address, p_user_agent,
                jsonb_build_object('reason', 'account_locked', 'locked_until', v_user.locked_until));
        RETURN;
    END IF;

    IF verify_password(p_plain_password, v_user.password_hash) THEN
        UPDATE app_user SET
            last_login_at      = NOW(),
            last_login_ip      = p_ip_address,
            failed_login_count = 0,
            locked_until       = NULL
        WHERE app_user.user_id = v_user.user_id;

        INSERT INTO user_login_log (user_id, action, ip_address, user_agent)
        VALUES (v_user.user_id, 'login_success', p_ip_address, p_user_agent);

        out_user_id            := v_user.user_id;
        out_email              := v_user.email;
        out_first_name         := v_user.first_name;
        out_last_name          := v_user.last_name;
        out_role_code          := v_user.role_code;
        out_role_label         := v_user.role_label;
        out_is_active          := v_user.is_active;
        out_is_email_verified  := v_user.is_email_verified;
        out_preferred_language := v_user.preferred_language;
        out_timezone           := v_user.timezone;
        RETURN NEXT;
    ELSE
        UPDATE app_user SET
            failed_login_count = failed_login_count + 1,
            locked_until = CASE
                WHEN failed_login_count >= 4 THEN NOW() + INTERVAL '30 minutes'
                ELSE NULL
            END
        WHERE app_user.user_id = v_user.user_id;

        INSERT INTO user_login_log (user_id, action, ip_address, user_agent, details)
        VALUES (v_user.user_id, 'login_failure', p_ip_address, p_user_agent,
                jsonb_build_object('reason', 'wrong_password',
                                   'failed_count', v_user.failed_login_count + 1));
        RETURN;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
