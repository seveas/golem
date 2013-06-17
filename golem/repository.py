import collections
from   copy import copy
import getpass
import github3
from   golem import GolemError, CmdLogger
import json
import logging
import os
import re
import requests
import shlex
import socket
import whelk

class IniConfig(object):
    defaults = {}
    def __init__(self, config, section):
        self.config = {}
        for key in self.defaults:
            self._set(key, copy(self.defaults[key]))
        for key in config.options(section):
            self._set(key, config.get(section, key), config=True)

    def _set(self, key, val, config=False):
        if isinstance(val, basestring):
            val = shlex.split(val)
            if len(val) == 1:
                val = val[0]
        if '.' in key:
            key1, key2 = key.split('.', 1)
            if not hasattr(self, key1):
                setattr(self, key1, {})
            getattr(self, key1)[key2] = val
            if config:
                if key1 not in self.config:
                    self.config[key1] = {}
                self.config[key1][key2] = val
        else:
            setattr(self, key, val)
            if config:
                self.config[key] = val

class Repository(IniConfig):
    defaults = {'upstream': None, 'reflogtype': None, 'actions': {}, 'remote': {}}
    def __init__(self, daemon, config):
        IniConfig.__init__(self, config, 'repo')
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
            else:
                if self.git('config', 'remote.origin.url').stdout.strip() != self.upstream:
                    self.logger.warning("Updating origin url")
                    self.git('config', 'remote.origin.url', self.upstream)
                self.logger.info("Fetching from %s" % self.upstream)
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
                    self.git('fetch', remote)
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
            if repo.endswith('.git'):
                repo = repo[:-4]
            repo = gh.repository(user, repo)
            branches = collections.defaultdict(list)
            heads = {}

            for event in repo.iter_events(number=300):
                if event.type != 'PushEvent':
                    continue
                # Format:
                # old_sha1 new_sha1 Author Name <author@mail> timestamp +TZOFF push
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

    def schedule(self, ref, old_commit, commit):
        refs = {}
        if ref and ref.startswith(('refs/heads', 'refs/tags')):
            refs[ref] = [commit]

        if not refs:
            for head in self.git('for-each-ref', '--format', '%(refname)', 'refs/heads').stdout.splitlines():
                with open(os.path.join(self.repo_path, 'logs', 'refs', 'heads', head[11:])) as fd:
                    log = fd.readlines()
                    refs[head] = [x.split(None, 2)[1] for x in log]

        for aname, action in self.actions.items():
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
                    tag = ref[:10]
                    for tag_ in action.tags:
                        if tag_ == tag or (hasattr(tag_, 'match') and tag_.match(tag)):
                            handle = True
                            break
                if not handle:
                    continue

                for commit in refs[ref][-(action.backlog+1):]:
                    req_ok = True
                    for req in action.requires:
                        if not self.actions[req[7:]].succes(ref, commit):
                            req_ok = False
                    if req_ok and not action.scheduled(ref, commit):
                        action.schedule(ref, old_commit, commit)

    def git(self, *args, **kwargs):
        res = self.shell.git(*args, **kwargs)
        if res.returncode:
            raise RuntimeError("git %s failed: %s" % (' '.join(args), res.stderr))
        return res

    def __repr__(self):
        return '<Repository %s at %s>' % (self.name, self.path)

class Action(IniConfig):
    defaults = {'branches': [], 'tags': [], 'requires': [], 'queue': None, 'when': 'push', 'backlog': 10, 'ttr': 120, 'publish': []}
    def __init__(self, config, section):
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
        if not self.queue:
            raise ValueError("No queue specified")

    def succes(self, ref, commit):
        return os.path.exists(os.path.join(self.artefact_path, '%s@%s' % (ref, commit), 'finished_ok'))

    def scheduled(self, ref, commit):
        return os.path.exists(os.path.join(self.artefact_path, '%s@%s' % (ref, commit)))

    def schedule(self, ref, old_commit, commit):
        self.logger.info("Scheduling %s for %s@%s" % (self.name, ref, commit))
        self.daemon.bs.use(self.queue)
        data = {'repo': self.repo_name, 'ref': ref, 'old_commit': old_commit, 'commit': commit, 'action': self.name}
        data.update(self.config)
        self.daemon.bs.put(json.dumps(data), ttr=self.ttr)
        if commit:
            ref += '@' + commit
        if not os.path.exists(os.path.join(self.artefact_path, ref)):
            os.makedirs(os.path.join(self.artefact_path, ref))

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
        password = getpass.getpass("GitHub password: ")
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
