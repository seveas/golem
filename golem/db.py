from sqlalchemy import *

metadata = MetaData()

repository = Table('repository', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(50), nullable=False, unique=True)
)

commit = Table('commit', metadata,
    Column('id', Integer, primary_key=True),
    Column('repository', Integer, ForeignKey('repository.id')),
    Column('sha1', String(40)),
    Column('prev_sha1', String(40)),
    Column('ref', String(60)),
    Column('submit_time', DateTime()),
    UniqueConstraint('repository', 'sha', 'ref')
)

action = Table('action', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(30)),
    Column('commit', Integer, ForeignKey('commit.id')),
    Column('status', String(10)),
    Column('start_time', DateTime()),
    Column('end_time', DateTime()),
    Column('duration', Integer),
    UniqueConstraint('name', 'commit'),
)

artefact = Table('artefact', metadata,
    Column('id', Integer, primary_key=True),
    Column('filename', String(192)),
    Column('action', Integer, ForeignKey('action.id')),
    Column('sha1', String(40)),
    UniqueConstraint('filename', 'action'),
)
