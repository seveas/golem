from golem import GolemError
from golem.worker import Worker

class Daemon(Worker):
    def process_job_simple(self, job):
        self.logger.info("Running external command %s" % job.command)
        try:
            job.shell[job.command](input=job.json)
        except Exception as e:
            raise GolemError(str(e))
