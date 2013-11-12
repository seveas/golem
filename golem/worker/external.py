from golem.worker import Worker
import os

class Daemon(Worker):
    def process_job_simple(self, job):
        self.logger.info("Running external command %s" % job.command)
        job.shell[job.command](input=job.json)
