from golem.worker import Worker
import os

class Daemon(Worker):
    name = 'sphinx'
    logger = 'golem.worker.sphinx'
    queue = 'golem-build-sphinx'

    def process_job_simple(self, job):
        self.logger.info("Building documentation")
        job.run_hook('pre-build')
        zipfile = os.path.join(job.doctype + '.zip')
        job.shell.make('clean', job.doctype, cwd=os.path.join(job.work_path, job.docdir))
        job.shell.zip(zipfile, '-r', '.', cwd=os.path.join(job.work_path, job.docdir, '_build', job.doctype))
        os.rename(os.path.join(job.work_path, job.docdir, '_build', job.doctype, zipfile), os.path.join(job.artefact_path, zipfile))
