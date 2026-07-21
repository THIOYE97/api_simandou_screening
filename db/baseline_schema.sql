--
-- PostgreSQL database dump
--

\restrict RAFoyYQpl1U7s58D4YGbAOhALX4QHX18FGzsMOu4YE77E6RHxZDeBh3LjSM1m5b

-- Dumped from database version 18.1 (Ubuntu 18.1-1.pgdg24.04+2)
-- Dumped by pg_dump version 18.1 (Ubuntu 18.1-1.pgdg24.04+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: unaccent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;


--
-- Name: EXTENSION unaccent; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION unaccent IS 'text search dictionary that removes accents';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: action_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.action_type AS ENUM (
    'PASS',
    'MANUAL_REVIEW',
    'BLOCK'
);


--
-- Name: adverse_media_category; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.adverse_media_category AS ENUM (
    'FRAUD',
    'CORRUPTION',
    'MONEY_LAUNDERING',
    'TERRORISM',
    'TRAFFICKING',
    'SANCTIONS_EVASION',
    'ORGANIZED_CRIME',
    'OTHER'
);


--
-- Name: alert_severity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_severity AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);


--
-- Name: alert_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_source AS ENUM (
    'SCREENING',
    'SCORING',
    'KYT',
    'MANUAL'
);


--
-- Name: alert_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_status AS ENUM (
    'OPEN',
    'FALSE_POSITIVE',
    'CONFIRMED'
);


--
-- Name: alert_status_app; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_status_app AS ENUM (
    'OPEN',
    'IN_REVIEW',
    'ESCALATED',
    'CLOSED_TRUE_POSITIVE',
    'CLOSED_FALSE_POSITIVE'
);


--
-- Name: alert_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.alert_type AS ENUM (
    'SANCTIONS',
    'PEP',
    'ADVERSE_MEDIA'
);


--
-- Name: case_entity_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.case_entity_role AS ENUM (
    'PRIMARY_PERSON',
    'PRIMARY_COMPANY',
    'DIRECTOR',
    'UBO'
);


--
-- Name: case_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.case_status AS ENUM (
    'DRAFT',
    'PENDING_REVIEW',
    'ACTION_REQUIRED',
    'APPROVED',
    'REJECTED'
);


--
-- Name: case_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.case_type AS ENUM (
    'KYC',
    'KYB'
);


--
-- Name: company_role_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.company_role_type AS ENUM (
    'DIRECTOR',
    'UBO'
);


--
-- Name: entity_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.entity_type AS ENUM (
    'person',
    'company'
);


--
-- Name: export_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.export_type AS ENUM (
    'PDF_REPORT',
    'ZIP_DOSSIER',
    'CSV_STATS'
);


--
-- Name: kyt_channel; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.kyt_channel AS ENUM (
    'CASH',
    'WIRE',
    'CHECK',
    'CARD',
    'OTHER'
);


--
-- Name: kyt_direction; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.kyt_direction AS ENUM (
    'IN',
    'OUT',
    'INTERNAL'
);


--
-- Name: kyt_source_system; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.kyt_source_system AS ENUM (
    'T24',
    'SWIFT',
    'ACH',
    'RTGS',
    'MANUAL'
);


--
-- Name: match_band; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.match_band AS ENUM (
    'STRONG',
    'POSSIBLE',
    'WEAK'
);


--
-- Name: monitoring_frequency; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.monitoring_frequency AS ENUM (
    'DAILY',
    'WEEKLY',
    'MONTHLY'
);


--
-- Name: ocr_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ocr_status AS ENUM (
    'PENDING',
    'DONE',
    'LOW_CONFIDENCE',
    'FAILED'
);


--
-- Name: record_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.record_type AS ENUM (
    'SANCTION',
    'NOTICE',
    'PEP'
);


--
-- Name: risk_class; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.risk_class AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);


--
-- Name: risk_level; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.risk_level AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH'
);


--
-- Name: risk_subject_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.risk_subject_type AS ENUM (
    'PERSON',
    'COMPANY',
    'TRANSACTION'
);


--
-- Name: sar_decision; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sar_decision AS ENUM (
    'PENDING',
    'FILED_TO_CENTIF',
    'DISMISSED'
);


--
-- Name: sar_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sar_status AS ENUM (
    'DRAFT',
    'SUBMITTED',
    'UNDER_REVIEW',
    'DECIDED'
);


--
-- Name: scenario_category; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scenario_category AS ENUM (
    'SANCTIONS',
    'PEP',
    'GEOGRAPHY',
    'TRANSACTION',
    'BEHAVIOR',
    'ADVERSE_MEDIA'
);


--
-- Name: scenario_severity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.scenario_severity AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'CRITICAL'
);


--
-- Name: source_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_type AS ENUM (
    'SANCTIONS',
    'OFFICIAL_NOTICE',
    'PEP_RULES',
    'OTHER'
);


--
-- Name: user_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.user_role AS ENUM (
    'ANALYST',
    'CHECKER',
    'ADMIN',
    'SUPER_ADMIN'
);


