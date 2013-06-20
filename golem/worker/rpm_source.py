from golem.worker import Worker, GolemError
import os
import glob
import rpm

class Daemon(Worker):
    repo_checkout = False

    def process_job_simple(self, job):
        self.logger.info("Building source rpm")
        # Fetch packages created in previous task
        job.fetch_artefacts(job.requires[0], job.tarball)
        tarball = glob.glob(job.tarball)[0]

        job.shell.git('checkout', job.rpm_branch, '--', '*')
        specfile = glob.glob('*.spec')[0]
        spec = rpm.ts().parseSpec(specfile).sourceHeader

        if hasattr(job, 'version_script'):
            job.version_script.append(job.commit)
            res = job.shell[job.version_script[0]](*job.version_script[1:])
            gitversion = res.stdout.strip()

            if gitversion != spec['Version']:
                # Correct the version, release and name of directory in the specfile
                job.run_hook('pre-version-mangle')
                job.shell.sed('-e', r's/^\(Version:[[:space:]]\+\).*/\1%s/' % gitversion, '-i', specfile)
                job.shell.sed('-e', r's/^\(Release:[[:space:]]\+\).*/\11/', '-i', specfile)
                job.shell.sed('-e', r's/^\(Source0:[[:space:]]\+\).*/\1%s/' % tarball, '-i', specfile)
                dirname = job.shell.tar('-tf', tarball, output_callback=None).stdout.split('\n')[0]
                dirname = dirname[:dirname.find('/')]
                job.shell.sed('-e', r's/^%%setup.*/& -n %s/' % dirname, '-i', specfile)
                job.run_hook('post-version-mangle')

        job.run_hook('pre-build')
        job.shell.rpmbuild('-bs', '--nodeps', '--define', '_sourcedir %s' % os.getcwd(), '--define', '_srcrpmdir %s' % job.artefact_path, specfile)
        job.run_hook('post-build')
