"""multi-user: profile, premium, usage quotas, payments, analytics events

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import bot.db.models


revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('first_name', sa.String(length=100), server_default='', nullable=False))
        batch.add_column(sa.Column('username', sa.String(length=64), server_default='', nullable=False))
        batch.add_column(sa.Column('ref', sa.String(length=64), server_default='', nullable=False))
        batch.add_column(sa.Column('premium_until', bot.db.models.UTCDateTime(), nullable=True))

    op.create_table('usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('day', sa.String(length=10), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'day', 'kind', name='uq_usage_user_day_kind')
    )
    op.create_index(op.f('ix_usage_user_id'), 'usage', ['user_id'], unique=False)

    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('payload', sa.String(length=128), nullable=False),
    sa.Column('charge_id', sa.String(length=200), nullable=False),
    sa.Column('created_at', bot.db.models.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('charge_id')
    )
    op.create_index(op.f('ix_payments_user_id'), 'payments', ['user_id'], unique=False)

    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('props', sa.JSON(), nullable=False),
    sa.Column('created_at', bot.db.models.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_events_user_id'), 'events', ['user_id'], unique=False)
    op.create_index(op.f('ix_events_name'), 'events', ['name'], unique=False)
    op.create_index(op.f('ix_events_created_at'), 'events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('events')
    op.drop_table('payments')
    op.drop_table('usage')
    with op.batch_alter_table('users') as batch:
        batch.drop_column('premium_until')
        batch.drop_column('ref')
        batch.drop_column('username')
        batch.drop_column('first_name')
