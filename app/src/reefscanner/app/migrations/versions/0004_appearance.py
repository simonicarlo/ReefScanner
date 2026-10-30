"""Appearance settings: light or dark mode, and translucency.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-30 16:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Server defaults so an existing settings row gets the app's defaults.
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'appearance_mode', sqlmodel.sql.sqltypes.AutoString(),
            nullable=False, server_default='system',
        ))
        batch_op.add_column(sa.Column(
            'translucency', sa.Boolean(), nullable=False, server_default=sa.true(),
        ))


def downgrade() -> None:
    with op.batch_alter_table('appsettings', schema=None) as batch_op:
        batch_op.drop_column('translucency')
        batch_op.drop_column('appearance_mode')
