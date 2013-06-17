from golem.daemon import Daemon
from collections import defaultdict
import whelk
import os
import glob
import json
import re
from golem import GolemError, CmdLogger

class Worker(Daemon):
    repo_sync = True
    repo_checkout = True

    def __init__(self, parser):
        super(Worker, self).__init__(parser)
        self.repo_dir = parser.get(self.name, 'repos')
        self.rsync_root = parser.get('golem', 'rsync_root')
        self.rsync_hardlink = None
        self.rsync_password = None
        if parser.has_option('golem', 'rsync_password'):
            self.rsync_password = parser.get('golem', 'rsync_password')
        if parser.has_option(self.name, 'rsync_hardlink'):
            self.rsync_hardlink = parser.get(self.name, 'rsync_hardlink')
        if not os.path.exists(self.repo_dir):
            os.makedirs(self.repo_dir)
        self.repo_checkout = self.repo_checkout and self.repo_sync

    def setup(self, job):
        pass

    def process_job(self, job):
        job = Job(self, job)
        self.logger.info("Processing %s job for %s (%s@%s)" % (job.action, job.repo, job.ref, job.commit))
        for f in ('ok', 'fail'):
            if os.path.exists(os.path.join(job.artefact_path, 'finished_' + f)):
                os.unlink(os.path.join(job.artefact_path, 'finished_' + f))

        if self.repo_sync:
            job.sync()
        os.chdir(job.work_path)
        if self.repo_checkout:
            job.checkout(job.commit)

        try:
            self.setup(job)
            self.process_job_simple(job)
            job.succes = True
        except GolemError, e:
            job.succes = False
            self.logger.error(str(e))
            with open(os.path.join(job.artefact_path, 'finished_fail'), 'w') as fd:
                fd.write(str(e))
        else:
            open(os.path.join(job.artefact_path, 'finished_ok'), 'w').close()
        os.chdir('/')
        job.publish_results()
        if job.succes:
            job.shell.rm('-rf', job.work_path, cwd='/')

        return True

class Job(object):
    def __init__(self, worker, data):
        self.hook = {}
        self.env = {}
        self.publish = []
        self.worker = worker
        self.logger = worker.logger

        data = json.loads(data.body)
        for key, value in data.items():
            setattr(self, key, value)

        self.env.update(os.environ)

        self.repo_path = os.path.join(worker.repo_dir, self.repo, self.repo + '.git')
        self.work_path = os.path.join(worker.repo_dir, self.repo, 'work', self.action, '%s@%s' % (self.ref, self.commit))
        self.artefact_path = os.path.join(worker.repo_dir, self.repo, 'artefacts', self.action, '%s@%s' % (self.ref, self.commit))
        self.env['GIT_DIR'] = self.repo_path
        self.env['GIT_WORK_TREE'] = self.work_path

        if self.worker.repo_sync and not os.path.exists(self.repo_path):
            os.makedirs(self.repo_path)
        if not os.path.exists(self.work_path):
            os.makedirs(self.work_path)
        if not os.path.exists(self.artefact_path):
            os.makedirs(self.artefact_path)

        self.log = open(os.path.join(self.artefact_path, 'log'), 'a')
        self.shell = whelk.Shell(output_callback=CmdLogger(self.logger, self.log), env=self.env, cwd=self.work_path, exit_callback=check_sp)
        self.pipe = whelk.Pipe(output_callback=CmdLogger(self.logger, self.log), env=self.env, cwd=self.work_path, exit_callback=check_sp)

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
        if which in self.hook:
            command = self.hook[which]
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
                        arg = arg.replace('$commit', self.commit)
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
                    arg = arg.replace('$commit', self.commit)
                    args[idx] = arg
                if len(args) >= 2 and args[-2] == '>':
                    kwargs['stdout'] = open(os.path.join(self.work_path, args[-1]), 'w')
                    args = args[:-2]
                self.shell[command](*args, **kwargs)

    def checkout(self, commit):
        # Synced repos may be bare, let's not do that
        self.shell.git('clean', '-dxf')
        self.shell.git('reset', '--hard')
        self.shell.git('checkout', commit)

    def publish_results(self):
        for glb in getattr(self, 'publish', []):
            for file in glob.glob(os.path.join(self.work_path, glb)):
                self.logger.info("Adding artefact %s" % file.replace(self.work_path, ''))
                os.rename(file, os.path.join(self.artefact_path, os.path.basename(file)))
        local = self.artefact_path + os.sep
        remote = '/'.join([self.worker.rsync_root, self.repo, 'artefacts', self.action, '%s@%s' % (self.ref, self.commit)]) + os.sep
        self.logger.info("Publishing %s => %s" % (local, remote))
        args = ['-av', local, remote]
        if self.worker.rsync_password:
            args += ['--password-file', self.worker.rsync_password]
        self.shell.rsync(*args)
        to_submit = {'repo': self.repo, 'ref': self.ref, 'old-sha1': self.old_commit, 'new-sha1': self.commit}
        self.worker.bs.use('golem-updates')
        self.worker.bs.put(json.dumps(to_submit), ttr=600)

    def fetch_artefacts(self, action, filename):
        local = '.'
        if action.startswith('action:'):
            action = action[7:]
        remote = os.path.join(self.worker.rsync_root, self.repo, 'artefacts', action, '%s@%s' % (self.ref, self.commit), filename)

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
            raise GolemError("%s %s failed: %s" % (command.name, ' '.join(command.args), res.stderr))
    elif res.returncode.count(0) != len(res.returncode):
        raise GolemError("%s %s failed: %s" % (command.name, ' '.join(command.args), res.stderr))
