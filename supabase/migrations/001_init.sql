-- Study Helper schema for Supabase (PostgreSQL)
-- Covers Option A (mastery), Option B (live dashboard), Option C (planner)

create extension if not exists pgcrypto;

-- ----------
-- Enums
-- ----------
create type importance_level as enum ('low', 'medium', 'high');
create type question_difficulty as enum ('basic', 'intermediate', 'advanced');
create type question_format as enum ('mcq', 'open_ended');
create type question_intent as enum ('concept', 'application');
create type session_kind as enum ('quiz', 'study', 'review');

-- ----------
-- Core learning structure
-- ----------
create table if not exists main_topics (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  description text,
  importance importance_level not null default 'medium',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, title)
);

create table if not exists subtopics (
  id uuid primary key default gen_random_uuid(),
  main_topic_id uuid not null references main_topics(id) on delete cascade,
  title text not null,
  description text,
  exam_weight numeric(5,2) not null default 1.0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (main_topic_id, title)
);

create index if not exists idx_subtopics_main_topic_id on subtopics(main_topic_id);

create table if not exists notes (
  id uuid primary key default gen_random_uuid(),
  subtopic_id uuid not null references subtopics(id) on delete cascade,
  parent_note_id uuid references notes(id) on delete cascade,
  title text not null,
  body_md text not null,
  source_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_notes_subtopic_id on notes(subtopic_id);
create index if not exists idx_notes_parent_note_id on notes(parent_note_id);

-- ----------
-- Question bank + quiz runs
-- ----------
create table if not exists questions (
  id uuid primary key default gen_random_uuid(),
  subtopic_id uuid not null references subtopics(id) on delete cascade,
  prompt text not null,
  difficulty question_difficulty not null,
  format question_format not null,
  intent question_intent not null,
  expected_seconds integer,
  weight numeric(5,2) generated always as (
    case difficulty
      when 'basic' then 1.0
      when 'intermediate' then 1.5
      when 'advanced' then 2.0
    end
  ) stored,
  created_by text not null default 'system',
  created_at timestamptz not null default now()
);

create index if not exists idx_questions_subtopic_id on questions(subtopic_id);
create index if not exists idx_questions_profile on questions(subtopic_id, difficulty, format, intent);

create table if not exists quiz_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  main_topic_id uuid references main_topics(id) on delete set null,
  session_type session_kind not null default 'quiz',
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  exam_date date,
  hours_left_to_exam numeric(8,2),
  created_at timestamptz not null default now()
);

create index if not exists idx_quiz_sessions_user_id on quiz_sessions(user_id, started_at desc);

create table if not exists quiz_session_questions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references quiz_sessions(id) on delete cascade,
  question_id uuid not null references questions(id) on delete restrict,
  position integer not null,
  max_attempts integer not null,
  allocated_seconds integer,
  unique (session_id, position),
  unique (session_id, question_id)
);

create index if not exists idx_qsq_session_id on quiz_session_questions(session_id);

create table if not exists question_attempts (
  id uuid primary key default gen_random_uuid(),
  session_question_id uuid not null references quiz_session_questions(id) on delete cascade,
  attempt_no integer not null check (attempt_no > 0),
  submitted_answer text,
  is_correct boolean not null,
  rubric_score numeric(6,4) check (rubric_score between 0 and 1),
  answered_at timestamptz not null default now(),
  response_seconds integer not null check (response_seconds >= 0),
  ai_feedback text,
  unique (session_question_id, attempt_no)
);

create index if not exists idx_attempts_session_question_id on question_attempts(session_question_id);
create index if not exists idx_attempts_speed_correct on question_attempts(is_correct, response_seconds);

-- ----------
-- Mastery, confidence and forgetting-decay support
-- ----------
create table if not exists subtopic_mastery_snapshots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  subtopic_id uuid not null references subtopics(id) on delete cascade,
  snapshot_at timestamptz not null default now(),
  attempts_sample_size integer not null check (attempts_sample_size >= 0),
  weighted_accuracy numeric(6,4) not null check (weighted_accuracy between 0 and 1),
  speed_score numeric(6,4) not null check (speed_score between 0 and 1),
  mastery_score numeric(6,4) not null check (mastery_score between 0 and 1),
  confidence_score numeric(6,4) not null check (confidence_score between 0 and 1),
  confidence_band text not null check (confidence_band in ('not_trusted', 'somewhat_reliable', 'very_reliable')),
  decay_factor numeric(6,4) not null default 1.0 check (decay_factor between 0 and 1),
  adjusted_mastery numeric(6,4) not null check (adjusted_mastery between 0 and 1)
);

