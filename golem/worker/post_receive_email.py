from golem.worker import Worker

class Daemon(Worker):
    def process_job_simple(self, job):
        self.logger.info("Sending post receive email")
        script = getattr(job, 'post_receive_email', '/usr/share/git-core/contrib/hooks/post-receive-email')
        job.shell[script](input="%s %s %s\n" % (job.prev_sha1, job.sha1, job.ref))
