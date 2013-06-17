from golem.worker import Worker

class Daemon(Worker):
    name = 'dput'
    logger = 'golem.worker.dput'
    queue = 'golem-publish-dput'
    repo_sync = False

    def process_job_simple(self, job):
        self.logger.info("Publishing debian sources")
        # Fetch packages created in previous task
        files = job.fetch_artefacts(job.requires[0], "*")
        for file in files:
            if not file.endswith('_source.changes'):
                continue
            self.logger.info("Uploading %s to %s" % (file, job.archive))
            job.shell.dput(job.archive, file)
