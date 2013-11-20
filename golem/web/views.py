from flask.views import View
from flask import render_template, current_app, redirect, url_for, request, send_file, g
import os
import beanstalkc
import json

class TemplateView(View):
    def render(self, context):
        return render_template(self.template_name, **context)

class IndexView(TemplateView):
    template_name = 'index.html'

    def dispatch_request(self):
        return self.render({'repos': current_app.config['REPOS']})

class RepoView(TemplateView):
    template_name = 'repo.html'

    def dispatch_request(self, repo):
        repo = current_app.config['REPOS'][repo]
        return self.render({'repo': repo})

class RunView(TemplateView):
    template_name = 'run.html'

    def dispatch_request(self, repo, ref, sha1):
        repo = current_app.config['REPOS'][repo]
        commit = repo.commit(ref, sha1, g.db)
        actions = repo.actions_for(ref, sha1, g.db)
        actions = [x for x in actions if x['start_time']] + [x for x in actions if not x['start_time']]
        return self.render({'repo': repo, 'commit': commit, 'actions': actions})

class ArtefactView(View):
    def dispatch_request(self, repo, ref, sha1, action, filename):
        repo = current_app.config['REPOS'][repo]
        path = os.path.join(repo.path, 'artefacts', action, '%s@%s' % (ref, sha1), filename)
        mimetype = None
        if filename == 'log':
            mimetype = 'text/plain'
        return send_file(path, attachment_filename=os.path.basename(filename), as_attachment=False, mimetype=mimetype)

class QueueView(TemplateView):
    template_name = 'queues.html'

    def dispatch_request(self):
        host, port = current_app.config['BEANSTALK_SERVER'].split(':')
        bs = beanstalkc.Connection(host, int(port))
        queues = dict([(x, {'name': x, 'jobs': [], 'stats': None}) for x in bs.tubes() if x.startswith('golem-')])
        for queue in queues:
            bs.watch(queue)
            bs.use(queue)
            queues[queue]['stats'] = qstats = bs.stats_tube(queue)
        bs.close()

        return self.render({'queues': queues})
