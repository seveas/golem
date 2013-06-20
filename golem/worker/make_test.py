from golem.worker import Worker

class Daemon(Worker):
    def setup(self, job):
        for what in ('configure', 'make', 'make_test'):
            args = getattr(job, '%s_args' % what, [])
            if isinstance(args, str):
                args = [args]
            want = args or getattr(job, what, 'no').lower() in ('1', 'true', 'yes')
            setattr(job, what, want)
            setattr(job, '%s_args' % what, args)
        if not job.make_test_args:
            job.make_test_args = ['test']

    def process_job_simple(self, job):
        self.logger.info("Compiling and running tests")
        if job.configure:
            job.run_hook('pre-configure')
            job.shell['./configure'](*job.configure_args)
        if job.make:
            job.run_hook('pre-make')
            job.shell.make(*job.make_args)
        job.run_hook('pre-test')
        job.shell.make(*job.make_test_args)
