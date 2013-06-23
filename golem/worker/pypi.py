from golem import GolemError
from golem.worker import Worker
from distutils.core import run_setup, Command, Distribution, PyPIRCCommand
import logging
import getpass
import os,sys
import requests

class Daemon(Worker):
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Uploading package to PyPI")
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

    @staticmethod
    def login():
        cmd = PyPIRCCommand(Distribution())
        cf = cmd._get_rc_file()
        if os.path.exists(cf):
            print >>sys.stderr, "%s already exists. Remove to relogin" % cf
            sys.exit(1)
        user = raw_input("PyPI user: ").strip()
        password = getpass.getpass("PyPI password: ")
        resp = requests.post(cmd.DEFAULT_REPOSITORY, auth=(user, password), data={':action': 'login'})
        if resp.status_code != 200:
            print >>sys.stderr, "Login failed"
            sys.exit(1)
        cmd._store_pypirc(user, password)
