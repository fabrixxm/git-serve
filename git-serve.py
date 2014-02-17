# -*- coding: utf-8 -*-
#!/usr/bin/env python
 
import BaseHTTPServer
import CGIHTTPServer
import urlparse
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

try:
	from pygments import highlight
	from pygments.lexers import guess_lexer
	from pygments.formatters import HtmlFormatter
except ImportError:
	highlight = None	

class GIT:
	"""stupid git cli interface"""
	current_ref = "HEAD"
	@classmethod
	def _do(cls, *cmd):
		cmd = ['git']+list(cmd)
		#~ print "#cmd: ", cmd
		return check_output(cmd)
	@classmethod
	def rev_parse(cls,*args):
		return cls._do("rev-parse", *args)
	@classmethod
	def branch(cls, *args):
		r = cls._do("branch", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n") if b.strip("\n\r *")!=""]
	@classmethod		
	def tag(cls, *args):
		r = cls._do("tag", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n") if b.strip("\n\r *")!=""]
	@classmethod
	def files(cls, base="", _ref=None):
		ref = _ref or cls.current_ref
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
	def show(cls, file, _ref):
		ref = _ref or cls.current_ref
		return cls._do("show", ref+":"+file)
	@classmethod
	def log(cls, file="", _ref=None):
		ref = _ref or cls.current_ref
		r = cls._do("log", '--pretty=format:%h%x09%an%x09%ad%x09%s', ref, "--",file)
		r = r.strip()
		logs = [ l.strip().split("\t") for l in r.split("\n") ]
		return logs
	@classmethod
	def diff_tree(cls,ref=None):
		_ref = ref or cls.current_ref
		r = cls._do("diff-tree", "--no-commit-id", "--name-status", "-r" , _ref)
		r = [ l.strip().split("\t") for l in r.strip().split("\n") ]
		return r
	@classmethod
	def diff(cls, path="", ref1=None, ref2=None):
		ref1 = ref1 or cls.current_ref
		ref2 = ref2 or ref1+"~1"
		r = cls._do("diff", ref1, ref2, "--", path)
		if r.strip()=="":
			return None,None,None
		#r = r.strip().split("\n")
		
		ref1 = cls._do("rev-parse","--short", ref1).strip()
		ref2 = cls._do("rev-parse","--short", ref2).strip()
		
		return r, ref1, ref2 #"\n".join(r[4:]), ref1, ref2
		

class GITServePages(object):
	def __init__(self):
		self.use_md = not markdown is None
		self.use_pygments = not highlight is None
		if self.use_pygments:
			self.formatter = HtmlFormatter(linenos=False, cssclass="source")
		self.routes = {
			re.compile(r'^/$') : self.index,
			re.compile(r'^/refs/$') : self.refs,
			re.compile(r'^/browse(?P<path>.*)$') : self.browse,
			re.compile(r'^/view(?P<path>.*)$') : self.view,
			re.compile(r'^/history(?P<path>.*)$') : self.history,
			re.compile(r'^/commit/(?P<ref>[a-zA-Z0-9]*)/$') : self.commit,
			re.compile(r'^/diff(?P<path>.*)$') : self.diff,
		}
		
	def route(self, request):
		self.request = request
		
		path = request.path
		query = ""
		if "?" in path:
			path, query = path.split("?")
			
		self.path_info  = path
		self.query = urlparse.parse_qs(query)

		view = None
		kwargs = {}
		
		for k, v in self.routes.iteritems():
			m = k.match(path)
			if m:
				view = v
				kwargs = m.groupdict()
		
		if not view is None:
			return view(**kwargs)
		return None
	
	def _tpl(self, text):
		style="""body{padding:0px;margin:0px;font-family:sans-serif;background-color:#eee}article{width:90%;margin:0px auto}header{padding:20px 5%;background-color:#404e61;color:#fff}header>a{color:#DDD}header>a:hover{color:#fff}footer{padding:10px 5%;background-color:#152a47;color:#fff}
		li.dir{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAABTVBMVEUAABRISEhJSUlGTVNMTExRUVFWVlZbW1tfX180ZaQ0ZaU0ZqQ1ZqQ1ZqU2ZqQ2ZqU2Z6U3Z6U4Z6Q3aKY4aKU5aKU6aaVlZWVBbaZqampsbGxubm5FeLJzc3N0dHR4eHh5eXl6enpQg7qAgIB4hpeMjIyNjY1tnM5unM5wns+ZmZmbm5t4o9J5pNN6pNN6pdF+ptOhoaF+p9SioqKBqNWkpKSlpaSlpaWEq9WFq9Wnp6eHrdepqamJrtiqqqqrq6uLsNiLsNmsrKytra2OstmOstqurq6Qs9qRtNqRtNuwsLCRtduStduVttyUt9yVt9yzs7OWuNy0tLSZud2Zut2but22tracut23t7e5ubm7u7u9vb2pxOLBwcDExMTFxcWxyeXHx8fJycm2zea3z+e4z+e4z+i+0um+0+m+0+q+1Oq/1OrB1erE1+vG2Ow1AMXeAAAAAXRSTlMAQObYZgAAALtJREFUGNNjYEAHigpggBCQT0qMj4sLkoMLyMZ7OdvbOampqaqqKksBBaRjneyszE1NncIio4wlgQKS0RL8IMADBJycnMIM4hG8mdnZWVlZGSCQxsXAEcCT4+np7e0DAoEp3AzsbgK5fjDgkczLwGbDlxcCAf6ujqm8DKxmgumhwb4+7i621tYOCbwMLIYiMSZ6UGAUzsvAqC1kqaEOBZoWvAxMWqIGOjCgqw9UoSKmhAAy/AzMnMiAhwEAATQqrYcDKI4AAAAASUVORK5CYII=);}
		li.file{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAAP1BMVEUAAACBgYGVlZWZmZnExMTFxcXGxsbHx8fIyMjq6urr6+vs7Ozt7eXt7ebt7e3u7u7v7+/w8PDx8fHy8vL///9IyRz5AAAAAXRSTlMAQObYZgAAAGdJREFUGNNlj0sWgCAMA0FFPtUCxfufVahQeZrlTLKIWvUUVaOvKZoBeB9CAMDcgd+M2WusgKYBMQ4Q2E8N3uMBb6PpGE8BvI8pJQFtb51zAthnIuoAH09UBsBWyFQG+HxZ5reL+ucG2iMI0Xh/di8AAAAASUVORK5CYII=);}
		header .ref{float:right}pre{border:1px solid #AAA;background-color:#fff;padding: 1em;border-radius:10px;}
		"""
		if self.use_pygments:
			style +=  self.formatter.get_style_defs()
		
		return """<!DOCTYPE html><head><title>{repo_name}</title>
		<style>{style}</style>
		</head>
		<body>
		<header><strong>{repo_name}</strong> - <a href="/">home</a> - <a href="/browse/">browse</a> - <a href="/history/">history</a><a href="/refs/" class='ref'>{ref}</a></header>
		<article>{content}</article>
		<footer>clone this repo: <code>git clone http://{host}:{port}{repo_name}</code></footer>
		</body>
		""".format(
			repo_name = self.request.repo_name,
			host = self.request.server.server_name,
			port = self.request.server.server_port,
			style=style,
			content = text,
			ref = GIT.current_ref
		)
	
	def _hi(self, text):
		if not self.use_pygments:
			return "<pre>"+text+"</pre>"
		#~ try:
		lexer = guess_lexer(text)
		return highlight(text, lexer, self.formatter)
		#~ except Exception:
			#~ return text
	
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
		

	def refs(self):
		if "r" in self.query:
			GIT.current_ref = self.query['r'][0]
		
		branches = GIT.branch()
		tags = GIT.tag()
		txt = "<ul><a href='?r=HEAD'>HEAD</a></li></ul>"
		if len(branches):
			txt += "<h3>Branches</h3>"
			txt += "<ul>"
			for k in branches:
				txt += "<li><a href='?r={0}'>{0}</a></li>".format(k)
			txt += "</ul>"
		else:
			txt += "<h3>No branches</h3>"

		if len(tags):
			txt += "<h3>Tags</h3>"
			txt += "<ul>"
			for k in tags:
				txt += "<li><a href='?r={0}'>{0}</a></li>".format(k)
			txt += "</ul>"
		else:
			txt += "<h3>No tags</h3>"
		return (200, "text/html", self._tpl(txt))
		

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
		ref = self.query.get('ref', [GIT.current_ref])[0]
		path = path.strip("/")
		try:
			text = GIT.show(path, ref)
			logs = GIT.log(path, ref)[1]
		except CalledProcessError:
			return None
		txt = "<h3>{0} ({1})</h3>".format(path, ref)
		txt += "<p>Show diff: <a href='/diff/{1}?ref={0}..{2}'>previus</a> - <a href='/diff/{1}?ref=HEAD..{0}'>HEAD</a></p>".format(ref,path, logs[0]) 
		txt += self._hi(text)
		
		return (200, "text/html", self._tpl(txt))
	
	def history(self, path):
		try:
			logs = GIT.log(path.strip("/"))
		except CalledProcessError:
			return None
		txt_h = "<h3>History of {1} ({0})</h3>".format(GIT.current_ref, path)
		for l in logs:
			txt_h += "<dl>"
			txt_h += "<dt><em><a href='/commit/{0}/'>{0}</a></em> - {1} - {2}</dt>".format(*l)
			txt_h += "<dd><pre>{3}</pre></dd>".format(*l)
			txt_h += "</dl>"
		return (200, "text/html", self._tpl(txt_h))
		
	def commit(self, ref):
		try:
			files = GIT.diff_tree(ref)
			log = GIT.log("", ref)[0]
		except CalledProcessError:
			return None
		
		txt = "<h3>Commit {0}</h3>".format(ref)
		txt += "<p>{1} - {2}</p>".format(*log)
		txt += "<pre>{3}</pre>".format(*log)
		txt += "<ul>"
		for f in files:
			txt += "<li><b>{1}</b> <a href='/view/{2}?ref={0}'>{2}</a></li>".format(ref, *f)
		txt += "</ul>"
		return (200, "text/html", self._tpl(txt))

	def diff(self,path):
		ref = self.query.get("ref", [None])[0]
		if ".." in ref:
			ref1, ref2 = ref.split("..")
		else:
			ref1, ref2 = ref, None
			
		ref1 = ref1 or GIT.current_ref
		ref2 = ref2 or ref1+"~1"		
		
		path = path.strip("/")
		logs=[]
		try:
			text, ref1, ref2 = GIT.diff(path, ref1, ref2)
			logs.append( GIT.log(path, ref1)[0] )
			logs.append( GIT.log(path, ref2)[0] )
		except CalledProcessError:
			return None

		txt = "<h3>Diff {1}..{2} -- {0}</h3>".format( path, ref1, ref2)		
		if text is None:
			txt += "<p>Files are identical!</p>"
		else:
			for l in logs:
				txt += "<dl>"
				txt += "<dt><em><a href='/commit/{0}/'>{0}</a></em> - {1} - {2}</dt>".format(*l)
				txt += "<dd><pre>{3}</pre></dd>".format(*l)
				txt += "</dl>"
			txt += self._hi(text)
		return (200, "text/html", self._tpl(txt))

 
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
	os.environ['GIT_PAGER'] = "cat"
	
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
	#~ try:
		#~ print GIT.diff()
	#~ except CalledProcessError, e:
		#~ print e.output	
	#~ sys.exit()
	
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
	
	
