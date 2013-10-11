from sqlalchemy import *

metadata = MetaData()

repository = Table('repository', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(50), nullable=False, unique=True)
)

commit = Table('commit', metadata,
    Column('id', Integer, primary_key=True),
    Column('repository', Integer, ForeignKey('repository.id')),
    Column('sha', String(40)),
    Column('ref', String(60)),
    UniqueConstraint('repository', 'sha', 'ref')
)

action = Table('action', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(30)),
    Column('commit', Integer, ForeignKey('commit.id')),
    Column('status', String(10)),
    UniqueConstraint('name', 'commit'),
)
