"""Core server tables (spec §5.1). Server DB only: skipped with `-x db=kb`.

Column types follow spec §5.1. Extra internal columns are marked "internal".

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""
from alembic import context, op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

EPISODE_STATUS = "('received','reading','read_failed','judged','notified','held','closed','paused_skip')"
LINE_STATE = (
    "('held','scheduled','running','done','partial','failed','unknown','blocked',"
    "'user_changed','off','stopped','cancelled','dropped')"
)

TABLES = [
    """
    CREATE TABLE households (
        id               text PRIMARY KEY,
        household_types  text[] NOT NULL DEFAULT '{}',
        paused           boolean NOT NULL DEFAULT false,
        hub_key_hash     text NOT NULL UNIQUE,
        created_at       timestamptz NOT NULL DEFAULT now(),
        updated_at       timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE device_lists (
        household_id  text PRIMARY KEY REFERENCES households(id) ON DELETE CASCADE,
        revision      integer NOT NULL,
        body          jsonb NOT NULL,
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE calendar_events (
        household_id  text NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        id            text NOT NULL,
        start         timestamptz NOT NULL,
        "end"         timestamptz NOT NULL,
        tags          text[] NOT NULL DEFAULT '{}',
        tagged        boolean NOT NULL DEFAULT false,
        fingerprint   text NOT NULL,
        updated_at    timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (household_id, id)
    )
    """,
    """
    CREATE TABLE calendar_revisions (
        household_id  text PRIMARY KEY REFERENCES households(id) ON DELETE CASCADE,
        revision      integer NOT NULL DEFAULT 0
    )
    """,
    f"""
    CREATE TABLE episodes (
        id                 text PRIMARY KEY,
        household_id       text NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        status             text NOT NULL CHECK (status IN {EPISODE_STATUS}),
        shared_at          timestamptz NOT NULL,
        received_at        timestamptz NOT NULL,
        source_ids         text[] NOT NULL DEFAULT '{{}}',
        judged             boolean NOT NULL DEFAULT false,
        stage              text CHECK (stage IN ('s1','s2','s5','done')),
        quiet_due          timestamptz,
        plan_version       integer NOT NULL DEFAULT 0,
        context            jsonb,
        intent             jsonb,
        error              jsonb,
        closed_at          timestamptz,
        created_at         timestamptz NOT NULL DEFAULT now(),
        updated_at         timestamptz NOT NULL DEFAULT now(),
        -- internal counters (ids never reused within an episode)
        next_item_n        integer NOT NULL DEFAULT 1,
        next_task_n        integer NOT NULL DEFAULT 1,
        next_card_ordinal  integer NOT NULL DEFAULT 1,
        -- internal: new items arrived after judging; re-run comes with spec §14
        rerun_pending      boolean NOT NULL DEFAULT false
    )
    """,
    "CREATE INDEX episodes_household_status ON episodes (household_id, status)",
    "CREATE INDEX episodes_household_shared ON episodes (household_id, shared_at)",
    """
    CREATE TABLE episode_sources (
        household_id  text NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        source_id     text NOT NULL,
        episode_id    text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        PRIMARY KEY (household_id, source_id)
    )
    """,
    """
    CREATE TABLE episode_images (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        episode_id  text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        path        text NOT NULL,
        read        boolean NOT NULL DEFAULT false,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX episode_images_episode ON episode_images (episode_id, read)",
    """
    CREATE TABLE orders (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- internal
        episode_id  text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        order_no    text,
        mall        text,
        eta_text    text
    )
    """,
    "CREATE INDEX orders_episode ON orders (episode_id)",
    "CREATE INDEX orders_order_no ON orders (order_no)",
    """
    CREATE TABLE order_items (
        episode_id  text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        id          text NOT NULL,
        order_no    text,
        name        text,
        type        text,
        grp         text,
        label       text NOT NULL CHECK (label IN ('care','clue')),
        qty         integer,
        deal        text,
        attributes  jsonb,
        masked      boolean NOT NULL DEFAULT false,
        created_at  timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (episode_id, id)
    )
    """,
    """
    CREATE TABLE tasks (
        episode_id               text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        task_id                  text NOT NULL,
        card_id                  text,
        source                   text NOT NULL CHECK (source IN ('situation','item')),
        way                      text NOT NULL CHECK (way IN ('run','standby','notice')),
        status                   text NOT NULL CHECK (status IN ('held','live','cancelled','dropped','ended')),
        need                     text,
        line                     text,
        actions                  jsonb NOT NULL,
        trigger                  jsonb,
        "end"                    jsonb NOT NULL,
        target_room              text,
        end_after_start_minutes  integer,
        meta                     jsonb NOT NULL DEFAULT '{}'::jsonb,
        started_at               timestamptz,
        ended_at                 timestamptz,
        drop_reason              text,
        restore                  boolean,          -- internal: restore flag of a cancelled task
        created_at               timestamptz NOT NULL DEFAULT now(),  -- internal
        PRIMARY KEY (episode_id, task_id)
    )
    """,
    "CREATE INDEX tasks_status ON tasks (status)",
    """
    CREATE TABLE plans (
        episode_id        text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        version           integer NOT NULL,
        body              jsonb NOT NULL,
        devices_revision  integer NOT NULL,
        created_at        timestamptz NOT NULL DEFAULT now(),
        ack               jsonb,
        acked_at          timestamptz,
        PRIMARY KEY (episode_id, version)
    )
    """,
    "CREATE SEQUENCE card_write_seq",
    """
    CREATE TABLE cards (
        id            text PRIMARY KEY,
        episode_id    text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        bundle_index  integer NOT NULL,
        ordinal       integer NOT NULL,
        intent_id     text NOT NULL,
        template      text NOT NULL,
        text          text NOT NULL,
        starts_at     timestamptz,
        stopped       boolean NOT NULL DEFAULT false,
        archived      boolean NOT NULL DEFAULT false,
        notify        boolean NOT NULL DEFAULT false,
        updated_at    timestamptz NOT NULL,
        seq           bigint NOT NULL DEFAULT nextval('card_write_seq'),
        UNIQUE (episode_id, ordinal)
    )
    """,
    "CREATE INDEX cards_episode ON cards (episode_id)",
    "CREATE INDEX cards_updated ON cards (updated_at)",
    f"""
    CREATE TABLE card_lines (
        card_id             text NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
        task_id             text NOT NULL,
        position            integer NOT NULL,
        checked             boolean NOT NULL DEFAULT true,
        checked_changed_at  timestamptz,
        state               text NOT NULL CHECK (state IN {LINE_STATE}),
        end_state           text
                            CHECK (end_state IN ('restored','kept_user_change','restore_failed','withheld','none')),
        note                text,
        PRIMARY KEY (card_id, task_id)
    )
    """,
    """
    CREATE TABLE events (
        event_id      text PRIMARY KEY,
        household_id  text NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        type          text NOT NULL,
        source        text NOT NULL,
        at            timestamptz NOT NULL,
        payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
        received_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX events_household_at ON events (household_id, at)",
    """
    CREATE TABLE executions (
        result_id      text PRIMARY KEY,
        kind           text NOT NULL CHECK (kind IN ('run','restore')),
        operation_id   text,
        plan_id        text NOT NULL,
        plan_version   integer NOT NULL,
        task_id        text NOT NULL,
        device         text,
        cmd            text,
        substrate      text,
        status         text,
        reason         text,
        body           jsonb NOT NULL,
        at             timestamptz NOT NULL,
        received_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX executions_task ON executions (plan_id, task_id)",
    """
    CREATE TABLE windows (
        id               text PRIMARY KEY,
        episode_id       text NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
        card_id          text NOT NULL UNIQUE REFERENCES cards(id) ON DELETE CASCADE,
        start_at         timestamptz,
        scheduled_start  timestamptz,
        end_due          timestamptz,
        end_at           timestamptz,
        end_reason       text,
        status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','open','closed')),
        memory           text NOT NULL DEFAULT 'pending' CHECK (memory IN ('pending','written','ineligible')),
        verdict          text CHECK (verdict IN ('match','stopped','unconfirmed')),
        task_feedback    jsonb,
        checks           jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE care_notices_shown (
        household_id  text NOT NULL REFERENCES households(id) ON DELETE CASCADE,
        item_type     text NOT NULL,
        kind          text NOT NULL,
        count         integer NOT NULL DEFAULT 0,
        PRIMARY KEY (household_id, item_type, kind)
    )
    """,
    """
    CREATE TABLE llm_calls (
        id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        episode_id     text,
        stage          text NOT NULL CHECK (stage IN ('s1','cal','s3','s4','retype')),
        provider       text NOT NULL,
        model          text NOT NULL,
        input_tokens   integer,
        output_tokens  integer,
        latency_ms     integer,
        attempts       integer NOT NULL,
        outcome        text NOT NULL CHECK (outcome IN ('ok','format_fail','timeout','error')),
        created_at     timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX llm_calls_episode ON llm_calls (episode_id)",
    # id sequences: h_{n}, ep_{n}, nc_{n}, ow_{n}
    "CREATE SEQUENCE household_id_seq",
    "CREATE SEQUENCE episode_id_seq",
    "CREATE SEQUENCE card_id_seq",
    "CREATE SEQUENCE window_id_seq",
]

DROP = [
    "llm_calls", "care_notices_shown", "windows", "executions", "events", "card_lines", "cards", "plans",
    "tasks", "order_items", "orders", "episode_images", "episode_sources", "episodes", "calendar_revisions",
    "calendar_events", "device_lists", "households",
]


def _kb_target() -> bool:
    return context.get_x_argument(as_dictionary=True).get("db") == "kb"


def upgrade() -> None:
    if _kb_target():
        return
    for sql in TABLES:
        op.execute(sql)


def downgrade() -> None:
    if _kb_target():
        return
    for table in DROP:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for seq in ("card_write_seq", "household_id_seq", "episode_id_seq", "card_id_seq", "window_id_seq"):
        op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
