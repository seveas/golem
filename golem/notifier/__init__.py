from golem.daemon import Daemon
from golem.worker import check_sp
from golem import CmdLogger
import json
import os
import whelk

class Notifier(Daemon):
    def __init__(self, logger, bs_host, bs_port, bs_queue, repo_dir, do_one):
        super(Notifier, self).__init__(logger, bs_host, bs_port, bs_queue)
        self.repo_dir = repo_dir
        self.do_one = do_one

    def process_job(self, job):
        job = Job(self, job)
        self.logger.info("Sending %s notifications for %s (%s@%s)" % (job.action, job.repo, job.ref, getattr(job, 'new-sha1')))
        self.process_job_simple(job)
        os.chdir('/')
        return not self.do_one

class Job(object):
    def __init__(self, worker, data):
        self.worker = worker
        self.logger = worker.logger

        data = json.loads(data.body)
        for key, value in data.items():
            setattr(self, key, value)

        self.repo_path = os.path.join(worker.repo_dir, self.repo, self.repo + '.git')
        self.artefact_path = os.path.join(worker.repo_dir, self.repo, 'artefacts', self.action, '%s@%s' % (self.ref, getattr(self, 'new-sha1')))
        self.env = {'GIT_DIR': self.repo_path}

        self.shell = whelk.Shell(output_callback=CmdLogger(self.logger), env=self.env, cwd=self.repo_path, exit_callback=check_sp)
        self.pipe = whelk.Pipe(output_callback=CmdLogger(self.logger), env=self.env, cwd=self.repo_path, exit_callback=check_sp)
