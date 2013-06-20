from golem.worker import Worker

class Daemon(Worker):
    def process_job_simple(self, job):
        self.logger.info("Building tarball")
        job.run_hook('pre-dist')
        job.shell.python('setup.py', 'sdist')
        job.run_hook('post-dist')
