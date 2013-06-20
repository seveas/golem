from golem.worker import Worker
from golem import GolemError
import os

class Daemon(Worker):
    def process_job_simple(self, job):
        self.logger.info("Building tarball")
        job.run_hook('pre-dist')
        if os.path.exists('Build.pl'):
            job.shell.perl('./Build.pl', 'dist')
        elif os.path.exists('Makefile.PL'):
            job.shell.perl('./Makefile.PL')
            job.shell.make('dist')
        else:
            raise GolemError("Only dists using Extutils::MakeMaker or Module::Build are supported")
        job.run_hook('post-dist')
