"""Add max_rating to user table

Revision ID: 94b640653b2d
Revises: 2535204cd05a
Create Date: 2021-05-22 00:12:25.855255

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.ext.declarative import declarative_base
from utils.db import Json

Base = declarative_base()


class Contest(Base):
    __tablename__ = 'contest'

    key = sa.Column(sa.String, primary_key=True)
    rankings = sa.Column(Json)
    is_rated = sa.Column(sa.Boolean)
    end_time = sa.Column(sa.DateTime)

class User(Base):
    __tablename__ = 'user'

    id = sa.Column(sa.String, primary_key=True)
    username = sa.Column(sa.String)
    max_rating = sa.Column(sa.Integer)

# revision identifiers, used by Alembic.
revision = '94b640653b2d'
down_revision = '2535204cd05a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('user', sa.Column('max_rating', sa.Integer(), nullable=True))
    bind = op.get_bind()
    session = orm.Session(bind=bind)
    max_rating = {}
    contests = session.query(Contest).filter(Contest.is_rated == 1)\
        .order_by(Contest.end_time.desc()).all()
    print("Getting max rating for every user")
    for contest in contests:
        for participation in contest.rankings:
            username = participation['user']
            if participation['new_rating'] is not None:
                if username not in max_rating:
                    max_rating[username] = participation['new_rating']
                else:
                    max_rating[username] = max(participation['new_rating'], max_rating[username])

    print("Adding data to max_rating column")
    for user in session.query(User):
        if user.username not in max_rating:
            user.max_rating = 0
        else:
            user.max_rating = max_rating[user.username]
        session.add(user)
    session.commit()
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('user', 'max_rating')
    # ### end Alembic commands ###
