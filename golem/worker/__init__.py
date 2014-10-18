from golem.daemon import Daemon
from collections import defaultdict
import keyword
import whelk
import os
import glob
import json
import logging
import re
import shutil
import time
import random
import socket
from golem import GolemError, GolemRetryLater, OutputLogger, RunLogger, now, toutctimestamp

class Worker(Daemon):
    repo_sync = True
    repo_checkout = True
    release_git_lock = True

    def __init__(self, logger, bs_host, bs_port, bs_queue, repo_dir, submit_queue, rsync_root, rsync_hardlink, rsync_password, do_one, config):
        super(Worker, self).__init__(logger, bs_host, bs_port, bs_queue)
        self.repo_dir = repo_dir
        self.rsync_root = rsync_root
        self.rsync_hardlink = rsync_hardlink
        self.rsync_password = rsync_password
        self.submit_queue = submit_queue
        self.do_one = do_one
        if not os.path.exists(self.repo_dir):
            os.makedirs(self.repo_dir)
        self.repo_checkout = self.repo_checkout and self.repo_sync
        self.config = config

    def setup(self, job):
        pass

    def process_job(self, job):
        job = Job(self, job)
        self.logger.info("Processing %s job for %s (%s@%s)" % (job.action, job.repo, job.ref, job.sha1))
        to_submit = {'repo': job.repo, 'ref': job.ref, 'prev_sha1': job.prev_sha1, 'sha1': job.sha1,
                     'why': 'action-started', 'action': job.action, 'host': socket.gethostname(),
                     'start_time': toutctimestamp(job.start_time)}
        self.bs.use(self.submit_queue)
        self.bs.put(json.dumps(to_submit), ttr=600)

        if self.repo_sync:
            job.run_hook('pre-sync')
            job.sync()
            job.run_hook('post-sync')

        os.chdir(job.work_path)

        if self.repo_checkout:
            job.run_hook('pre-checkout')
            job.checkout(job.sha1)
            job.run_hook('post-checkout')

        try:
            self.setup(job)
            self.process_job_simple(job)
            job.result = 'success'
        except GolemRetryLater, e:
            self.logger.error(unicode(e).encode('utf-8'))
            job.result = 'retry'
        except GolemError, e:
            self.logger.error(unicode(e).encode('utf-8'))
            job.result = 'fail'
        os.chdir('/')
        job.run_hook('pre-publish')
        job.publish_results()
        job.run_hook('post-publish')
        if job.result == 'success':
            shutil.rmtree(job.work_path)

        return not self.do_one

