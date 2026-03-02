-- Demo seed script
-- Replace __USER_ID__ with an actual auth.users id from your Supabase project.

-- Example:
-- select id, email from auth.users order by created_at desc limit 5;

insert into main_topics (user_id, title, description, importance)
values
  ('__USER_ID__', 'Calculus', 'Core derivatives and integration topics', 'high'),
  ('__USER_ID__', 'Linear Algebra', 'Vector spaces and transformations', 'medium')
on conflict (user_id, title) do nothing;

with calc as (
  select id from main_topics where user_id = '__USER_ID__' and title = 'Calculus'
),
lin as (
  select id from main_topics where user_id = '__USER_ID__' and title = 'Linear Algebra'
)
insert into subtopics (main_topic_id, title, description, exam_weight)
values
  ((select id from calc), 'Limits', 'Limit laws and continuity', 1.5),
  ((select id from calc), 'Differentiation', 'Derivative rules and applications', 2.0),
  ((select id from lin), 'Vectors', 'Vector operations and geometry', 1.2),
  ((select id from lin), 'Eigenvalues', 'Eigen decomposition and interpretation', 1.6)
on conflict (main_topic_id, title) do nothing;

-- Add 6 balanced questions for one subtopic
with target as (
  select id from subtopics
  where title = 'Limits'
  and main_topic_id in (select id from main_topics where user_id = '__USER_ID__' and title = 'Calculus')
  limit 1
)
insert into questions (subtopic_id, prompt, difficulty, format, intent, expected_seconds)
values
  ((select id from target), 'Evaluate lim x->2 (x^2 - 4)/(x - 2).', 'basic', 'mcq', 'concept', 90),
  ((select id from target), 'State epsilon-delta intuition for continuity at a point.', 'basic', 'open_ended', 'concept', 180),
  ((select id from target), 'Find lim x->0 sin(3x)/x.', 'intermediate', 'mcq', 'application', 120),
  ((select id from target), 'Explain why one-sided limits matter in piecewise functions.', 'intermediate', 'open_ended', 'concept', 210),
  ((select id from target), 'Compute lim x->infinity (2x^2 + 3)/(x^2 - 1).', 'advanced', 'mcq', 'application', 150),
  ((select id from target), 'Give a real-world interpretation of asymptotic behavior.', 'advanced', 'open_ended', 'application', 240)
on conflict do nothing;
