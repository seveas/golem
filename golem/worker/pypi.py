from golem import GolemError
from golem.worker import Worker
from distutils.cmd import Command
from distutils.core import run_setup
import logging

class Daemon(Worker):
    name = 'pypi-docs'
    logger = 'golem.worker.pypi'
    queue = 'golem-publish-pypi'
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Uploading documentation to PyPI")
        files = job.fetch_artefacts(job.requires[0], job.tarball)
        files = [('sdist', 'source', files[0])]

        job.shell.git('checkout', job.commit, '--', 'setup.py')
        Command.announce = self._log
        dist = run_setup('setup.py')
        dist.run_command('register')
        dist.dist_files = files
        dist.run_command('upload')

    def _log(self, message, level=logging.INFO):
        self.logger.info(message)
        if 'Server response' in message and '200' not in message:
            raise GolemError(message)
        if '(400)' in message or 'Upload failed' in message:
            raise GolemError(message)