--
-- Name: auth_get_user_by_email(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.auth_get_user_by_email(p_email text) RETURNS TABLE(id uuid, email text, full_name text, password_hash text, tenant_id uuid, is_active boolean, status text)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
  SELECT u.id, u.email, u.full_name, u.password_hash, u.tenant_id, u.is_active, u.status
  FROM public.users u
  WHERE lower(u.email) = lower(p_email)
  LIMIT 1;
$$;


--
-- Name: get_user_for_login(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.get_user_for_login(p_email text) RETURNS TABLE(id uuid, email text, full_name text, password_hash text, is_active boolean, status text, tenant_id uuid)
    LANGUAGE sql SECURITY DEFINER
    AS $$
  SELECT u.id, u.email, u.full_name, u.password_hash, u.is_active, u.status, u.tenant_id
  FROM public.users u
  WHERE lower(trim(u.email)) = lower(trim(p_email))
  LIMIT 1;
$$;


--
-- Name: ingest_batch(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.ingest_batch(p_batch uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  r RECORD;
  v_source_id SMALLINT;
  v_entity_id UUID;
BEGIN
  FOR r IN
    SELECT * FROM staging_screening_records WHERE batch_id = p_batch
  LOOP
    SELECT id INTO v_source_id FROM sources WHERE source_code = r.source_code AND is_active = true;
    IF v_source_id IS NULL THEN
      RAISE EXCEPTION 'Unknown source_code: %', r.source_code;
    END IF;

    v_entity_id := upsert_person_entity(r.primary_name, r.dob, r.nationalities, r.pob_country);

    -- aliases
    IF r.aliases IS NOT NULL THEN
      INSERT INTO entity_names(entity_id, name_raw, name_normalized, name_tokens, is_primary, name_type)
      SELECT
        v_entity_id,
        a,
        normalize_name(a),
        tokenize_name(a),
        false,
        'ALIAS'
      FROM unnest(r.aliases) a
      ON CONFLICT DO NOTHING; -- (si tu veux, ajoute une contrainte unique)
    END IF;

    -- source record
    INSERT INTO source_records(source_id, source_ref, entity_id, record_type, listed_on, unlisted_on,
                               program, summary, evidence_urls, raw_payload)
    VALUES (v_source_id, r.source_ref, v_entity_id, r.record_type, r.listed_on, r.unlisted_on,
            r.program, r.summary, r.evidence_urls, r.raw_payload)
    ON CONFLICT (source_id, source_ref) DO UPDATE SET
      entity_id = EXCLUDED.entity_id,
      record_type = EXCLUDED.record_type,
      listed_on = EXCLUDED.listed_on,
      unlisted_on = EXCLUDED.unlisted_on,
      program = EXCLUDED.program,
      summary = EXCLUDED.summary,
      evidence_urls = EXCLUDED.evidence_urls,
      raw_payload = EXCLUDED.raw_payload,
      updated_at = now();

    -- mise à jour risk_level “par défaut” selon record_type
    UPDATE entities e
    SET risk_level =
      CASE
        WHEN EXISTS (SELECT 1 FROM source_records sr WHERE sr.entity_id=e.id AND sr.record_type='SANCTION') THEN 'HIGH'::risk_level
        WHEN EXISTS (SELECT 1 FROM source_records sr WHERE sr.entity_id=e.id AND sr.record_type IN ('NOTICE','PEP')) THEN 'MEDIUM'::risk_level
        ELSE e.risk_level
      END,
      updated_at = now()
    WHERE e.id = v_entity_id;
  END LOOP;
END;
$$;


--
-- Name: normalize_name(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.normalize_name(input text) RETURNS text
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT trim(
    regexp_replace(
      upper(unaccent(coalesce(input,''))),
      '[^A-Z0-9 ]+', ' ', 'g'
    )
  );
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;


--
-- Name: tokenize_name(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.tokenize_name(input text) RETURNS text[]
    LANGUAGE sql IMMUTABLE
    AS $$
  SELECT array_remove(regexp_split_to_array(normalize_name(input), '\s+'), '');
$$;


--
-- Name: tokenize_name_filtered(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.tokenize_name_filtered(input text, country text) RETURNS text[]
    LANGUAGE sql STABLE
    AS $$
  WITH t AS (
    SELECT tokenize_name(input) AS tokens
  )
  SELECT COALESCE(
    (SELECT array_agg(tok)
     FROM unnest((SELECT tokens FROM t)) tok
     WHERE NOT EXISTS (
       SELECT 1 FROM name_stopwords s
       WHERE s.country = country AND s.token = tok
     )
    ),
    ARRAY[]::TEXT[]
  );
$$;


--
-- Name: upsert_person_entity(text, date, text[], text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.upsert_person_entity(p_primary_name text, p_dob date, p_nationalities text[], p_country_focus text) RETURNS uuid
    LANGUAGE plpgsql
    AS $$
DECLARE
  v_norm TEXT := normalize_name(p_primary_name);
  v_entity UUID;
BEGIN
  -- 1) match fort: nom normalisé + dob
  IF p_dob IS NOT NULL THEN
    SELECT e.id INTO v_entity
    FROM entities e
    JOIN entity_names n ON n.entity_id = e.id
    JOIN person_attributes pa ON pa.entity_id = e.id
    WHERE e.entity_type='person'
      AND n.name_normalized = v_norm
      AND pa.dob = p_dob
    LIMIT 1;
  END IF;

  -- 2) match moyen: nom exact + nationalité overlap
  IF v_entity IS NULL AND p_nationalities IS NOT NULL THEN
    SELECT e.id INTO v_entity
    FROM entities e
    JOIN entity_names n ON n.entity_id = e.id
    JOIN person_attributes pa ON pa.entity_id = e.id
    WHERE e.entity_type='person'
      AND n.name_normalized = v_norm
      AND pa.nationalities && p_nationalities
    LIMIT 1;
  END IF;

  -- 3) create new if not found
  IF v_entity IS NULL THEN
    INSERT INTO entities(entity_type, primary_name, country_focus, risk_level)
    VALUES ('person', v_norm, p_country_focus, 'LOW')
    RETURNING id INTO v_entity;

    INSERT INTO entity_names(entity_id, name_raw, name_normalized, name_tokens, is_primary, name_type)
    VALUES (v_entity, p_primary_name, v_norm, tokenize_name(p_primary_name), true, 'PRIMARY');

    INSERT INTO person_attributes(entity_id, dob, nationalities)
    VALUES (v_entity, p_dob, p_nationalities)
    ON CONFLICT (entity_id) DO UPDATE SET
      dob = COALESCE(person_attributes.dob, EXCLUDED.dob),
      nationalities = COALESCE(person_attributes.nationalities, EXCLUDED.nationalities),
      updated_at = now();
  ELSE
    -- update minimal attributes if missing
    INSERT INTO person_attributes(entity_id, dob, nationalities)
    VALUES (v_entity, p_dob, p_nationalities)
    ON CONFLICT (entity_id) DO UPDATE SET
      dob = COALESCE(person_attributes.dob, EXCLUDED.dob),
      nationalities = COALESCE(person_attributes.nationalities, EXCLUDED.nationalities),
      updated_at = now();
  END IF;

  RETURN v_entity;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: adverse_media_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.adverse_media_records (
    id uuid NOT NULL,
    entity_name character varying NOT NULL,
    normalized_name character varying NOT NULL,
    category public.adverse_media_category NOT NULL,
    source character varying,
    url character varying,
    summary text,
    published_at timestamp with time zone,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: alert_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alert_rules (
    id uuid NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    source public.alert_source NOT NULL,
    severity public.alert_severity NOT NULL,
    condition jsonb NOT NULL,
    auto_escalate boolean NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alerts (
    id uuid NOT NULL,
    tenant_id uuid,
    source public.alert_source NOT NULL,
    severity public.alert_severity NOT NULL,
    status public.alert_status_app DEFAULT 'OPEN'::public.alert_status_app NOT NULL,
    title character varying NOT NULL,
    rule_code character varying,
    subject_ref character varying,
    subject_label character varying,
    risk_assessment_id uuid,
    detail jsonb NOT NULL,
    assigned_to uuid,
    resolution text,
    resolved_by uuid,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_user_id uuid,
    tenant_id uuid,
    action text NOT NULL,
    target_type text,
    target_id text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_alerts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_alerts (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    case_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    alert_type public.alert_type NOT NULL,
    severity public.risk_level DEFAULT 'LOW'::public.risk_level NOT NULL,
    title text,
    description text,
    external_ref text,
    source_record_id uuid,
    match_id bigint,
    status public.alert_status DEFAULT 'OPEN'::public.alert_status NOT NULL,
    decided_by uuid,
    decided_at timestamp with time zone,
    decision_comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_entities (
    case_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    role public.case_entity_role NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_exports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_exports (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    case_id uuid NOT NULL,
    export_type public.export_type NOT NULL,
    file_path text NOT NULL,
    generated_by uuid NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    parameters jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: case_screening_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_screening_decisions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    request_id uuid NOT NULL,
    decision text NOT NULL,
    comment text NOT NULL,
    decided_by_email text NOT NULL,
    decided_by_user_id uuid,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT case_screening_decisions_decision_check CHECK ((decision = ANY (ARRAY['PASS'::text, 'BLOCK'::text])))
);


--
-- Name: case_status_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_status_history (
    id bigint NOT NULL,
    case_id uuid NOT NULL,
    from_status public.case_status,
    to_status public.case_status NOT NULL,
    actor_user_id uuid NOT NULL,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: case_status_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.case_status_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: case_status_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.case_status_history_id_seq OWNED BY public.case_status_history.id;


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    case_type public.case_type NOT NULL,
    status public.case_status DEFAULT 'DRAFT'::public.case_status NOT NULL,
    risk_level public.risk_level DEFAULT 'LOW'::public.risk_level NOT NULL,
    urgent_flag boolean DEFAULT false NOT NULL,
    urgent_reason text,
    created_by uuid NOT NULL,
    assigned_checker uuid,
    last_screening_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    sumsub_applicant_id text,
    sumsub_review_status text,
    sumsub_review_answer text,
    sumsub_last_event_at timestamp with time zone,
    sumsub_snapshot jsonb,
    tenant_id uuid DEFAULT (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid NOT NULL
);

ALTER TABLE ONLY public.cases FORCE ROW LEVEL SECURITY;


--
-- Name: companies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companies (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    entity_id uuid NOT NULL,
    legal_name text,
    legal_form text,
    rccm text,
    nif text,
    client_code text,
    address_full text,
    city text,
    commune text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: company_people; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_people (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    company_id uuid NOT NULL,
    person_id uuid NOT NULL,
    role_type public.company_role_type NOT NULL,
    ownership_pct numeric(5,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_ubo_pct CHECK (((role_type <> 'UBO'::public.company_role_type) OR ((ownership_pct IS NOT NULL) AND (ownership_pct >= 25.0))))
);


--
-- Name: compliance_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compliance_events (
    id uuid NOT NULL,
    tenant_id uuid,
    alert_id uuid,
    subject_kind character varying(16) NOT NULL,
    subject_id character varying,
    subject_label character varying,
    action character varying(24) NOT NULL,
    to_status character varying(32),
    decision character varying(16),
    justification text,
    actor_id uuid,
    actor_label character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    case_id uuid,
    doc_type text NOT NULL,
    file_path text NOT NULL,
    mime_type text,
    file_hash text,
    uploaded_by uuid NOT NULL,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    ocr_status public.ocr_status DEFAULT 'PENDING'::public.ocr_status NOT NULL,
    ocr_confidence numeric(4,3),
    extracted_fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    storage_backend text,
    object_key text,
    original_filename text,
    size_bytes bigint,
    sha256 text,
    tenant_id uuid DEFAULT (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid NOT NULL
);


--
-- Name: entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entities (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    entity_type public.entity_type NOT NULL,
    primary_name text NOT NULL,
    country_focus text,
    risk_level public.risk_level DEFAULT 'LOW'::public.risk_level NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source_name text,
    source_id text,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: entity_names; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_names (
    id bigint NOT NULL,
    entity_id uuid NOT NULL,
    name_raw text NOT NULL,
    name_normalized text NOT NULL,
    name_tokens text[] NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    name_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT entity_names_name_type_check CHECK ((name_type = ANY (ARRAY['PRIMARY'::text, 'ALIAS'::text, 'AKA'::text, 'TRANSLIT'::text])))
);


--
-- Name: entity_names_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.entity_names_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entity_names_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.entity_names_id_seq OWNED BY public.entity_names.id;


--
-- Name: external_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.external_identities (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    entity_id uuid NOT NULL,
    provider text NOT NULL,
    external_id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invitations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    email text NOT NULL,
    role text DEFAULT 'ANALYST'::text NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    max_uses integer DEFAULT 1 NOT NULL,
    used_count integer DEFAULT 0 NOT NULL,
    invited_by uuid,
    accepted_by uuid,
    accepted_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT invitations_role_check CHECK ((role = ANY (ARRAY['OWNER'::text, 'ADMIN'::text, 'ANALYST'::text, 'VIEWER'::text])))
);


--
-- Name: kyt_sars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyt_sars (
    id uuid NOT NULL,
    tenant_id uuid,
    subject_ref character varying,
    subject_label character varying,
    reason character varying NOT NULL,
    narrative text,
    status public.sar_status NOT NULL,
    decision public.sar_decision NOT NULL,
    related_alert_id uuid,
    related_transaction_ids jsonb NOT NULL,
    created_by uuid,
    reviewed_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: kyt_transactions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyt_transactions (
    id uuid NOT NULL,
    tenant_id uuid,
    external_ref character varying,
    source_system public.kyt_source_system NOT NULL,
    direction public.kyt_direction NOT NULL,
    channel public.kyt_channel NOT NULL,
    amount numeric(18,2) NOT NULL,
    currency character varying(3) NOT NULL,
    customer_ref character varying,
    counterparty_name character varying,
    counterparty_country character varying(64),
    value_date timestamp with time zone,
    raw jsonb NOT NULL,
    risk_assessment_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    decision character varying(16) DEFAULT 'PENDING'::character varying NOT NULL
);


--
-- Name: match_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.match_labels (
    request_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    label text NOT NULL,
    labeled_by text NOT NULL,
    labeled_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT match_labels_label_check CHECK ((label = ANY (ARRAY['TP'::text, 'FP'::text, 'UNCERTAIN'::text])))
);


--
-- Name: monitoring_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.monitoring_jobs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    case_id uuid NOT NULL,
    frequency public.monitoring_frequency DEFAULT 'WEEKLY'::public.monitoring_frequency NOT NULL,
    next_run_at timestamp with time zone NOT NULL,
    last_run_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    last_summary text
);


--
-- Name: name_stopwords; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.name_stopwords (
    country text NOT NULL,
    token text NOT NULL
);


--
-- Name: person_attributes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person_attributes (
    entity_id uuid NOT NULL,
    dob date,
    pob_city text,
    pob_country text,
    gender text,
    nationalities text[],
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT person_attributes_gender_check CHECK ((gender = ANY (ARRAY['M'::text, 'F'::text, 'X'::text])))
);


--
-- Name: persons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persons (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    entity_id uuid NOT NULL,
    last_name text,
    first_names text,
    date_of_birth date,
    place_of_birth text,
    nationality text,
    address text,
    phone text,
    email text,
    document_type text,
    document_number text,
    document_expiry date,
    document_issue_country text,
    ppe_status boolean,
    client_code text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: provider_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_events (
    id bigint NOT NULL,
    provider text NOT NULL,
    external_id text,
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_event_id text
);


--
-- Name: provider_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.provider_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: provider_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.provider_events_id_seq OWNED BY public.provider_events.id;


--
-- Name: rbac_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rbac_roles (
    id uuid NOT NULL,
    tenant_id uuid,
    code character varying(32) NOT NULL,
    name character varying NOT NULL,
    description text,
    permissions jsonb NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rbac_user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rbac_user_roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role_code character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ref_business_sectors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ref_business_sectors (
    id uuid NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    risk_weight integer NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ref_client_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ref_client_categories (
    id uuid NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    base_risk_weight integer NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ref_countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ref_countries (
    id uuid NOT NULL,
    iso_code character varying(3) NOT NULL,
    name character varying NOT NULL,
    is_high_risk boolean NOT NULL,
    is_non_cooperative boolean NOT NULL,
    risk_weight integer NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ref_currencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ref_currencies (
    id uuid NOT NULL,
    code character varying(3) NOT NULL,
    name character varying NOT NULL,
    symbol character varying,
    region character varying,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: ref_risk_scenarios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ref_risk_scenarios (
    id uuid NOT NULL,
    code character varying NOT NULL,
    name character varying NOT NULL,
    description text,
    category public.scenario_category NOT NULL,
    severity public.scenario_severity NOT NULL,
    criteria jsonb NOT NULL,
    risk_weight integer NOT NULL,
    active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason text,
    client_ip character varying(64),
    user_agent text
);


--
-- Name: risk_assessments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.risk_assessments (
    id uuid NOT NULL,
    tenant_id uuid,
    subject_type public.risk_subject_type NOT NULL,
    subject_ref character varying,
    subject_label character varying,
    total_score integer NOT NULL,
    risk_class public.risk_class NOT NULL,
    triggered jsonb NOT NULL,
    context jsonb NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    notes text
);


--
-- Name: sanctions_sync_meta; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sanctions_sync_meta (
    source_id text NOT NULL,
    source_name text NOT NULL,
    content_hash text NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: screening_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_matches (
    id bigint NOT NULL,
    request_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    source_record_id uuid,
    match_score integer NOT NULL,
    match_band public.match_band NOT NULL,
    reasons jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    tenant_id uuid DEFAULT (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid NOT NULL,
    CONSTRAINT screening_matches_match_score_check CHECK (((match_score >= 0) AND (match_score <= 100))),
    CONSTRAINT screening_matches_tenant_consistency CHECK ((tenant_id IS NOT NULL))
);


--
-- Name: screening_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.screening_matches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: screening_matches_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.screening_matches_id_seq OWNED BY public.screening_matches.id;


--
-- Name: screening_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_requests (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    client_id text,
    request_payload jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    case_id uuid,
    provider text DEFAULT 'INTERNAL'::text NOT NULL,
    triggered_by uuid,
    status text DEFAULT 'DONE'::text NOT NULL,
    completed_at timestamp with time zone,
    tenant_id uuid DEFAULT (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid NOT NULL
);


--
-- Name: screening_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screening_results (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    request_id uuid NOT NULL,
    risk_level public.risk_level NOT NULL,
    confidence integer NOT NULL,
    recommended_action public.action_type NOT NULL,
    decided_by text DEFAULT 'SYSTEM'::text NOT NULL,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    notes text,
    tenant_id uuid DEFAULT (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid NOT NULL,
    CONSTRAINT screening_results_confidence_check CHECK (((confidence >= 0) AND (confidence <= 100))),
    CONSTRAINT screening_results_tenant_consistency CHECK ((tenant_id IS NOT NULL))
);


--
-- Name: source_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_records (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    source_id smallint NOT NULL,
    source_ref text NOT NULL,
    entity_id uuid NOT NULL,
    record_type public.record_type NOT NULL,
    listed_on date,
    unlisted_on date,
    program text,
    summary text,
    evidence_urls text[],
    raw_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id smallint NOT NULL,
    source_code text NOT NULL,
    source_name text NOT NULL,
    source_type public.source_type NOT NULL,
    country text,
    refresh_policy text NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sources_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sources_id_seq OWNED BY public.sources.id;


--
-- Name: staging_screening_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staging_screening_records (
    batch_id uuid NOT NULL,
    source_code text NOT NULL,
    source_ref text NOT NULL,
    record_type public.record_type NOT NULL,
    primary_name text NOT NULL,
    aliases text[],
    dob date,
    nationalities text[],
    gender text,
    pob_country text,
    listed_on date,
    unlisted_on date,
    program text,
    summary text,
    evidence_urls text[],
    raw_payload jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_domains (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    domain text NOT NULL,
    is_verified boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant_invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_invitations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    tenant_id uuid NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: tenant_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_settings (
    tenant_id uuid NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    active_from timestamp with time zone,
    active_until timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tenants_status_check CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'SUSPENDED'::text, 'DISABLED'::text, 'EXPIRED'::text])))
);


--
-- Name: user_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_roles (
    user_id uuid NOT NULL,
    role public.user_role NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    email text NOT NULL,
    full_name text NOT NULL,
    password_hash text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tenant_id uuid NOT NULL,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    CONSTRAINT users_status_check CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'SUSPENDED'::text, 'DISABLED'::text])))
);


--
-- Name: case_status_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_status_history ALTER COLUMN id SET DEFAULT nextval('public.case_status_history_id_seq'::regclass);


--
-- Name: entity_names id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_names ALTER COLUMN id SET DEFAULT nextval('public.entity_names_id_seq'::regclass);


--
-- Name: provider_events id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_events ALTER COLUMN id SET DEFAULT nextval('public.provider_events_id_seq'::regclass);


--
-- Name: screening_matches id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches ALTER COLUMN id SET DEFAULT nextval('public.screening_matches_id_seq'::regclass);


--
-- Name: sources id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources ALTER COLUMN id SET DEFAULT nextval('public.sources_id_seq'::regclass);


--
-- Name: adverse_media_records adverse_media_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.adverse_media_records
    ADD CONSTRAINT adverse_media_records_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: alert_rules alert_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_pkey PRIMARY KEY (id);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: case_alerts case_alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_alerts
    ADD CONSTRAINT case_alerts_pkey PRIMARY KEY (id);


--
-- Name: case_entities case_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_entities
    ADD CONSTRAINT case_entities_pkey PRIMARY KEY (case_id, entity_id, role);


--
-- Name: case_exports case_exports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_exports
    ADD CONSTRAINT case_exports_pkey PRIMARY KEY (id);


--
-- Name: case_screening_decisions case_screening_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_screening_decisions
    ADD CONSTRAINT case_screening_decisions_pkey PRIMARY KEY (id);


--
-- Name: case_status_history case_status_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_status_history
    ADD CONSTRAINT case_status_history_pkey PRIMARY KEY (id);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: companies companies_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_entity_id_key UNIQUE (entity_id);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);


--
-- Name: company_people company_people_company_id_person_id_role_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_people
    ADD CONSTRAINT company_people_company_id_person_id_role_type_key UNIQUE (company_id, person_id, role_type);


--
-- Name: company_people company_people_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_people
    ADD CONSTRAINT company_people_pkey PRIMARY KEY (id);


--
-- Name: compliance_events compliance_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_events
    ADD CONSTRAINT compliance_events_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: entities entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (id);


--
-- Name: entity_names entity_names_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_names
    ADD CONSTRAINT entity_names_pkey PRIMARY KEY (id);


--
-- Name: external_identities external_identities_entity_id_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_entity_id_provider_key UNIQUE (entity_id, provider);


--
-- Name: external_identities external_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_pkey PRIMARY KEY (id);


--
-- Name: external_identities external_identities_provider_external_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_provider_external_id_key UNIQUE (provider, external_id);


--
-- Name: invitations invitations_email_tenant_active; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitations
    ADD CONSTRAINT invitations_email_tenant_active UNIQUE (tenant_id, email, revoked_at);


--
-- Name: invitations invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitations
    ADD CONSTRAINT invitations_pkey PRIMARY KEY (id);


--
-- Name: kyt_sars kyt_sars_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyt_sars
    ADD CONSTRAINT kyt_sars_pkey PRIMARY KEY (id);


--
-- Name: kyt_transactions kyt_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyt_transactions
    ADD CONSTRAINT kyt_transactions_pkey PRIMARY KEY (id);


--
-- Name: match_labels match_labels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.match_labels
    ADD CONSTRAINT match_labels_pkey PRIMARY KEY (request_id, entity_id);


--
-- Name: monitoring_jobs monitoring_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_jobs
    ADD CONSTRAINT monitoring_jobs_pkey PRIMARY KEY (id);


--
-- Name: name_stopwords name_stopwords_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.name_stopwords
    ADD CONSTRAINT name_stopwords_pkey PRIMARY KEY (country, token);


--
-- Name: person_attributes person_attributes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_attributes
    ADD CONSTRAINT person_attributes_pkey PRIMARY KEY (entity_id);


--
-- Name: persons persons_entity_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons
    ADD CONSTRAINT persons_entity_id_key UNIQUE (entity_id);


--
-- Name: persons persons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons
    ADD CONSTRAINT persons_pkey PRIMARY KEY (id);


--
-- Name: provider_events provider_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_events
    ADD CONSTRAINT provider_events_pkey PRIMARY KEY (id);


--
-- Name: rbac_roles rbac_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rbac_roles
    ADD CONSTRAINT rbac_roles_pkey PRIMARY KEY (id);


--
-- Name: rbac_user_roles rbac_user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rbac_user_roles
    ADD CONSTRAINT rbac_user_roles_pkey PRIMARY KEY (id);


--
-- Name: ref_business_sectors ref_business_sectors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ref_business_sectors
    ADD CONSTRAINT ref_business_sectors_pkey PRIMARY KEY (id);


--
-- Name: ref_client_categories ref_client_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ref_client_categories
    ADD CONSTRAINT ref_client_categories_pkey PRIMARY KEY (id);


--
-- Name: ref_countries ref_countries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ref_countries
    ADD CONSTRAINT ref_countries_pkey PRIMARY KEY (id);


--
-- Name: ref_currencies ref_currencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ref_currencies
    ADD CONSTRAINT ref_currencies_pkey PRIMARY KEY (id);


--
-- Name: ref_risk_scenarios ref_risk_scenarios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ref_risk_scenarios
    ADD CONSTRAINT ref_risk_scenarios_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);


--
-- Name: risk_assessments risk_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.risk_assessments
    ADD CONSTRAINT risk_assessments_pkey PRIMARY KEY (id);


--
-- Name: sanctions_sync_meta sanctions_sync_meta_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sanctions_sync_meta
    ADD CONSTRAINT sanctions_sync_meta_pkey PRIMARY KEY (source_id);


--
-- Name: screening_matches screening_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches
    ADD CONSTRAINT screening_matches_pkey PRIMARY KEY (id);


--
-- Name: screening_requests screening_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_requests
    ADD CONSTRAINT screening_requests_pkey PRIMARY KEY (id);


--
-- Name: screening_results screening_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_results
    ADD CONSTRAINT screening_results_pkey PRIMARY KEY (id);


--
-- Name: source_records source_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_pkey PRIMARY KEY (id);


--
-- Name: source_records source_records_source_id_source_ref_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_source_id_source_ref_key UNIQUE (source_id, source_ref);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: sources sources_source_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_source_code_key UNIQUE (source_code);


--
-- Name: tenant_domains tenant_domains_domain_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_domain_key UNIQUE (domain);


--
-- Name: tenant_domains tenant_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_pkey PRIMARY KEY (id);


--
-- Name: tenant_invitations tenant_invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invitations
    ADD CONSTRAINT tenant_invitations_pkey PRIMARY KEY (id);


--
-- Name: tenant_settings tenant_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_settings
    ADD CONSTRAINT tenant_settings_pkey PRIMARY KEY (tenant_id);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: tenants tenants_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_slug_key UNIQUE (slug);


--
-- Name: rbac_roles uq_rbac_roles_tenant_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rbac_roles
    ADD CONSTRAINT uq_rbac_roles_tenant_code UNIQUE (tenant_id, code);


--
-- Name: rbac_user_roles uq_rbac_user_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rbac_user_roles
    ADD CONSTRAINT uq_rbac_user_roles UNIQUE (tenant_id, user_id, role_code);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_audit_log_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_action ON public.audit_log USING btree (action);


--
-- Name: idx_audit_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_created ON public.audit_log USING btree (created_at);


--
-- Name: idx_audit_log_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_tenant ON public.audit_log USING btree (tenant_id);


--
-- Name: idx_case_alerts_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_alerts_case ON public.case_alerts USING btree (case_id, created_at DESC);


--
-- Name: idx_case_alerts_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_alerts_entity ON public.case_alerts USING btree (entity_id);


--
-- Name: idx_case_entities_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_entities_case ON public.case_entities USING btree (case_id);


--
-- Name: idx_case_entities_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_entities_entity ON public.case_entities USING btree (entity_id);


--
-- Name: idx_case_screening_decisions_case_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_screening_decisions_case_id ON public.case_screening_decisions USING btree (case_id, decided_at DESC);


--
-- Name: idx_case_screening_decisions_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_screening_decisions_request_id ON public.case_screening_decisions USING btree (request_id, decided_at DESC);


--
-- Name: idx_case_status_history_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_status_history_case ON public.case_status_history USING btree (case_id, created_at DESC);


--
-- Name: idx_cases_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_tenant_id ON public.cases USING btree (tenant_id);


--
-- Name: idx_companies_nif; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_companies_nif ON public.companies USING btree (nif);


--
-- Name: idx_companies_rccm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_companies_rccm ON public.companies USING btree (rccm);


--
-- Name: idx_documents_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_case ON public.documents USING btree (case_id, uploaded_at DESC);


--
-- Name: idx_documents_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_tenant_id ON public.documents USING btree (tenant_id);


--
-- Name: idx_entities_risk; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_risk ON public.entities USING btree (risk_level);


--
-- Name: idx_entities_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_type ON public.entities USING btree (entity_type);


--
-- Name: idx_entity_names_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_names_entity ON public.entity_names USING btree (entity_id);


--
-- Name: idx_entity_names_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_names_norm ON public.entity_names USING btree (name_normalized);


--
-- Name: idx_entity_names_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_names_normalized ON public.entity_names USING btree (name_normalized);


--
-- Name: idx_entity_names_tokens_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_names_tokens_gin ON public.entity_names USING gin (name_tokens);


--
-- Name: idx_entity_names_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entity_names_trgm ON public.entity_names USING gin (name_normalized public.gin_trgm_ops);


--
-- Name: idx_external_identities_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_external_identities_entity ON public.external_identities USING btree (entity_id);


--
-- Name: idx_external_identities_provider_ext; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_external_identities_provider_ext ON public.external_identities USING btree (provider, external_id);


--
-- Name: idx_invitations_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invitations_email ON public.invitations USING btree (email);


--
-- Name: idx_invitations_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invitations_expires ON public.invitations USING btree (expires_at);


--
-- Name: idx_invitations_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_invitations_tenant ON public.invitations USING btree (tenant_id);


--
-- Name: idx_matches_request; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_matches_request ON public.screening_matches USING btree (request_id);


--
-- Name: idx_matches_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_matches_score ON public.screening_matches USING btree (match_score DESC);


--
-- Name: idx_monitoring_next_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_monitoring_next_run ON public.monitoring_jobs USING btree (next_run_at) WHERE (is_active = true);


--
-- Name: idx_person_dob; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_person_dob ON public.person_attributes USING btree (dob);


--
-- Name: idx_person_nat_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_person_nat_gin ON public.person_attributes USING gin (nationalities);


--
-- Name: idx_provider_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_events_event_type ON public.provider_events USING btree (event_type);


--
-- Name: idx_provider_events_external; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_events_external ON public.provider_events USING btree (provider, external_id);


--
-- Name: idx_provider_events_provider_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_events_provider_time ON public.provider_events USING btree (provider, received_at DESC);


--
-- Name: idx_screening_matches_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_matches_tenant_id ON public.screening_matches USING btree (tenant_id);


--
-- Name: idx_screening_requests_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_requests_case ON public.screening_requests USING btree (case_id, created_at DESC);


--
-- Name: idx_screening_requests_provider; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_requests_provider ON public.screening_requests USING btree (provider);


--
-- Name: idx_screening_requests_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_requests_tenant_id ON public.screening_requests USING btree (tenant_id);


--
-- Name: idx_screening_requests_triggered_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_requests_triggered_by ON public.screening_requests USING btree (triggered_by);


--
-- Name: idx_screening_requests_triggered_by_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_requests_triggered_by_created_at ON public.screening_requests USING btree (triggered_by, created_at DESC);


--
-- Name: idx_screening_results_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_screening_results_tenant_id ON public.screening_results USING btree (tenant_id);


--
-- Name: idx_source_records_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_records_entity ON public.source_records USING btree (entity_id);


--
-- Name: idx_source_records_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_records_source ON public.source_records USING btree (source_id);


--
-- Name: idx_source_records_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_records_type ON public.source_records USING btree (record_type);


--
-- Name: idx_staging_batch; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staging_batch ON public.staging_screening_records USING btree (batch_id);


--
-- Name: idx_staging_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staging_source ON public.staging_screening_records USING btree (source_code);


--
-- Name: idx_tenant_domains_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_domains_tenant_id ON public.tenant_domains USING btree (tenant_id);


--
-- Name: idx_tenants_active_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenants_active_until ON public.tenants USING btree (active_until);


--
-- Name: idx_tenants_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenants_status ON public.tenants USING btree (status);


--
-- Name: idx_users_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_tenant_id ON public.users USING btree (tenant_id);


--
-- Name: ix_adverse_media_records_normalized_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_adverse_media_records_normalized_name ON public.adverse_media_records USING btree (normalized_name);


--
-- Name: ix_alert_rules_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_alert_rules_code ON public.alert_rules USING btree (code);


--
-- Name: ix_alerts_rule_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_rule_code ON public.alerts USING btree (rule_code);


--
-- Name: ix_alerts_subject_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_subject_ref ON public.alerts USING btree (subject_ref);


--
-- Name: ix_alerts_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alerts_tenant_id ON public.alerts USING btree (tenant_id);


--
-- Name: ix_cases_sumsub_applicant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cases_sumsub_applicant_id ON public.cases USING btree (sumsub_applicant_id);


--
-- Name: ix_compliance_events_alert_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compliance_events_alert_id ON public.compliance_events USING btree (alert_id);


--
-- Name: ix_compliance_events_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compliance_events_subject_id ON public.compliance_events USING btree (subject_id);


--
-- Name: ix_compliance_events_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compliance_events_tenant_id ON public.compliance_events USING btree (tenant_id);


--
-- Name: ix_kyt_sars_subject_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kyt_sars_subject_ref ON public.kyt_sars USING btree (subject_ref);


--
-- Name: ix_kyt_sars_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kyt_sars_tenant_id ON public.kyt_sars USING btree (tenant_id);


--
-- Name: ix_kyt_transactions_customer_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kyt_transactions_customer_ref ON public.kyt_transactions USING btree (customer_ref);


--
-- Name: ix_kyt_transactions_external_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kyt_transactions_external_ref ON public.kyt_transactions USING btree (external_ref);


--
-- Name: ix_kyt_transactions_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_kyt_transactions_tenant_id ON public.kyt_transactions USING btree (tenant_id);


--
-- Name: ix_rbac_roles_code; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rbac_roles_code ON public.rbac_roles USING btree (code);


--
-- Name: ix_rbac_roles_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rbac_roles_tenant_id ON public.rbac_roles USING btree (tenant_id);


--
-- Name: ix_rbac_user_roles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_rbac_user_roles_user_id ON public.rbac_user_roles USING btree (user_id);


--
-- Name: ix_ref_business_sectors_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ref_business_sectors_code ON public.ref_business_sectors USING btree (code);


--
-- Name: ix_ref_client_categories_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ref_client_categories_code ON public.ref_client_categories USING btree (code);


--
-- Name: ix_ref_countries_iso_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ref_countries_iso_code ON public.ref_countries USING btree (iso_code);


--
-- Name: ix_ref_currencies_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ref_currencies_code ON public.ref_currencies USING btree (code);


--
-- Name: ix_ref_risk_scenarios_code; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_ref_risk_scenarios_code ON public.ref_risk_scenarios USING btree (code);


--
-- Name: ix_refresh_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);


--
-- Name: ix_risk_assessments_subject_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_subject_ref ON public.risk_assessments USING btree (subject_ref);


--
-- Name: ix_risk_assessments_tenant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_risk_assessments_tenant_id ON public.risk_assessments USING btree (tenant_id);


--
-- Name: uniq_invite_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uniq_invite_email ON public.tenant_invitations USING btree (tenant_id, email) WHERE (accepted_at IS NULL);


--
-- Name: uq_entities_source; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_entities_source ON public.entities USING btree (source_name, source_id) WHERE ((source_name IS NOT NULL) AND (source_id IS NOT NULL));


--
-- Name: uq_provider_events_dedupe; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_provider_events_dedupe ON public.provider_events USING btree (provider, provider_event_id) WHERE (provider_event_id IS NOT NULL);


--
-- Name: ux_cases_sumsub_applicant_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_cases_sumsub_applicant_id ON public.cases USING btree (sumsub_applicant_id) WHERE (sumsub_applicant_id IS NOT NULL);


--
-- Name: tenants trg_tenants_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tenants_updated_at BEFORE UPDATE ON public.tenants FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: audit_log audit_log_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);


--
-- Name: audit_log audit_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: case_alerts case_alerts_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_alerts
    ADD CONSTRAINT case_alerts_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_alerts case_alerts_decided_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_alerts
    ADD CONSTRAINT case_alerts_decided_by_fkey FOREIGN KEY (decided_by) REFERENCES public.users(id);


--
-- Name: case_alerts case_alerts_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_alerts
    ADD CONSTRAINT case_alerts_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: case_entities case_entities_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_entities
    ADD CONSTRAINT case_entities_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_entities case_entities_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_entities
    ADD CONSTRAINT case_entities_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: case_exports case_exports_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_exports
    ADD CONSTRAINT case_exports_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_exports case_exports_generated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_exports
    ADD CONSTRAINT case_exports_generated_by_fkey FOREIGN KEY (generated_by) REFERENCES public.users(id);


--
-- Name: case_status_history case_status_history_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_status_history
    ADD CONSTRAINT case_status_history_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);


--
-- Name: case_status_history case_status_history_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_status_history
    ADD CONSTRAINT case_status_history_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: cases cases_assigned_checker_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_assigned_checker_fkey FOREIGN KEY (assigned_checker) REFERENCES public.users(id);


--
-- Name: cases cases_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cases cases_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: companies companies_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: company_people company_people_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_people
    ADD CONSTRAINT company_people_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_people company_people_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_people
    ADD CONSTRAINT company_people_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: documents documents_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: documents documents_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: documents documents_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);


--
-- Name: entity_names entity_names_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_names
    ADD CONSTRAINT entity_names_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: external_identities external_identities_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.external_identities
    ADD CONSTRAINT external_identities_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: invitations invitations_accepted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitations
    ADD CONSTRAINT invitations_accepted_by_fkey FOREIGN KEY (accepted_by) REFERENCES public.users(id);


--
-- Name: invitations invitations_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invitations
    ADD CONSTRAINT invitations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: monitoring_jobs monitoring_jobs_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.monitoring_jobs
    ADD CONSTRAINT monitoring_jobs_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: person_attributes person_attributes_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_attributes
    ADD CONSTRAINT person_attributes_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: persons persons_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons
    ADD CONSTRAINT persons_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: screening_matches screening_matches_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches
    ADD CONSTRAINT screening_matches_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id);


--
-- Name: screening_matches screening_matches_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches
    ADD CONSTRAINT screening_matches_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.screening_requests(id) ON DELETE CASCADE;


--
-- Name: screening_matches screening_matches_source_record_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches
    ADD CONSTRAINT screening_matches_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES public.source_records(id);


--
-- Name: screening_matches screening_matches_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_matches
    ADD CONSTRAINT screening_matches_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: screening_requests screening_requests_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_requests
    ADD CONSTRAINT screening_requests_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE SET NULL;


--
-- Name: screening_requests screening_requests_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_requests
    ADD CONSTRAINT screening_requests_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: screening_requests screening_requests_triggered_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_requests
    ADD CONSTRAINT screening_requests_triggered_by_fkey FOREIGN KEY (triggered_by) REFERENCES public.users(id);


--
-- Name: screening_results screening_results_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_results
    ADD CONSTRAINT screening_results_request_id_fkey FOREIGN KEY (request_id) REFERENCES public.screening_requests(id) ON DELETE CASCADE;


--
-- Name: screening_results screening_results_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screening_results
    ADD CONSTRAINT screening_results_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: source_records source_records_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_entity_id_fkey FOREIGN KEY (entity_id) REFERENCES public.entities(id) ON DELETE CASCADE;


--
-- Name: source_records source_records_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_records
    ADD CONSTRAINT source_records_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id);


--
-- Name: tenant_domains tenant_domains_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domains
    ADD CONSTRAINT tenant_domains_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: tenant_invitations tenant_invitations_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invitations
    ADD CONSTRAINT tenant_invitations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: tenant_invitations tenant_invitations_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_invitations
    ADD CONSTRAINT tenant_invitations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);


--
-- Name: case_screening_decisions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.case_screening_decisions ENABLE ROW LEVEL SECURITY;

--
-- Name: cases; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.cases ENABLE ROW LEVEL SECURITY;

--
-- Name: case_screening_decisions csd_app_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY csd_app_insert ON public.case_screening_decisions FOR INSERT TO screening_app WITH CHECK ((EXISTS ( SELECT 1
   FROM public.cases c
  WHERE (c.id = case_screening_decisions.case_id))));


--
-- Name: case_screening_decisions csd_app_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY csd_app_read ON public.case_screening_decisions FOR SELECT TO screening_app USING ((EXISTS ( SELECT 1
   FROM public.cases c
  WHERE (c.id = case_screening_decisions.case_id))));


--
-- Name: case_screening_decisions csd_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY csd_insert ON public.case_screening_decisions FOR INSERT TO screening_app WITH CHECK (true);


--
-- Name: case_screening_decisions csd_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY csd_read ON public.case_screening_decisions FOR SELECT TO screening_app USING (true);


--
-- Name: documents; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;

--
-- Name: screening_matches; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.screening_matches ENABLE ROW LEVEL SECURITY;

--
-- Name: screening_requests; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.screening_requests ENABLE ROW LEVEL SECURITY;

--
-- Name: screening_requests screening_requests_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY screening_requests_insert ON public.screening_requests FOR INSERT WITH CHECK (((current_setting('app.is_super_admin'::text, true) = 'true'::text) OR ((tenant_id)::text = current_setting('app.tenant_id'::text, true))));


--
-- Name: screening_requests screening_requests_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY screening_requests_select ON public.screening_requests FOR SELECT USING (((current_setting('app.is_super_admin'::text, true) = 'true'::text) OR ((tenant_id)::text = current_setting('app.tenant_id'::text, true))));


--
-- Name: screening_results; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.screening_results ENABLE ROW LEVEL SECURITY;

--
-- Name: cases tenant_cases_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_cases_insert ON public.cases FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: cases tenant_cases_select; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_cases_select ON public.cases FOR SELECT USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: cases tenant_cases_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_cases_update ON public.cases FOR UPDATE USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)) WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: documents tenant_documents_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_documents_insert ON public.documents FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: documents tenant_documents_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_documents_update ON public.documents FOR UPDATE WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: documents tenant_isolation_documents; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_documents ON public.documents USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_matches tenant_isolation_screening_matches; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_screening_matches ON public.screening_matches USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_requests tenant_isolation_screening_requests; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_screening_requests ON public.screening_requests USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_results tenant_isolation_screening_results; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_screening_results ON public.screening_results USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: users tenant_isolation_users; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_isolation_users ON public.users USING ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_matches tenant_screening_matches_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_matches_insert ON public.screening_matches FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_matches tenant_screening_matches_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_matches_update ON public.screening_matches FOR UPDATE WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_matches tenant_screening_matches_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_matches_write ON public.screening_matches FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_results tenant_screening_results_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_results_insert ON public.screening_results FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_results tenant_screening_results_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_results_update ON public.screening_results FOR UPDATE WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: screening_results tenant_screening_results_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_screening_results_write ON public.screening_results FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: users tenant_users_insert; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_users_insert ON public.users FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: users tenant_users_update; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_users_update ON public.users FOR UPDATE WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: users tenant_users_write; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY tenant_users_write ON public.users FOR INSERT WITH CHECK ((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid));


--
-- Name: users; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict RAFoyYQpl1U7s58D4YGbAOhALX4QHX18FGzsMOu4YE77E6RHxZDeBh3LjSM1m5b

