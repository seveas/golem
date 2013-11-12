import collections
from golem import ConfigParser
from   copy import copy
import datetime
import fnmatch
import getpass
import github3
from   golem import GolemError, CmdLogger, now
import hashlib
import json
import keyword
import logging
import os
import re
import requests
import shlex
import shutil
import socket
import traceback
import whelk
import golem.db
import sqlalchemy.sql as sql

class IniConfig(object):
    defaults = {}
    def __init__(self, config, section):
        if not hasattr(self, 'config'):
            self.config = {}
            for key in self.defaults:
                self._set(key, copy(self.defaults[key]))
        for key in config.options(section):
            self._set(key, config.get(section, key), config=True)

    def _set(self, key, val, config=False):
        if isinstance(val, basestring):
            if "\n" in val:
                val = [shlex.split(x) for x in val.split("\n")]
            else:
                val = shlex.split(val)
                if len(val) == 1:
                    val = val[0]
        if '.' in key:
            key1, key2 = key.split('.', 1)
            if keyword.iskeyword(key1):
                key1 += '_'
            if not hasattr(self, key1):
                setattr(self, key1, {})
            getattr(self, key1)[key2] = val
            if config:
                if key1 not in self.config:
                    self.config[key1] = {}
                self.config[key1][key2] = val
        else:
            if keyword.iskeyword(key):
                key += '_'
            setattr(self, key, val)
            if config:
                self.config[key] = val