create index if not exists idx_mastery_user_subtopic_time
  on subtopic_mastery_snapshots(user_id, subtopic_id, snapshot_at desc);

-- ----------
-- Error pattern & dashboard telemetry
-- ----------
create table if not exists attempt_analysis (
  id uuid primary key default gen_random_uuid(),
  question_attempt_id uuid not null unique references question_attempts(id) on delete cascade,
  speed_bucket text not null check (speed_bucket in ('fast', 'slow')),
  tries_to_correct integer not null check (tries_to_correct between 0 and 2),
  analysis_label text not null,
  created_at timestamptz not null default now()
);

create table if not exists study_activity_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  subtopic_id uuid references subtopics(id) on delete set null,
  session_id uuid references quiz_sessions(id) on delete set null,
  event_type text not null,
  event_payload jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists idx_activity_user_time on study_activity_events(user_id, occurred_at desc);

-- ----------
-- Planning (Option C)
-- ----------
create table if not exists study_planning_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  exam_date date,
  hours_available_total numeric(8,2),
  study_style text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists subtopic_improvement_models (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  subtopic_id uuid not null references subtopics(id) on delete cascade,
  estimated_gain_per_hour numeric(6,4) not null check (estimated_gain_per_hour >= 0),
  source text not null check (source in ('user_history', 'global_default', 'manual_override')),
  last_practiced_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, subtopic_id)
);

create index if not exists idx_improvement_user_subtopic on subtopic_improvement_models(user_id, subtopic_id);

-- ----------
-- Useful views for reporting
-- ----------
create or replace view v_main_topic_strength_report as
select
  mt.user_id,
  mt.id as main_topic_id,
  mt.title as main_topic_title,
  avg(sms.adjusted_mastery) as avg_adjusted_mastery,
  min(sms.adjusted_mastery) as weakest_subtopic_score,
  max(sms.adjusted_mastery) as strongest_subtopic_score,
  avg(sms.confidence_score) as avg_confidence
from main_topics mt
join subtopics st on st.main_topic_id = mt.id
join lateral (
  select x.*
  from subtopic_mastery_snapshots x
  where x.subtopic_id = st.id
  and x.user_id = mt.user_id
  order by x.snapshot_at desc
  limit 1
) sms on true
group by mt.user_id, mt.id, mt.title;

create or replace view v_subtopic_latest_mastery as
select distinct on (sms.user_id, sms.subtopic_id)
  sms.user_id,
  sms.subtopic_id,
  sms.snapshot_at,
  sms.mastery_score,
  sms.confidence_score,
  sms.confidence_band,
  sms.decay_factor,
  sms.adjusted_mastery
from subtopic_mastery_snapshots sms
order by sms.user_id, sms.subtopic_id, sms.snapshot_at desc;

create or replace view v_study_priority_queue as
select
  sim.user_id,
  sim.subtopic_id,
  st.main_topic_id,
  coalesce(vlm.adjusted_mastery, 0) as adjusted_mastery,
  st.exam_weight,
  sim.estimated_gain_per_hour,
  greatest(extract(epoch from (now() - coalesce(sim.last_practiced_at, now() - interval '30 days'))) / 86400.0, 0) as days_since_last_practice,
  (
    st.exam_weight
    * (1 - coalesce(vlm.adjusted_mastery, 0))
    * sim.estimated_gain_per_hour
    * (1 + least(greatest(extract(epoch from (now() - coalesce(sim.last_practiced_at, now() - interval '30 days'))) / 86400.0, 0), 30) / 30.0)
  ) as priority_score
from subtopic_improvement_models sim
join subtopics st on st.id = sim.subtopic_id
left join v_subtopic_latest_mastery vlm
  on vlm.user_id = sim.user_id and vlm.subtopic_id = sim.subtopic_id;

-- ----------
-- Trigger: keep updated_at fresh
-- ----------
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_main_topics_updated_at on main_topics;
create trigger trg_main_topics_updated_at
before update on main_topics
for each row execute function set_updated_at();

drop trigger if exists trg_subtopics_updated_at on subtopics;
create trigger trg_subtopics_updated_at
before update on subtopics
for each row execute function set_updated_at();

drop trigger if exists trg_notes_updated_at on notes;
create trigger trg_notes_updated_at
before update on notes
for each row execute function set_updated_at();

drop trigger if exists trg_study_planning_profiles_updated_at on study_planning_profiles;
create trigger trg_study_planning_profiles_updated_at
before update on study_planning_profiles
for each row execute function set_updated_at();

