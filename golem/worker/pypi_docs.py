from golem.worker import Worker
from golem import GolemError
from distutils.core import PyPIRCCommand, Distribution
import requests
import os

class Daemon(Worker):
    repo_sync = False

    def process_job_simple(self, job):
        self.logger.info("Uploading documentation to PyPI")
        files = job.fetch_artefacts(job.requires[0], '*')
        for f in files:
            if f.endswith('.zip'):
                Upload(Distribution({'name':job.pypi_dist})).upload(f)
            elif f.endswith(('.tar.gz', 'tar.bz2')):
                raise NotImplementedError("Can only handle zipfiles for now")

class Upload(PyPIRCCommand):
    def upload(self, fn):
        config = self._read_pypirc()
        resp = requests.post(config['repository'], auth=(config['username'], config['password']),
            data = {':action': 'doc_upload', 'name': self.distribution.metadata.get_name()},
            files = {'content': (fn, open(fn, 'rb'))}
        )
        if resp.status_code != 200:
            raise GolemError("Upload failed: %s" % resp.text)