class Repository(IniConfig):
    defaults = {'upstream': None, 'reflogtype': None, 'actions': {}, 'notifiers': {}, 'remote': {}}
    def __init__(self, daemon, config, db):
        self.configfile = config
        self.mtime = os.path.getmtime(config)
        config = ConfigParser(config)
        IniConfig.__init__(self, config,    'repo')
        self.logger = logging.getLogger('golem.repo.' + self.name)
        self.logger.info("Parsing configuration for %s" % self.name)
        self.path = os.path.join(daemon.repo_dir, self.name)
        self.repo_path = os.path.join(self.path, self.name + '.git')
        self.artefact_path = os.path.join(self.path, 'artefacts')
        self.shell = whelk.Shell(output_callback=CmdLogger(self.logger),cwd=self.repo_path)

        if re.match('^https?://', self.upstream):
            self.reflogtype = 'http'
            self.reflogurl = self.upstream
        elif self.upstream.startswith('file://'):
            self.reflogtype = 'file'
            self.upstream_path = self.upstream[7:]
            if self.git('config', 'core.bare', cwd=self.upstream).stdout.strip() != 'false':
                self.upstream_path = os.path.join(self.upstream_path, '.git')
        elif self.upstream.startswith('git://'):
            if hasattr(self, 'gitweb'):
                self.reflogtype = 'http'
                self.reflogurl = self.gitweb
        elif ':' in self.upstream:
            self.reflogtype = 'ssh'
        else:
            self.reflogtype = 'file'
            self.upstream_path = self.upstream
            if self.shell.git('config', 'core.bare', cwd=self.upstream).stdout.strip() != 'false':
                self.upstream_path = os.path.join(self.upstream_path, '.git')

        if re.match('^([a-z]+://|git@)github.com', self.upstream):
            self.reflogtype = 'github'

        if not self.reflogtype:
            raise GolemError("Don't know how to fetch reflogs for %s" % self.name)

        for section in config.sections():
            if section.startswith('action:'):
                action = section[7:]
                self.logger.info("  Adding action %s" % action)
                self.actions[action] = Action(config, section)
                self.actions[action].artefact_path = os.path.join(self.artefact_path, action)
                self.actions[action].daemon = daemon
                self.actions[action].repo_name = self.name
            elif section.startswith('notify:'):
                nf = section[7:]
                self.logger.info("  Adding notifier %s" % nf)
                self.notifiers[nf] = Notifier(config, section)
                self.notifiers[nf].daemon = daemon
                self.notifiers[nf].repo_name = self.name

        changed = True
        while changed:
            changed = False
            for action in self.actions:
                for req in self.actions[action].requires:
                    req = req[7:]

                    # Backlog is "inherited" from the dependencies
                    if self.actions[req].backlog < self.actions[action].backlog:
                        changed = True
                        self.actions[action].backlog = self.actions[req].backlog

                    # Same for branches and tags. Intersection of all parents
                    if self.actions[req].branches and not self.actions[action].branches:
                        changed = True
                        self.actions[action].branches = copy(self.actions[req].branches)
                    elif self.actions[req].branches:
                        for branch in self.actions[action].branches[:]:
                            if branch not in self.actions[req].branches:
                                changed = True
                                self.actions[action].branches.remove(branch)
                    if self.actions[req].tags and not self.actions[action].tags:
                        changed = True
                        self.actions[action].tags = copy(self.actions[req].tags)
                    elif self.actions[req].tags:
                        for tag in self.actions[action].tags[:]:
                            if tag not in self.actions[req].tags:
                                changed = True
                                self.actions[action].tags.remove(tag)

        self.create_dirs()

        _r = golem.db.repository
        self.id = db.execute(sql.select([_r.c.id]).where(_r.c.name==self.name)).fetchone()
        self.id = self.id.id if self.id else db.execute(_r.insert().values(name=self.name)).inserted_primary_key[0]

    def create_dirs(self):
        if not os.path.exists(self.artefact_path):
            os.makedirs(self.artefact_path)

    def update(self):
        self.logger.info("Processing update for %s" % self.name)
        if self.upstream:
            if not os.path.exists(self.repo_path):
                self.logger.info("Cloning %s" % self.upstream)
                res = self.shell.git('clone', '--mirror', self.upstream, os.path.basename(self.repo_path), cwd=self.path)
                if res.returncode != 0:
                    raise GolemError("Unable to clone repository: %s" % res.stdout)
                self.git('config', 'core.logallrefupdates', 'false')
                self.git('config', 'remote.origin.fetch', 'refs/heads/*:refs/heads/*')
            else:
                if self.git('config', 'remote.origin.url').stdout.strip() != self.upstream:
                    self.logger.warning("Updating origin url")
                    self.git('config', 'remote.origin.url', self.upstream)
                if self.git('config', 'remote.origin.fetch').stdout.strip() != '+refs/heads/*:refs/heads/*':
                    self.git('config', 'remote.origin.fetch', '+refs/heads/*:refs/heads/*')
                self.logger.info("Fetching from %s" % self.upstream)
                self.git('remote', 'prune', 'origin')
                self.git('fetch', 'origin')
            if self.remote:
                _remotes = self.git('remote').stdout.strip().split()
                for remote in self.remote:
                    if remote not in _remotes:
                        self.git('remote', 'add', remote, self.remote[remote])

                    if self.git('config', 'remote.%s.url' % remote).stdout.strip() != self.remote[remote]:
                        self.logger.warning("Updating %s url" % remote)
                        self.git('config', 'remote.%s.url' % remote, self.remote[remote])
                    self.logger.info("Fetching from %s" % self.remote[remote])
                    try:
                        self.git('remote', 'prune', remote)
                        self.git('fetch', remote)
                    except RuntimeError:
                        # For secondary repos, exceptions are ok
                        for line in traceback.format_exc().split('\n'):
                            self.logger.error(line)
        self.update_reflog()

    def update_reflog(self):
        if self.reflogtype == 'file':
            self.shell.rsync(os.path.join(self.upstream_path, 'logs/'),
                             os.path.join(self.repo_path, 'logs/'))
        elif self.reflogtype == 'ssh':
            self.shell.rsync('%s/logs/' % self.upstream, os.path.join(self.repo_path, 'logs/'))
        elif self.reflogtype == 'http':
            branches = self.git('for-each-ref', '--format', '%(refname:short)', 'refs/heads').stdout.splitlines()
            for branch in branches:
                logpath = os.path.join(self.repo_path, 'logs', 'refs', 'heads', branch)
                if not os.path.exists(os.path.dirname(logpath)):
                    os.makedirs(os.path.dirname(logpath))
                res = requests.get('%s/logs/refs/heads/%s' % (self.reflogurl, branch))
                if res.status_code != 200:
                    raise GolemError("Unable to fetch reflog for branch: %s" % r.status_code)
                with open(logpath, 'w') as fd:
                    fd.write(res.text.encode('utf-8'))
        elif self.reflogtype == 'github':
            gh = github()
            BOGUS_SHA1 = '1' * 40
            user, repo = self.upstream.rsplit('/', 3)[-2:]
            # For ssh urls
            if ':' in user:
                user = user[user.find(':')+1:]
            if repo.endswith('.git'):
                repo = repo[:-4]
            repo = gh.repository(user, repo)
            branches = collections.defaultdict(list)
            heads = {}

            for event in repo.iter_events(number=300):
                if event.type != 'PushEvent':
                    continue
                # Format:
                # prev_sha1 sha1 Author Name <author@mail> timestamp +TZOFF push
                push = (
                    event.payload.get('before',BOGUS_SHA1), # Older events don't have 'before'
                    event.payload['head'],
                    cache(gh.user, event.actor.login).name,
                    '<%s@github>' % event.actor.login,
                    event.created_at.strftime('%s +0000'),
                    'push',
                )
                heads[event.payload['head']] = 1
                branches[event.payload['ref']].append(push)

            for branch in branches:
                branches[branch].reverse()
                log_path = os.path.join(self.repo_path, 'logs', branch)
                if os.path.exists(log_path):
                   with open(log_path) as fd:
                       log = fd.readlines()
                   for line in log:
                       old, new, junk = line.strip().split(None, 2)
                       if new not in heads:
                           name, mail, ts, tz, psh = junk.rsplit(None, 4)
                           branches[branch].append((old, new, name, mail, '%s %s' % (ts, tz), psh))
                   branches[branch].sort(key=lambda x: x[4])
                log = "\n".join([' '.join(push) for push in branches[branch]]) + "\n"

                if not os.path.exists(os.path.dirname(log_path)):
                    os.makedirs(os.path.dirname(log_path))
                with open(log_path, 'w') as fd:
                    fd.write(log)
        else:
            raise GolemError("Don't know how to fetch the reflog")

    def schedule(self, job, db):
        ref = job.get('ref', None)
        why = job['why']
        repo = job['repo']

        _c = golem.db.commit
        _a = golem.db.action
        _r = golem.db.repository
        _f = golem.db.artefact

        refs = {}
        tags = []
        if why == 'reschedule':
            if job['sha1']:
                c = db.execute(_c.select().where(sql.and_(_c.c.ref==job['ref'], _c.c.sha1==job['sha1']))).fetchone()
                if not c:
                    self.logger.error("Commit %s for ref %s cannot be rescheduled, it does not exist" % (job['sha1'], job['ref']))
                    return
            else:
                c = db.execute(_c.select().where(_c.c.ref==job['ref']).desc('submit_time').limit(1)).fetchone()
                if not c:
                    self.logger.error("Cannot reschedule actions for ref %s, no commits were processed yet" % job['ref'])
                    return
            job['prev_sha1'], job['sha1'] = c.prev_sha1, c.sha1

        if ref and ref.startswith(('refs/heads', 'refs/tags')):
            refs[ref] = [(job['prev_sha1'], job['sha1'])]
        if ref and ref.startswith('refs/tags'):
            tags = [(ref, 0)]

        if why == 'action-done':
            aid = db.execute(_a.join(_c).join(_r).select(use_labels=True).where(
                    sql.and_(_r.c.name == job['repo'], _c.c.ref==job['ref'], _c.c.sha1==job['sha1'], _a.c.name==job['action']))).fetchone()[0]
            db.execute(_a.update().values(status=job['result'], start_time=datetime.datetime.utcfromtimestamp(job['start_time']), 
                                          end_time=datetime.datetime.utcfromtimestamp(job['end_time']), duration=job['duration']).where(_a.c.id==aid))
            artefact_path = os.path.join(self.actions[job['action']].artefact_path, '%s@%s' % (job['ref'], job['sha1']))
            for path, _, files in os.walk(artefact_path):
                for file in files:
                    if file != 'log':
                        file = os.path.join(path, file)
                        rfile = file[len(artefact_path)+len(os.sep):]
                        db.execute(_f.insert().values(action=aid, filename=rfile, sha1=sha1_file(file)))
            for nf in self.notifiers.values():
                for what in nf.process:
                    if fnmatch.fnmatch('action:' + job['action'], what):
                        nf.schedule(job)

        if why == 'post-receive' and not refs:
            for head in self.git('for-each-ref', '--format', '%(refname)', 'refs/heads').stdout.splitlines():
                lf = os.path.join(self.repo_path, 'logs', 'refs', 'heads', head[11:])
                if not os.path.exists(lf):
                    refs[head] = []
                else:
                    with open(lf) as fd:
                        log = fd.readlines()
                        refs[head] = [x.split(None, 2)[:2] for x in log]
            null = '0' * 40
            for tag in self.git('for-each-ref', '--format', '%(refname) %(*objectname) %(objectname) %(taggerdate:raw) %(committerdate:raw)', 'refs/tags').stdout.splitlines():
                data = tag.split()
                if not (data[-2].isdigit() and data[-1][1:].isdigit()):
                    # Severely broken tag 
                    continue
                tag, sha = data[:2]
                ts = data[-2:]
                ts = int(ts[0]) + (-1 if ts[1][0] == '-' else 1) * (3600 * int(ts[1][1:3]) + 60 * int(ts[1][3:]))
                refs[tag] = [(null, sha)]
                tags.append((tag, ts))

        if why == 'reschedule':
            # Set actions back to 'new'
            # Set dependent actions back to 'new'
            # Delete files from artefacts
            if job['action']:
                actions = [job['action']]
            else:
                actions = [x.name for x in db.execute(_a.select().where(sql.and_(_a.c.commit==c.id, _a.c.status=='retry'))).fetchall()]
            added = True
            while added:
                added = False
                for aname, action in self.actions.items():
                    if aname in actions:
                        continue
                    for act in actions:
                        if 'action:' + act in action.requires:
                            added = True
                            actions.append(aname)
                            break
            for action in actions:
                self.actions[action].clean(job['ref'], job['sha1'])
            db.execute(_a.update().values(status='new').where(sql.and_(_a.c.commit==c.id, _a.c.name.in_(actions))))

        tags.sort(key=lambda x: x[1], reverse=True)

        for aname, action in self.actions.items():
            if job['why'] == 'action-done' and 'action:' + job['action'] not in action.requires:
                continue
            my_tags = []
            for tag in tags:
                tag = tag[0][10:]
                for tag_ in action.tags:
                    if tag_ == tag or (hasattr(tag_, 'match') and tag_.match(tag)):
                        my_tags.append(tag)
            my_tags = my_tags[:action.backlog+1]
            for ref in refs:
                # Do we want to handle this thing?
                handle = False
                if ref.startswith('refs/heads'):
                    head = ref[11:]
                    for head_ in action.branches:
                        if head_ == head or (hasattr(head_, 'match') and head_.match(head)):
                            handle = True
                            break
                elif ref.startswith('refs/tags'):
                    tag = ref[10:]
                    if tag in my_tags:
                        handle = True

                if not handle:
                    continue

                for prev_sha1, sha1 in refs[ref][-(action.backlog+1):]:
                    cid = db.execute(_c.select().where(_c.c.repository==self.id).where(_c.c.ref==ref).where(_c.c.sha1==sha1)).fetchone()
                    cid = cid.id if cid else db.execute(_c.insert().values(repository=self.id, ref=ref, sha1=sha1, prev_sha1=prev_sha1,
                                                        submit_time=now())).inserted_primary_key[0]
                    act = db.execute(_a.select().where(_a.c.commit==cid).where(_a.c.name==action.name)).fetchone()
                    if not act:
                        db.execute(_a.insert().values(commit=cid, name=action.name, status='new'))
                        act = db.execute(_a.select().where(_a.c.commit==cid).where(_a.c.name==action.name)).fetchone()

                    # Check if all dependencies have been met
                    if action.requires:
                        requires = [x.replace('action:','') for x in action.requires]
                        actions = db.execute(_a.select().where(_a.c.commit==cid).where(_a.c.name.in_(requires)).where(_a.c.status=='success')).fetchall()
                        if len(actions) != len(action.requires):
                            continue

                    if act.status == 'new':
                        db.execute(_a.update().where(_a.c.id==act.id).values(status='scheduled'))
                        action.schedule(ref, prev_sha1, sha1)

    def git(self, *args, **kwargs):
        res = self.shell.git(*args, **kwargs)
        if res.returncode:
            raise RuntimeError("git %s failed: %s" % (' '.join(args), res.stderr))
        return res

    def __repr__(self):
        return '<Repository %s at %s>' % (self.name, self.path)

