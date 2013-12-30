from golem.worker import Worker
from golem import GolemError, GolemRetryLater
import glob
import os
from whelk import shell

class Daemon(Worker):
    repo_sync = False

    def process_job_simple(self, job):
        self.logger.info("Publishing sources with osc")
        # Clean older sources
        for file in glob.glob(os.path.join(job.osc_path, '*')):
            os.unlink(file)
        
        # Fetch packages created in previous task and add to package
        for action in job.requires:
            files = job.fetch_artefacts(action, "*")
            for src in files:
                if src.endswith('_source.changes'):
                    for f in job.shell.dcmd(src).stdout.strip().split():
                        os.rename(f, os.path.join(job.osc_path, f))
                elif src.endswith('.src.rpm'):
                    job.pipe(job.pipe.rpm2cpio(src) | job.pipe.cpio('-i', cwd=job.osc_path))
        job.shell.osc('ar', cwd=job.osc_path)
        job.shell.osc('ci', '-m', 'Automated update by golem', cwd=job.osc_path)
        
    def setup(self, job):
        osc_root = os.path.join(self.repo_dir, job.repo, 'osc')
        job.osc_path = os.path.join(osc_root, job.package)
        if not os.path.exists(osc_root):
            os.makedirs(osc_root)
        if not os.path.exists(job.osc_path):
            self.logger.info("Checking out package %s" % job.package)
            job.shell.osc('co', job.package, cwd=osc_root)
        if job.shell.osc('status', cwd=job.osc_path).stdout.strip():
            raise GolemRetryLater("Package checkout in %s unclean, aborting" % job.osc_path)
        self.logger.info("Pulling updates from openbuildservice")
        job.shell.osc('up', cwd=job.osc_path)

    @staticmethod
    def login():
        shell.osc('my', 'pkg', redirect=False)