drop trigger if exists trg_subtopic_improvement_models_updated_at on subtopic_improvement_models;
create trigger trg_subtopic_improvement_models_updated_at
before update on subtopic_improvement_models
for each row execute function set_updated_at();

-- ----------
-- Optional RLS baseline (enable + own-row policies)
-- ----------
alter table main_topics enable row level security;
alter table subtopics enable row level security;
alter table notes enable row level security;
alter table questions enable row level security;
alter table quiz_sessions enable row level security;
alter table quiz_session_questions enable row level security;
alter table question_attempts enable row level security;
alter table subtopic_mastery_snapshots enable row level security;
alter table attempt_analysis enable row level security;
alter table study_activity_events enable row level security;
alter table study_planning_profiles enable row level security;
alter table subtopic_improvement_models enable row level security;

drop policy if exists "main_topics_owner" on main_topics;
create policy "main_topics_owner"
on main_topics
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "quiz_sessions_owner" on quiz_sessions;
create policy "quiz_sessions_owner"
on quiz_sessions
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "mastery_owner" on subtopic_mastery_snapshots;
create policy "mastery_owner"
on subtopic_mastery_snapshots
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "activity_owner" on study_activity_events;
create policy "activity_owner"
on study_activity_events
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "planning_owner" on study_planning_profiles;
create policy "planning_owner"
on study_planning_profiles
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "improvement_owner" on subtopic_improvement_models;
create policy "improvement_owner"
on subtopic_improvement_models
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "subtopics_owner_via_main_topic" on subtopics;
create policy "subtopics_owner_via_main_topic"
on subtopics
for all
using (
  exists (
    select 1 from main_topics mt
    where mt.id = subtopics.main_topic_id
    and mt.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1 from main_topics mt
    where mt.id = subtopics.main_topic_id
    and mt.user_id = auth.uid()
  )
);

drop policy if exists "notes_owner_via_subtopic" on notes;
create policy "notes_owner_via_subtopic"
on notes
for all
using (
  exists (
    select 1
    from subtopics st
    join main_topics mt on mt.id = st.main_topic_id
    where st.id = notes.subtopic_id
    and mt.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from subtopics st
    join main_topics mt on mt.id = st.main_topic_id
    where st.id = notes.subtopic_id
    and mt.user_id = auth.uid()
  )
);

drop policy if exists "questions_owner_via_subtopic" on questions;
create policy "questions_owner_via_subtopic"
on questions
for all
using (
  exists (
    select 1
    from subtopics st
    join main_topics mt on mt.id = st.main_topic_id
    where st.id = questions.subtopic_id
    and mt.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from subtopics st
    join main_topics mt on mt.id = st.main_topic_id
    where st.id = questions.subtopic_id
    and mt.user_id = auth.uid()
  )
);

drop policy if exists "quiz_session_questions_owner_via_session" on quiz_session_questions;
create policy "quiz_session_questions_owner_via_session"
on quiz_session_questions
for all
using (
  exists (
    select 1 from quiz_sessions qs
    where qs.id = quiz_session_questions.session_id
    and qs.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1 from quiz_sessions qs
    where qs.id = quiz_session_questions.session_id
    and qs.user_id = auth.uid()
  )
);

drop policy if exists "attempts_owner_via_session_question" on question_attempts;
create policy "attempts_owner_via_session_question"
on question_attempts
for all
using (
  exists (
    select 1
    from quiz_session_questions qsq
    join quiz_sessions qs on qs.id = qsq.session_id
    where qsq.id = question_attempts.session_question_id
    and qs.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from quiz_session_questions qsq
    join quiz_sessions qs on qs.id = qsq.session_id
    where qsq.id = question_attempts.session_question_id
    and qs.user_id = auth.uid()
  )
);

drop policy if exists "attempt_analysis_owner_via_attempt" on attempt_analysis;
create policy "attempt_analysis_owner_via_attempt"
on attempt_analysis
for all
using (
  exists (
    select 1
    from question_attempts qa
    join quiz_session_questions qsq on qsq.id = qa.session_question_id
    join quiz_sessions qs on qs.id = qsq.session_id
    where qa.id = attempt_analysis.question_attempt_id
    and qs.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1
    from question_attempts qa
    join quiz_session_questions qsq on qsq.id = qa.session_question_id
    join quiz_sessions qs on qs.id = qsq.session_id
    where qa.id = attempt_analysis.question_attempt_id
    and qs.user_id = auth.uid()
  )
);
