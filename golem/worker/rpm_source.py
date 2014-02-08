from golem.worker import Worker, GolemError, GolemRetryLater
import os
import glob
import rpm

class Daemon(Worker):
    repo_checkout = False
    release_git_lock = False

    def process_job_simple(self, job):
        self.logger.info("Building source rpm")
        # Fetch packages created in previous task
        files = job.fetch_artefacts(job.requires[0], job.tarball)
        tarball = files[0]

        # If version script: get version from there
        if hasattr(job, 'version_script'):
            # Check out specfile
            self.checkout(job.rpm_branch, job)
            spec = rpm.ts().parseSpec(job.specfile).sourceHeader

            job.run_hook('pre-version-mangle')
            job.version_script.append(job.sha1)
            res = job.shell[job.version_script[0]](*job.version_script[1:])
            gitversion = res.stdout.strip()

            if gitversion != spec['Version']:
                # Correct the version, release and name of directory in the specfile
                job.shell.sed('-e', r's/^\(Version:[[:space:]]\+\).*/\1%s/' % gitversion, '-i', job.specfile)
                job.shell.sed('-e', r's/^\(Release:[[:space:]]\+\).*/\11/', '-i', job.specfile)
                job.shell.sed('-e', r's/^\(Source0:[[:space:]]\+\).*/\1%s/' % tarball, '-i', job.specfile)
                dirname = job.shell.tar('-tf', tarball, output_callback=None).stdout.split('\n')[0]
                dirname = dirname[:dirname.find('/')]
                job.shell.sed('-e', r's/^%%setup.*/& -n %s/' % dirname, '-i', job.specfile)
            job.run_hook('post-version-mangle')

        # Do we have rpm/* tags?
        elif getattr(job, 'use_tags', 'no').lower() in ('true', 't', 'yes', 'y', '1'):
            # Do we have a debian tag?
            tags = job.shell.git('tag', '-l', 'rpm/%s*' % job.ref[10:]).stdout.strip().split()
            if not tags:
                raise GolemRetryLater("RPM tag not found yet")
            else:
                tags.sort()
                self.checkout(tags[-1], job)

        # Detect the commit on the rpm branch
        else:
            # Which commit on the rpm branch do we want:
            # - Assume master is always merged into rpm
            # - Go through the first-parent history of rpm..current_commit
            # - If the earliest commit isn't a merge containing a rpm dir: unclean merge, abort
            # - If this is the first commit on the rpm branch, and has only one parent: it's the start of the debian branch
            # - Walk forward in history until encountering another merge with master (one parent has no rpm dir), we want the one just before that
            commits = job.shell.git('rev-list', '--parents', '--ancestry-path', 
                                    '--first-parent', '%s..%s' % (job.sha1, job.rpm_branch))
            commits = [x.split() for x in commits.stdout.splitlines()]
            commits.reverse() # Let's walk forward in time
            if not commits:
                # No commit added yet
                # Try without --first-parent to see if there is *any* path
                commits = job.shell.git('rev-list', '--parents', '--ancestry-path', 
                                        '%s..%s' % (job.sha1, job.rpm_branch))
                if commits.stdout.strip():
                    raise GolemError("First commit after %s is not a merge into the %s branch (1)" % (job.ref, job.rpm_branch))
                raise GolemRetryLater()
            if len(commits[0]) != 3 and not job.shell.git('ls-tree', commits[0][0], '--', job.specfile).stdout:
                raise GolemError("First commit after %s is not a merge into the %s branch (2)" % (job.ref, job.rpm_branch))
            if not job.shell.git('ls-tree', commits[0][0], job.specfile).stdout.strip():
                raise GolemError("First commit after %s is not a merge into the %s branch (3)" % (job.ref, job.rpm_branch))

            good_commit = commits[0][0]
            for commit in commits[1:]:
                if len(commit) > 2:
                    # Assume that if a specfile exists in the parent, it's not master
                    # Because merges might mean other branches (pull requests) got merged
                    for parent in commit[1:]:
                        if job.shell.git('ls-tree', parent, '--', job.specfile).stdout:
                            break
                    else:
                        break
                good_commit = commit[0]

            self.checkout(good_commit, job)

        job.run_hook('pre-build')
        job.shell.rpmbuild('-bs', '--nodeps', '--define', '_sourcedir %s' % os.getcwd(), '--define', '_srcrpmdir %s' % job.artefact_path, job.specfile)
        job.run_hook('post-build')

    def checkout(self, commit, job):
        job.run_hook('pre-spec-checkout')
        job.shell.git('checkout', commit, '--', job.specfile)
        job.run_hook('post-spec-checkout')
        for source in rpm.ts().parseSpec(job.specfile).sources:
            try:
                job.shell.git('checkout', commit, '--', os.path.basename(source[0]))
            except GolemError:
                if source[0].startswith(('http://', 'https://')):
                    job.shell.wget(source[0])
        job.run_hook('post-source-download')
        self.lockfile.release()
