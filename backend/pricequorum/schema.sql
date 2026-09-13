-- PriceQuorum schema. Every statement is idempotent so it runs on each startup.

create table if not exists runs (
  id            uuid primary key default gen_random_uuid(),
  request_text  text not null,
  change_key    text,
  plan_key      text,
  currency      text,
  interval      text,
  status        text not null default 'running'
                check (status in ('running', 'awaiting_human', 'done', 'refused', 'failed')),
  outcome       text check (outcome in ('SUCCESS', 'PARTIAL', 'REFUSED', 'NEEDS_HUMAN')),
  remedy        text,
  approval_mode text not null default 'slack',
  scenario      text,
  last_seq      int not null default 0,
  invariants_expected jsonb not null default '[]'::jsonb,
  created_at    timestamptz not null default now(),
  finished_at   timestamptz
);

create table if not exists run_events (
  run_id  uuid not null references runs(id),
  seq     int not null,
  type    text not null,
  payload jsonb not null,
  at      timestamptz not null default now(),
  primary key (run_id, seq)
);

create table if not exists action_ledger (
  id                     bigint generated always as identity primary key,
  run_id                 uuid not null references runs(id),
  step_no                int not null,
  app                    text not null,
  action                 text not null,
  idempotency_key        text not null unique,
  args_hash              text not null,
  state                  text not null default 'pending'
                         check (state in ('pending', 'completed', 'failed', 'compensated')),
  external_object_id     text,
  expected_postcondition jsonb not null default '{}'::jsonb,
  outcome                text,
  remedy                 text,
  chain_id               bigint,
  duplicates_prevented   int not null default 0,
  created_at             timestamptz not null default now(),
  completed_at           timestamptz
);
create index if not exists action_ledger_run on action_ledger (run_id, step_no);

-- The hash chain, appended in completion order. Verification walks it by id.
create table if not exists ledger_chain (
  id          bigint generated always as identity primary key,
  run_id      uuid,
  payload     jsonb not null,
  prev_hash   text not null,
  entry_hash  text not null,
  created_at  timestamptz not null default now()
);

create table if not exists approvals (
  id                bigint generated always as identity primary key,
  run_id            uuid not null unique references runs(id),
  action            text not null,
  args_hash         text not null,
  summary           text not null,
  mode              text not null check (mode in ('slack', 'operator', 'sandbox_auto')),
  status            text not null default 'PENDING' check (status in ('PENDING', 'APPROVED', 'DENIED', 'EXPIRED')),
  approver_display  text,
  slack_channel     text,
  slack_ts          text,
  expires_at        timestamptz not null,
  decided_at        timestamptz,
  created_at        timestamptz not null default now()
);

create table if not exists entity_resolution (
  id                 bigint generated always as identity primary key,
  run_id             uuid references runs(id),
  plan_key           text,
  stripe_product_id  text,
  stripe_price_id    text,
  notion_page_id     text,
  airtable_record_id text,
  confidence         int,
  decided_by         text,
  candidates         jsonb not null default '[]'::jsonb
);

create table if not exists eval_scenarios (
  id                 text primary key,
  description        text not null,
  seed               jsonb not null default '{}'::jsonb,
  request            text not null,
  faults             jsonb,
  expected_outcome   text not null check (expected_outcome in ('SUCCESS', 'PARTIAL', 'REFUSED', 'NEEDS_HUMAN')),
  expected_end_state jsonb not null default '{}'::jsonb
);

create table if not exists eval_results (
  id                 bigint generated always as identity primary key,
  batch_id           uuid not null,
  scenario_id        text references eval_scenarios(id),
  run_id             uuid,
  passed             boolean not null,
  observed_outcome   text,
  observed_end_state jsonb,
  detail             text,
  commit_sha         text,
  ran_at             timestamptz not null default now()
);
alter table eval_results add column if not exists duplicate_writes_prevented int not null default 0;
alter table eval_results add column if not exists forbidden_refused int not null default 0;
alter table eval_results add column if not exists forbidden_attempted int not null default 0;
create index if not exists eval_results_batch on eval_results (batch_id);
-- A detection scenario (chain_tamper) starts no run, so it has no expected run outcome.
alter table eval_scenarios alter column expected_outcome drop not null;

-- Sandbox and heal runs may only change this plan; the orchestrator refuses any other resolution.
alter table runs add column if not exists plan_scope text;

-- The ledger signing key lives here when PQ_SIGNING_KEY is not set, so it survives restarts
-- on hosts without a persistent disk. See pricequorum/ledger.py for the tradeoff.
create table if not exists signing_keys (
  id         int primary key default 1 check (id = 1),
  seed_hex   text not null,
  created_at timestamptz not null default now()
);
