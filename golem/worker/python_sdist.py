from golem.worker import Worker

class Daemon(Worker):
    name = 'python-sdist'
    logger = 'golem.worker.python-sdist'
    queue = 'golem-build-python-sdist'

    def process_job_simple(self, job):
        self.logger.info("Building tarball")
        job.run_hook('pre-dist')
        job.shell.python('setup.py', 'sdist')
        job.run_hook('post-dist')
