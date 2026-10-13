"""ai provenance: which provider and model produced each interpretation and reading

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 10:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive and nullable: rows written before this revision simply have no provenance.
    op.add_column('inbound_message', sa.Column('interpretation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('evidence', sa.Column('ai_source', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('evidence', 'ai_source')
    op.drop_column('inbound_message', 'interpretation')
