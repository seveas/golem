from golem.worker import Worker

class Daemon(Worker):
    name = 'post-receive-email'
    queue = 'golem-publish-post-receive-email'
    logger = 'golem.worker.post-receive-email'

    def process_job_simple(self, job):
        self.logger.info("Sending post receive email")
        script = getattr(job, 'post_receive_email', '/usr/share/git-core/contrib/hooks/post-receive-email')
        job.shell[script](input="%s %s %s\n" % (job.old_commit, job.commit, job.ref))