class Action(IniConfig):
    defaults = {'branches': [], 'tags': [], 'requires': [], 'queue': None, 'backlog': 10, 'ttr': 120, 'publish': []}
    def __init__(self, config, section):
        if config.has_option(section, 'inherit'):
            IniConfig.__init__(self, config, config.get(section, 'inherit'))
        IniConfig.__init__(self, config, section)
        self.name = section[7:]
        self.logger = logging.getLogger('golem.action.' + self.name)
        if isinstance(self.branches, basestring):
            self.branches = self.config['branches'] = [self.branches]
            for idx, branch in enumerate(self.branches):
                if branch.startswith('^'):
                    self.branches[idx] = re.compile(branch)
        if isinstance(self.tags, basestring):
            self.tags = self.config['tags'] = [self.tags]
            for idx, tag in enumerate(self.tags):
                if tag.startswith('^'):
                    self.tags[idx] = re.compile(tag)
        if isinstance(self.requires, basestring):
            self.requires = self.config['requires'] = [self.requires]
        if isinstance(self.publish, basestring):
            self.publish = self.config['publish'] = [self.publish]
        if isinstance(self.backlog, basestring):
            self.backlog = self.config['backlog'] = int(self.backlog)
        if isinstance(self.ttr, basestring):
            self.ttr = self.config['ttr'] = int(self.ttr)
        if hasattr(self, 'hook'):
            for key, val in self.hook.items():
                if isinstance(val, basestring):
                    self.hook[key] = [[val]]
                elif isinstance(val[0], basestring):
                    self.hook[key] = [val]
            self.config['hook'] = self.hook

        if not self.queue:
            raise ValueError("No queue specified")

    def schedule(self, ref, prev_sha1, sha1):
        self.logger.info("Scheduling %s for %s@%s" % (self.name, ref, sha1))
        self.daemon.bs.use(self.queue)
        data = {'repo': self.repo_name, 'ref': ref, 'prev_sha1': prev_sha1, 'sha1': sha1, 'action': self.name}
        data.update(self.config)
        if 'tags' in data:
            data['tags'] = [x.pattern if hasattr(x, 'pattern') else x for x in data['tags']]
        if 'branches' in data:
            data['branches'] = [x.pattern if hasattr(x, 'pattern') else x for x in data['branches']]

        self.daemon.bs.put(json.dumps(data), ttr=self.ttr)
        if sha1:
            ref += '@' + sha1
        if not os.path.exists(os.path.join(self.artefact_path, ref)):
            os.makedirs(os.path.join(self.artefact_path, ref))

    def clean(self, ref, sha1):
        ref += '@' + sha1
        if os.path.exists(os.path.join(self.artefact_path, ref)):
            shutil.rmtree(os.path.join(self.artefact_path, ref))

