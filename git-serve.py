# -*- coding: utf-8 -*-
#!/usr/bin/env python
 
import BaseHTTPServer
import CGIHTTPServer
#import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
import codecs 
from subprocess import check_output,CalledProcessError
import re

if os.name == "nt":
	GIT_HTTP_BACKEND = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
elif os.name == "linux":
	GIT_HTTP_BACKEND = "/usr/lib/git-core/git-http-backend"
else:
	raise Exception("git-serve: i don't know where to find 'git-http-backend' on %s" % os.name)

try:
	import markdown
except ImportError:
	markdown = None

class GIT:
	"""stupid git cli interface"""
	@classmethod
	def _do(cls, *cmd):
		cmd = ['git']+list(cmd)
		return check_output(cmd)
	@classmethod
	def rev_parse(cls,*args):
		return cls._do("rev-parse", *args)
	@classmethod
	def branch(cls, *args):
		r = cls._do("branch", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n")]
	@classmethod		
	def tag(cls, *args):
		r = cls._do("tag", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n")]
	@classmethod
	def files(cls, base="", ref="HEAD"):
		files = cls._do("ls-tree", "--name-only", ref, base).strip()
		dirs = cls._do("ls-tree", "-d","--name-only", ref, base).strip()

		dirs = [b.strip("\n\r") for b in dirs.split("\n") if b.strip("\n\r")!=""]
		if base!="":
			dirset = set([base.strip("/")]+dirs)
		else:
			dirset = set(dirs)
		
		files = [ b.strip("\n\r") for b in files.split("\n") if b not in dirset and b.strip("\n\r")!="" ]
		
		return sorted(dirs), sorted(files)
	@classmethod
	def show(cls, file, ref="HEAD"):
		return cls._do("show", ref+":"+file)

class GITServePages(object):
	def __init__(self):
		self.use_md = not markdown is None
		self.routes = {
			re.compile(r'^/$') : self.index,
			re.compile(r'^/browse(?P<path>.*)$') : self.browse,
			re.compile(r'^/view(?P<path>.*)$') : self.view,
		}
		
	def route(self, request):
		self.request = request
		
		path = request.path
		query = None
		if "?" in path:
			path, query = path.split("?")
			
		self.path_info  = path
		self.query_string = query

		view = None
		kwargs = {}
		
		print "route",path
		
		for k, v in self.routes.iteritems():
			m = k.match(path)
			if m:
				view = v
				kwargs = m.groupdict()
		
		if not view is None:
			return view(**kwargs)
		return None
	
	def _tpl(self, text):
		style="""body{padding:0px;margin:0px;font-family:sans-serif}article{width:90%;margin:0px auto}header{padding:20px 5%;background-color:#404e61;color:#fff}header>a{color:#DDD}header>a:hover{color:#fff}footer{padding:10px 5%;background-color:#152a47;color:#fff}
		li.dir{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAABTVBMVEUAABRISEhJSUlGTVNMTExRUVFWVlZbW1tfX180ZaQ0ZaU0ZqQ1ZqQ1ZqU2ZqQ2ZqU2Z6U3Z6U4Z6Q3aKY4aKU5aKU6aaVlZWVBbaZqampsbGxubm5FeLJzc3N0dHR4eHh5eXl6enpQg7qAgIB4hpeMjIyNjY1tnM5unM5wns+ZmZmbm5t4o9J5pNN6pNN6pdF+ptOhoaF+p9SioqKBqNWkpKSlpaSlpaWEq9WFq9Wnp6eHrdepqamJrtiqqqqrq6uLsNiLsNmsrKytra2OstmOstqurq6Qs9qRtNqRtNuwsLCRtduStduVttyUt9yVt9yzs7OWuNy0tLSZud2Zut2but22tracut23t7e5ubm7u7u9vb2pxOLBwcDExMTFxcWxyeXHx8fJycm2zea3z+e4z+e4z+i+0um+0+m+0+q+1Oq/1OrB1erE1+vG2Ow1AMXeAAAAAXRSTlMAQObYZgAAALtJREFUGNNjYEAHigpggBCQT0qMj4sLkoMLyMZ7OdvbOampqaqqKksBBaRjneyszE1NncIio4wlgQKS0RL8IMADBJycnMIM4hG8mdnZWVlZGSCQxsXAEcCT4+np7e0DAoEp3AzsbgK5fjDgkczLwGbDlxcCAf6ujqm8DKxmgumhwb4+7i621tYOCbwMLIYiMSZ6UGAUzsvAqC1kqaEOBZoWvAxMWqIGOjCgqw9UoSKmhAAy/AzMnMiAhwEAATQqrYcDKI4AAAAASUVORK5CYII=);}
		li.file{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAAP1BMVEUAAACBgYGVlZWZmZnExMTFxcXGxsbHx8fIyMjq6urr6+vs7Ozt7eXt7ebt7e3u7u7v7+/w8PDx8fHy8vL///9IyRz5AAAAAXRSTlMAQObYZgAAAGdJREFUGNNlj0sWgCAMA0FFPtUCxfufVahQeZrlTLKIWvUUVaOvKZoBeB9CAMDcgd+M2WusgKYBMQ4Q2E8N3uMBb6PpGE8BvI8pJQFtb51zAthnIuoAH09UBsBWyFQG+HxZ5reL+ucG2iMI0Xh/di8AAAAASUVORK5CYII=);}
		"""
		return """<!DOCTYPE html><head><title>{repo_name}</title>
		<style>{style}</style>
		</head>
		<body>
		<header><strong>{repo_name}</strong> - <a href="/">home</a> - <a href="/browse/">browse</a></header>
		<article>{content}</article>
		<footer>clone this repo: <code>git clone http://{host}:{port}{repo_name}</code></footer>
		</body>
		""".format(
			repo_name = self.request.repo_name,
			host = self.request.server.server_name,
			port = self.request.server.server_port,
			style=style,
			content = text
		)
	
	def index(self):
		readme = os.path.join(self.request.repo_path, "README.md")
		if os.path.isfile( readme ):
			with codecs.open(readme, mode="r", encoding="utf-8") as input_file:
				text = input_file.read()
			if self.use_md:
				txt_index = markdown.markdown(text)
			else:
				txt_index  = text
		else:
			txt_index="Add a README.md to see something here!"
		return (200, "text/html", self._tpl(txt_index))
		return None

	def browse(self,path):
		path = path.strip("/")
		if path!="":
			path+="/"
		dirs, files = GIT.files(path)
		if len(dirs)==0 and len(files)==0:
			return None
		if path!="":
			dirs = [path+".."] + dirs
		txt_browse = "<h3>"+path+"</h3>"
		txt_browse += "<ul>"
		for name in dirs:
			name = name.replace(path,"")
			txt_browse += "<li class='dir'><a href='/browse/{0}{1}'>{1}</a></li>".format(path,name)
		for name in files:
			name = name.replace(path,"")
			txt_browse += "<li class='file'><a href='/view/{0}{1}'>{1}</a></li>".format(path,name)
		txt_browse += "</ul>"
		return (200, "text/html", self._tpl(txt_browse))
	
	def view(self, path):
		try:
			text = GIT.show(path.strip("/"))
		except CalledProcessError:
			return None
		text = "<pre>{0}</pre>".format(text)
		return (200, "text/html", self._tpl(text))
 
class GITRequestHandler(CGIHTTPServer.CGIHTTPRequestHandler):
	def translate_path(self, path):
		if path.startswith(self.repo_name):
			r = GIT_HTTP_BACKEND
		else:
			r = CGIHTTPServer.CGIHTTPRequestHandler.translate_path(self, path)
		return r
	
	def is_cgi(self):
		r = CGIHTTPServer.CGIHTTPRequestHandler.is_cgi(self)
		if r and self.path.startswith(self.repo_name):
			head, tail = self.cgi_info 
			self.cgi_info = head, "git-http-backend.exe/" + tail
		return r
	
	def do_GET(self):
		r = self.pages.route(self)
		if not r is None:
			self.send_response(r[0])
			self.send_header('Content-type',r[1])
			self.send_header('Accept-Ranges', 'bytes')
			self.send_header('Content-Length', len(r[2]))
			self.end_headers()
			self.wfile.write(r[2])
			return
		
		CGIHTTPServer.CGIHTTPRequestHandler.do_GET(self)

def start_serve(git_repo_path, port=8001):
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	
	server = BaseHTTPServer.HTTPServer
	handler = GITRequestHandler
	server_address = ("", port)
	
	repo_name = os.path.basename(git_repo_path)
	
	handler.repo_path = git_repo_path
	handler.repo_name = "/"+repo_name
	handler.cgi_directories = ["/"+repo_name]
	handler.pages = GITServePages()
	
	print "Serving git repo '%s' on 0.0.0.0:%s" % (repo_name, port)
	print "Web interface at http://<host ip>:%s/" % port
	print "git clone http://<host ip>:%s/%s/" % (port,repo_name)
	httpd = server(server_address, handler)
	httpd.serve_forever()	


if __name__=="__main__":	
	import sys
	
	
	port = 8001
	if len(sys.argv)>1 and sys.argv[1].isdigit():
		port = int(sys.argv[1])
	
	try:
		repo_path = GIT.rev_parse("--show-toplevel")
	except CalledProcessError, e:
		print e.output
		sys.exit(e.returncode)
	repo_path = repo_path.replace("/",os.path.sep).strip()

	start_serve(repo_path, port)
	
	
