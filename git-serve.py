#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
try:
	from BaseHTTPServer import HTTPServer
	from CGIHTTPServer import CGIHTTPRequestHandler
	from urlparse import parse_qs
except ImportError:
	from http.server import HTTPServer, CGIHTTPRequestHandler
	from urllib.parse import parse_qs

#import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
import codecs
from subprocess import check_output,CalledProcessError
import re
import cgi

if os.name == "nt":
	GIT_HTTP_BACKEND = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
elif os.name == "posix":
	GIT_HTTP_BACKEND = "/usr/lib/git-core/git-http-backend"
else:
	raise Exception("git-serve: i don't know where to find 'git-http-backend' on %s" % os.name)

GIT_HTTP_BACKEND_NAME = os.path.basename(GIT_HTTP_BACKEND)

try:
	import markdown
except ImportError:
	markdown = None

try:
	from pygments import highlight
	from pygments.lexers import guess_lexer, get_lexer_for_filename
	from pygments.formatters import HtmlFormatter
except ImportError:
	highlight = None


class GIT:
	"""stupid git cli interface"""
	current_ref = "HEAD"
	@classmethod
	def _do(cls, *cmd):
		cmd = ['git']+list(cmd)
		return check_output(cmd,universal_newlines=True)
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
	def log(cls, file="", _ref=None, n=20):
		ref = _ref or cls.current_ref
		r = cls._do("log", '-'+str(n) ,'--pretty=format:%h%x09%an%x09%ad%x09%s', ref, "--",file)
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
		print("git serve use markdown:{0}, pygments:{1}".format(self.use_md, self.use_pygments))
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
		self.query = parse_qs(query)

		view = None
		kwargs = {}
		
		for k, v in self.routes.items():
			m = k.match(path)
			if m:
				view = v
				kwargs = m.groupdict()
		
		if not view is None:
			return view(**kwargs)
		return None
	
	def _tpl(self, text):
		style=u"""body{padding:0px;margin:0px;font-family:sans-serif;background-color:#eee}article{width:90%;margin:0px auto}header{padding:20px 5%;background-color:#404e61;color:#fff}header>a{color:#DDD}header>a:hover{color:#fff}footer{padding:10px 5%;background-color:#152a47;color:#fff}
		li.dir{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAABTVBMVEUAABRISEhJSUlGTVNMTExRUVFWVlZbW1tfX180ZaQ0ZaU0ZqQ1ZqQ1ZqU2ZqQ2ZqU2Z6U3Z6U4Z6Q3aKY4aKU5aKU6aaVlZWVBbaZqampsbGxubm5FeLJzc3N0dHR4eHh5eXl6enpQg7qAgIB4hpeMjIyNjY1tnM5unM5wns+ZmZmbm5t4o9J5pNN6pNN6pdF+ptOhoaF+p9SioqKBqNWkpKSlpaSlpaWEq9WFq9Wnp6eHrdepqamJrtiqqqqrq6uLsNiLsNmsrKytra2OstmOstqurq6Qs9qRtNqRtNuwsLCRtduStduVttyUt9yVt9yzs7OWuNy0tLSZud2Zut2but22tracut23t7e5ubm7u7u9vb2pxOLBwcDExMTFxcWxyeXHx8fJycm2zea3z+e4z+e4z+i+0um+0+m+0+q+1Oq/1OrB1erE1+vG2Ow1AMXeAAAAAXRSTlMAQObYZgAAALtJREFUGNNjYEAHigpggBCQT0qMj4sLkoMLyMZ7OdvbOampqaqqKksBBaRjneyszE1NncIio4wlgQKS0RL8IMADBJycnMIM4hG8mdnZWVlZGSCQxsXAEcCT4+np7e0DAoEp3AzsbgK5fjDgkczLwGbDlxcCAf6ujqm8DKxmgumhwb4+7i621tYOCbwMLIYiMSZ6UGAUzsvAqC1kqaEOBZoWvAxMWqIGOjCgqw9UoSKmhAAy/AzMnMiAhwEAATQqrYcDKI4AAAAASUVORK5CYII=);}
		li.file{list-style-image:url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAAP1BMVEUAAACBgYGVlZWZmZnExMTFxcXGxsbHx8fIyMjq6urr6+vs7Ozt7eXt7ebt7e3u7u7v7+/w8PDx8fHy8vL///9IyRz5AAAAAXRSTlMAQObYZgAAAGdJREFUGNNlj0sWgCAMA0FFPtUCxfufVahQeZrlTLKIWvUUVaOvKZoBeB9CAMDcgd+M2WusgKYBMQ4Q2E8N3uMBb6PpGE8BvI8pJQFtb51zAthnIuoAH09UBsBWyFQG+HxZ5reL+ucG2iMI0Xh/di8AAAAASUVORK5CYII=);}
		header .ref{float:right}pre{border:1px solid #AAA;background-color:#fff;padding: 1em;border-radius:5px}pre.wrap{white-space:pre-wrap}
		"""
		if self.use_pygments:
			style +=  self.formatter.get_style_defs()
		
		return u"""<!DOCTYPE html><head><meta coding='utf-8'><title>~{repo_name}</title>
		<style>{style}</style>
		</head>
		<body>
		<header><strong>~{repo_name}</strong> - <a href="/">home</a> - <a href="/browse/">browse</a> - <a href="/history/">history</a><a href="/refs/" class='ref'>{ref}</a></header>
		<article>{content}</article>
		<footer>clone this repo: <code>git clone http://{host}:{port}/{repo_name}</code></footer>
		</body>
		""".format(
			repo_name = self.request.repo_name,
			host = self.request.server.server_name,
			port = self.request.server.server_port,
			style=style,
			content = text,
			ref = GIT.current_ref
		)
	
	def _hi(self, text, path="none.txt"):
		fname = os.path.basename(path)
		if not self.use_pygments:
			return u"<pre>"+cgi.escape(text)+"</pre>"
		#~ try:
		lexer = get_lexer_for_filename(fname, text)
		return highlight(text, lexer, self.formatter)
		#~ except Exception:
			#~ return text
	
	def index(self):
		for fname in ('README.md', 'README', 'README.txt'):
			readme = os.path.join(self.request.repo_path, fname)
			if os.path.isfile( readme ):
				with codecs.open(readme, mode="r", encoding="utf-8") as input_file:
					text = input_file.read()
				if self.use_md and fname.endswith(".md"):
					txt_index = markdown.markdown(text)
				else:
					txt_index  = u"<pre class='wrap'>{0}</pre>".format(text)
				break
			else:
				txt_index=u"Add a README to see something here. Call it README, README.txt or README.md"
		return (200, "text/html", self._tpl(txt_index))
		

	def refs(self):
		if "r" in self.query:
			GIT.current_ref = self.query['r'][0]
		
		branches = GIT.branch()
		tags = GIT.tag()
		txt = u"<ul><a href='?r=HEAD'>HEAD</a></li></ul>"
		if len(branches):
			txt += u"<h3>Branches</h3>"
			txt += u"<ul>"
			for k in branches:
				txt += u"<li><a href='?r={0}'>{0}</a></li>".format(k)
			txt += u"</ul>"
		else:
			txt += u"<h3>No branches</h3>"

		if len(tags):
			txt += u"<h3>Tags</h3>"
			txt += u"<ul>"
			for k in tags:
				txt += u"<li><a href='?r={0}'>{0}</a></li>".format(k)
			txt += u"</ul>"
		else:
			txt += u"<h3>No tags</h3>"
		return (200, "text/html", self._tpl(txt))
		

	def browse(self,path):
		path = path.strip(u"/")
		if path!="":
			path+=u"/"
		dirs, files = GIT.files(path)
		if len(dirs)==0 and len(files)==0:
			return None
		if path!="":
			dirs = [path+".."] + dirs
		txt_browse = u"<h3>"+path+u"</h3>"
		txt_browse += u"<ul>"
		for name in dirs:
			name = name.replace(path,"")
			txt_browse += u"<li class='dir'><a href='/browse/{0}{1}'>{1}</a></li>".format(path,name)
		for name in files:
			name = name.replace(path,"")
			txt_browse += u"<li class='file'><a href='/view/{0}{1}'>{1}</a></li>".format(path,name)
		txt_browse += u"</ul>"
		return (200, "text/html", self._tpl(txt_browse))
	
	def view(self, path):
		ref = self.query.get('ref', [GIT.current_ref])[0]
		path = path.strip(u"/")
		try:
			text = GIT.show(path, ref)
			logs = GIT.log(path, ref,2)[1]
		except CalledProcessError:
			return None
		txt = u"<h3>{0} ({1})</h3>".format(path, ref)
		txt += u"<p><a href='/history/{1}'>History</a> - Show diff: <a href='/diff/{1}?ref={0}..{2}'>previus</a> - <a href='/diff/{1}?ref=HEAD..{0}'>HEAD</a></p>".format(ref,path, logs[0]) 
		txt += self._hi(text, path)
		
		return (200, "text/html", self._tpl(txt))
	
	def history(self, path):
		try:
			logs = GIT.log(path.strip("/"))
		except CalledProcessError:
			return None
		txt_h = u"<h3>History of {1} ({0})</h3>".format(GIT.current_ref, path)
		for l in logs:
			txt_h += u"<dl>"
			txt_h += u"<dt><em><a href='/commit/{0}/'>{0}</a></em> - {1} - {2}</dt>".format(*l)
			txt_h += u"<dd><pre>{3}</pre></dd>".format(*l)
			txt_h += u"</dl>"
		return (200, "text/html", self._tpl(txt_h))
		
	def commit(self, ref):
		try:
			files = GIT.diff_tree(ref)
			log = GIT.log("", ref,1)[0]
		except CalledProcessError:
			return None
		
		txt = u"<h3>Commit {0}</h3>".format(ref)
		txt += u"<p>{1} - {2}</p>".format(*log)
		txt += u"<pre>{3}</pre>".format(*log)
		txt += u"<ul>"
		for f in files:
			txt += u"<li><b>{1}</b> <a href='/view/{2}?ref={0}'>{2}</a></li>".format(ref, *f)
		txt += u"</ul>"
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
			logs.append( GIT.log(path, ref1,1)[0] )
			logs.append( GIT.log(path, ref2,1)[0] )
		except CalledProcessError:
			return None

		txt = u"<h3>Diff {1}..{2} -- {0}</h3>".format( path, ref1, ref2)		
		if text is None:
			txt += u"<p>Files are identical!</p>"
		else:
			for l in logs:
				txt += u"<dl>"
				txt += u"<dt><em><a href='/commit/{0}/'>{0}</a></em> - {1} - {2}</dt>".format(*l)
				txt += u"<dd><pre>{3}</pre></dd>".format(*l)
				txt += u"</dl>"
			txt += self._hi(text, "diff.patch")
		return (200, u"text/html", self._tpl(txt))

 