class Notifier(IniConfig):
    defaults = {'process': [], 'queue': None, 'ttr': 120}
    def __init__(self, config, section):
        if config.has_option(section, 'inherit'):
            IniConfig.__init__(self, config, config.get(section, 'inherit'))
        IniConfig.__init__(self, config, section)
        self.name = section[7:]
        self.logger = logging.getLogger('golem.notifier.' + self.name)
        if isinstance(self.process, basestring):
            self.process = self.config['process'] = [self.process]
        if not self.queue:
            raise ValueError("No queue specified")

    def schedule(self, job):
        self.logger.info("Scheduling %s notifications for %s@%s" % (job['action'], job['ref'], job['sha1']))
        self.daemon.bs.use(self.queue)
        data = job.copy()
        data.update(self.config)
        self.daemon.bs.put(json.dumps(data), ttr=self.ttr)

# Copied from git-hub
def github(try_login=False):
    config_file = os.path.join(os.path.expanduser('~'), '.githubconfig-golem')
    old_umask = os.umask(63) # 0o077
    shell = whelk.Shell()

    user = shell.git('config', '--file', config_file, 'github.user').stdout.strip()
    if not user and try_login:
        user = raw_input("Github user: ").strip()
        shell.git('config', '--file', config_file, 'github.user', user)

    token = shell.git('config', '--file', config_file, 'github.token').stdout.strip()
    if not token and try_login:
        password = getpass.getpass("Github password: ")
        auth = github3.authorize(user, password, ['user', 'repo', 'gist'],
                "Golem on %s" % socket.gethostname(), "http://seveas.github.com/golem")
        token = auth.token
        shell.git('config', '--file', config_file, 'github.token', token)
        shell.git('config', '--file', config_file, 'github.auth_id', str(auth.id))

    if not user or not token:
        raise GolemError("No github credentials found, try golem --login github")

    gh = github3.login(username=user, token=token)
    try:
        gh.user()
    except github3.GitHubError:
        # Token obsolete
        shell.git('config', '--file', config_file, '--unset', 'github.token')
        gh = github(try_login)
    os.umask(old_umask)
    return gh

_cache={}
def cache(fnc, *args):
    if (fnc,) + args not in _cache:
        _cache[(fnc,) + args] = fnc(*args)
    return _cache[(fnc,) + args]

def sha1_file(file):
    sha = hashlib.new('sha1')
    with open(file) as fd:
        while True:
            data = fd.read(4096)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()