class Job(object):
    def __init__(self, worker, data):
        self.start_time = now()
        self.hook = {}
        self.env = {}
        self.publish = []
        self.worker = worker
        self.logger = worker.logger
        self.json = data.body

        data = json.loads(data.body)
        for key, value in data.items():
            if keyword.iskeyword(key):
                key += '_'
            setattr(self, key, value)

        self.env.update(os.environ)

        self.repo_path = os.path.join(worker.repo_dir, self.repo, self.repo + '.git')
        self.work_path = os.path.join(worker.repo_dir, self.repo, 'work', self.action, '%s@%s' % (self.ref, self.sha1))
        self.artefact_path = os.path.join(worker.repo_dir, self.repo, 'artefacts', self.action, '%s@%s' % (self.ref, self.sha1))

        if self.worker.repo_sync and not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path)
        if os.path.exists(self.work_path):
            shutil.rmtree(self.work_path)
        os.makedirs(self.work_path)
        if os.path.exists(self.artefact_path):
            shutil.rmtree(self.artefact_path)
        os.makedirs(self.artefact_path)

        self.shell = whelk.Shell(output_callback=OutputLogger(self.logger), run_callback=RunLogger(self.logger), env=self.env, cwd=self.work_path, exit_callback=check_sp)
        self.pipe = whelk.Pipe(output_callback=OutputLogger(self.logger), run_callback=RunLogger(self.logger), env=self.env, cwd=self.work_path, exit_callback=check_sp)

        # Add a loghandler for our logfile so everything is properly logged per job
        self.log = os.path.join(self.artefact_path, 'log')
        handler = logging.FileHandler(self.log)
        handler.is_job_handler = True
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(fmt='[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
        self.logger.addHandler(handler)

    def sync(self):
        local = self.repo_path
        remote = '/'.join([self.worker.rsync_root, self.repo, self.repo + '.git/'])
        self.logger.info("Syncing %s => %s" % (remote, local))
        args = ['-av', remote, local]
        if self.worker.rsync_hardlink:
            hl = os.path.join(self.worker.rsync_hardlink, self.repo, self.repo, '.git') + os.sep
            if not os.path.exists(hl):
                hl = os.path.join(self.worker.rsync_hardlink, self.repo, self.repo + '.git') + os.sep
            args += ['--link-dest', hl]
        if self.worker.rsync_password:
            args += ['--password-file', self.worker.rsync_password]
        self.shell.rsync(*args)

    def run_hook(self, which, **kwargs):
        if which not in self.hook:
            return
        self.logger.debug("Running %s hooks" % which)
        for command in self.hook[which]:
            if '|' in command:
                pipe = None
                while command:
                    if '|'in command:
                        args = command[:command.index('|')]
                        command = command[command.index('|')+1:]
                    else:
                        args = command
                        command = []
                    cmd = args.pop(0)
                    for idx, arg in enumerate(args):
                        arg = arg.replace('$commit', self.sha1)
                        args[idx] = arg
                    if len(args) >= 2 and args[-2] == '>':
                        kwargs['stdout'] = open(os.path.join(self.work_path, args[-1]), 'w')
                        args = args[:-2]
                    cmd = self.pipe[cmd](*args, **kwargs)
                    if pipe:
                        pipe = pipe | cmd
                    else:
                        pipe = cmd
                self.pipe(pipe)
            else:
                args = command[1:]
                command = command[0]
                for idx, arg in enumerate(args):
                    arg = arg.replace('$commit', self.sha1)
                    args[idx] = arg
                if len(args) >= 2 and args[-2] == '>':
                    kwargs['stdout'] = open(os.path.join(self.work_path, args[-1]), 'w')
                    args = args[:-2]
                self.shell[command](*args, **kwargs)

    def create_git_dir(self):
        # Symlink several things from the .git tree
        dotgit = os.path.join(self.work_path, '.git')
        if not os.path.exists(dotgit):
            os.mkdir(dotgit)
            os.mkdir(os.path.join(dotgit, 'logs'))
        for file in ('refs', 'logs/refs', 'objects', 'info', 'hooks',
            'packed-refs', 'remotes', 'rr-cache', 'svn'):
            if not os.path.exists(os.path.join(dotgit, file)) and os.path.exists(os.path.join(self.repo_path, file)):
                os.symlink(os.path.join(self.repo_path, file),
                           os.path.join(dotgit, file))
        with open(os.path.join(self.repo_path, 'config')) as infd:
            with open(os.path.join(dotgit, 'config'), 'w') as outfd:
                outfd.write(infd.read())
        with open(os.path.join(dotgit, 'HEAD'), 'w') as fd:
            fd.write(self.sha1)
        self.shell.git('config', 'core.bare', 'false')

    def checkout(self, sha1):
        supports_multiple_checkouts = '--to' in self.shell.man('git-checkout', output_callback=None).stdout
        if supports_multiple_checkouts:
            os.rmdir(self.work_path)
            self.shell.git('checkout', '--to', self.work_path, sha1, cwd=self.repo_path)
        else:
            job.create_git_dir()
            self.shell.git('clean', '-dxf')
            self.shell.git('reset', '--hard')
            self.shell.git('checkout', sha1)
        if self.shell.git('submodule').stdout.strip():
            self.shell.git('submodule', 'update')

    def publish_results(self):
        for glb in getattr(self, 'publish', []):
            for file in glob.glob(os.path.join(self.work_path, glb)):
                self.logger.info("Adding artefact %s" % file.replace(self.work_path, ''))
                os.rename(file, os.path.join(self.artefact_path, os.path.basename(file)))
        local = self.artefact_path + os.sep
        remote = '/'.join([self.worker.rsync_root, self.repo, 'artefacts', self.action, '%s@%s' % (self.ref, self.sha1)]) + os.sep
        self.logger.info("Publishing %s => %s" % (local, remote))
        args = ['-av', local, remote]
        if self.worker.rsync_password:
            args += ['--password-file', self.worker.rsync_password]
        self.shell.rsync(*args)
        self.end_time = now()
        to_submit = {'repo': self.repo, 'ref': self.ref, 'prev_sha1': self.prev_sha1, 'sha1': self.sha1,
                     'why': 'action-done', 'action': self.action, 'result': self.result,
                     'start_time': toutctimestamp(self.start_time), 'end_time': toutctimestamp(self.end_time),
                     'duration': (self.end_time-self.start_time).total_seconds(),
                     'host': socket.gethostname()}
        self.worker.bs.use(self.worker.submit_queue)
        self.worker.bs.put(json.dumps(to_submit), ttr=600)

    def fetch_artefacts(self, action, filename):
        local = '.'
        if action.startswith('action:'):
            action = action[7:]
        remote = os.path.join(self.worker.rsync_root, self.repo, 'artefacts', action, '%s@%s' % (self.ref, self.sha1), filename)

        args = ['-a', '--list-only', remote]
        if self.worker.rsync_password:
            args += ['--password-file', self.worker.rsync_password]
        files = self.shell.rsync(*args).stdout.strip().split('\n')
        files = [re.split('\s+', x, 4)[-1] for x in files] # And pray rsync never changes this format

        args = ['-av', remote, local]
        if self.worker.rsync_password:
            args += ['--password-file', self.worker.rsync_password]
        self.shell.rsync(*args)

        return files

def check_sp(command, sp, res):
    if isinstance(res.returncode, int):
        if res.returncode != 0:
            if command.name.endswith('/git') and 'index.lock' in res.stderr:
                # Let's retry
                time.sleep(random.random())
                return command(*command.args, **command.kwargs)
            raise GolemError("%s %s failed: %s" % (command.name, ' '.join(command.args), res.stderr.decode('utf-8')))
    elif res.returncode.count(0) != len(res.returncode):
        raise GolemError("%s %s failed: %s" % (command.name, ' '.join(command.args), res.stderr.decode('utf-8')))
