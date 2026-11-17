"""Several birth profiles per account (family members), one conversation each.

* birth_profiles.user_id loses its UNIQUE constraint; gains relation
* users.active_profile_id (backfilled to the user's existing profile)
* conversations.profile_id (backfilled from the user's single profile)

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _unique_on_user_id(constraints) -> list:
    return [c for c in constraints if list(c["column_names"]) == ["user_id"]]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if bind.dialect.name == "sqlite":
        # SQLite can't drop a constraint (the baseline's is unnamed): rebuild
        # the table from its reflected definition minus the UNIQUE(user_id).
        t = sa.Table("birth_profiles", sa.MetaData(), autoload_with=bind)
        for c in list(t.constraints):
            if isinstance(c, sa.UniqueConstraint) and [x.name for x in c.columns] == ["user_id"]:
                t.constraints.discard(c)
        with op.batch_alter_table("birth_profiles", copy_from=t, recreate="always") as b:
            b.add_column(sa.Column("relation", sa.String, nullable=False,
                                   server_default="self"))
            b.create_index("ix_birth_profiles_user_id", ["user_id"])
    else:
        for c in _unique_on_user_id(insp.get_unique_constraints("birth_profiles")):
            op.drop_constraint(c["name"], "birth_profiles", type_="unique")
        op.add_column("birth_profiles", sa.Column("relation", sa.String, nullable=False,
                                                  server_default="self"))
        op.create_index("ix_birth_profiles_user_id", "birth_profiles", ["user_id"])

    # plain integer (no FK): users <-> birth_profiles would be circular
    op.add_column("users", sa.Column("active_profile_id", sa.Integer, nullable=True))
    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("profile_id", sa.Integer, nullable=True))
        b.create_foreign_key("fk_conversations_profile_id", "birth_profiles",
                             ["profile_id"], ["id"])
        b.create_index("ix_conversations_profile_id", ["profile_id"])

    op.execute("UPDATE users SET active_profile_id = (SELECT MIN(p.id) FROM birth_profiles p "
               "WHERE p.user_id = users.id)")
    op.execute("UPDATE conversations SET profile_id = (SELECT MIN(p.id) FROM birth_profiles p "
               "WHERE p.user_id = conversations.user_id)")


def downgrade() -> None:
    # only valid while every user still has at most one profile
    with op.batch_alter_table("conversations") as b:
        b.drop_index("ix_conversations_profile_id")
        b.drop_constraint("fk_conversations_profile_id", type_="foreignkey")
        b.drop_column("profile_id")
    op.drop_column("users", "active_profile_id")
    with op.batch_alter_table("birth_profiles") as b:
        b.drop_index("ix_birth_profiles_user_id")
        b.drop_column("relation")
        b.create_unique_constraint("uq_birth_profiles_user_id", ["user_id"])
