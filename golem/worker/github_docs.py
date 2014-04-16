from golem.worker import Worker
from golem.repository import github
import os

class Daemon(Worker):
    repo_sync = False

    def process_job_simple(self, job):
        self.logger.info("Uploading documentation to Github")
        files = job.fetch_artefacts(job.requires[0], '*')
        for f in files:
            if f.endswith('.zip'):
                job.shell.unzip('-o', f)
            elif f.endswith(('.tar.gz', 'tar.bz2')):
                job.shell.tar('-xf', f)
            else:
                os.unlink(f)

        if getattr(job, 'nojekyll', 'no').lower() in ('true', 'yes', 'y', '1'):
            open('.nojekyll','w').close()

        gh = github()
        repo = gh.repository(*job.github_repo.split('/'))
        branch = repo.ref('heads/gh-pages')

        files = os.listdir('.')
        if len(files) == 1 and os.path.isdir(files[0]):
            os.chdir(files[0])
            job.shell.defaults['cwd'] = os.path.join(job.work_path, files[0])
            job.pipe.defaults['cwd'] = job.shell.defauls['cwd']

        blobs = []
        for (dir, _, files) in os.walk('.'):
            dir = dir[2:]
            for file in files:
                with open(os.path.join(dir, file)) as fd:
                    sha = repo.create_blob(fd.read().encode('base64'), "base64")
                blobs.append({'path': os.path.join(dir, file), 'mode': '100644', 'type': 'blob', 'sha': sha})
        tree = repo.create_tree(blobs)
        if not branch:
            self.logger.info("Creating gh-pages branch")
            commit = repo.create_commit("Automatic update from commit %s" % job.sha1,
                tree=tree.sha, parents=[],
                author={'name': 'Golem', 'email': 'golem@seveas.net'})
            repo.create_ref('refs/heads/gh-pages', commit.sha)
        else:
            parent = repo.commit(branch.object.sha)
            if tree.sha != parent.commit.tree.sha:
                self.logger.info("Creating new commit")
                commit = repo.create_commit("Automatic update from commit %s" % job.sha1,
                    tree=tree.sha, parents=[parent.sha],
                    author={'name': 'Golem', 'email': 'golem@seveas.net'})
                branch.update(commit.sha)
            else:
                self.logger.info("No change, not creating commit")