class GITRequestHandler(CGIHTTPRequestHandler):
	def translate_path(self, path):
		if path.startswith(self.repo_vfolder ):
			r = GIT_HTTP_BACKEND
		else:
			r = CGIHTTPRequestHandler.translate_path(self, path)
		return r
	
	def is_cgi(self):
		r = CGIHTTPRequestHandler.is_cgi(self)
		if r and self.path.startswith(self.repo_vfolder ):
			head, tail = self.cgi_info 
			self.cgi_info = head, GIT_HTTP_BACKEND_NAME + "/" + tail
		return r
	
	def do_GET(self):
		r = self.pages.route(self)
		if not r is None:
			self.send_response(r[0])
			self.send_header('Content-type',r[1])
			self.send_header('Accept-Ranges', 'bytes')
			self.send_header('Content-Length', len(r[2]))
			self.end_headers()
			self.wfile.write(r[2].encode("utf-8"))
			return
		
		CGIHTTPRequestHandler.do_GET(self)

def start_serve(git_repo_path, port=8001):
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	os.environ['GIT_PAGER'] = "cat"
	
	server = HTTPServer
	handler = GITRequestHandler
	server_address = ("", port)
	
	repo_name = os.path.basename(git_repo_path)
	
	handler.repo_path = git_repo_path
	handler.repo_name = repo_name
	handler.repo_vfolder = "/"+repo_name
	handler.cgi_directories = ["/"+repo_name]
	handler.pages = GITServePages()
	
	httpd = server(server_address, handler)
	print (
		"""Serving git repo '{0}'
		Web interface at http://{1}:{2}
		print "git clone http://{1}:{2}/{0}/""".format(repo_name, httpd.server_name, httpd.server_port)
	)
	
	httpd.serve_forever()	


if __name__=="__main__":	
	import sys
	#~ try:
		#~ print(GIT.diff())
	#~ except CalledProcessError, e:
		#~ print(e.output)	
	#~ sys.exit()
	
	port = 8001
	if len(sys.argv)>1 and sys.argv[1].isdigit():
		port = int(sys.argv[1])
	
	try:
		repo_path = GIT.rev_parse("--show-toplevel")
	except CalledProcessError as e:
		print(e.output)
		sys.exit(e.returncode)
	print(repo_path)
	repo_path = repo_path.replace("/",os.path.sep).strip()

	start_serve(repo_path, port)
	
	
