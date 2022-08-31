#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from http.server import HTTPServer, CGIHTTPRequestHandler
from urllib.parse import parse_qs
#import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
import sys
import codecs
from subprocess import check_output, CalledProcessError
import re
import cgi
import hashlib
import tempfile
import atexit
import traceback
import logging
from functools import partial

logger = logging.getLogger(__name__)

if os.name == "nt":
	GIT_HTTP_BACKEND = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
elif os.name == "posix":
	GIT_HTTP_BACKEND = "/usr/lib/git-core/git-http-backend"
else:
	raise Exception(f"git-serve: I don't know where to find 'git-http-backend' binary on {os.name}")

if not os.path.exists(GIT_HTTP_BACKEND):
	raise Exception("git-serve: I can't find 'git-http-backend' binary at {os.path.dirname(GIT_HTTP_BACKEND)}")

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
		r = check_output(cmd,universal_newlines=True)
		return r
		
	@classmethod
	def rev_parse(cls,*args):
		return cls._do("rev-parse", *args)

	@classmethod
	def branch(cls, *args):
		r = cls._do("branch", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n") if b.strip("\n\r *") != ""]

	@classmethod
	def branch_current(cls, *args):
		r = cls._do("branch", *args).strip()
		return ''.join(b.strip("\n\r *") for b in r.split("\n") if b.strip().startswith("*"))

	@classmethod		
	def tag(cls, *args):
		r = cls._do("tag", *args).strip()
		return [b.strip("\n\r *") for b in r.split("\n") if b.strip("\n\r *") != ""]

	@classmethod
	def files(cls, base=".", ref=None):
		if base == "":
			base = "."
		ref = ref or cls.current_ref
		files = cls._do("ls-tree", "--name-only", ref, base).strip()
		dirs = cls._do("ls-tree", "-d","--name-only", ref, base).strip()

		dirs = [b.strip("\n\r") for b in dirs.split("\n") if b.strip("\n\r") != ""]
		if base != "":
			dirset = set([base.strip("/")]+dirs)
		else:
			dirset = set(dirs)
		
		files = [b.strip("\n\r") for b in files.split("\n") if b not in dirset and b.strip("\n\r") != ""]
		
		return sorted(dirs), sorted(files)

	@classmethod
	def show(cls, file, ref):
		ref = ref or cls.current_ref
		return cls._do("show", f"{ref}:{file}")

	@classmethod
	def log(cls, file="", ref=None, n=40):
		if file == "":
			file = "."
		ref = ref or cls.current_ref
		r = cls._do("log", '-'+str(n), '--pretty=format:%h|%x09|%an|%x09|%ad|%x09|%s|%x09|%ae|%x09|%d', '--date=relative', ref, "--", file)
		r = r.strip(" \n\r")
		if r == "":
			return []
		logs = [[r.strip() for r in l.strip(" ").split("|\t|")] for l in r.split("\n")]
		return logs

	@classmethod
	def diff_tree(cls,ref=None):
		ref = ref or cls.current_ref
		r = cls._do("diff-tree", "--no-commit-id", "--name-status", "-r", ref).strip(" \n\r")
		if r == "":
			return []
		r = [l.strip().split("\t") for l in r.split("\n")]
		return r

	@classmethod
	def diff(cls, path="", ref1=None, ref2=None):
		if path == "":
			path = "."
		ref1 = ref1 or cls.current_ref
		ref2 = ref2 or ref1+"~1"
		r = cls._do("diff", ref1, ref2, "--", path)
		if r.strip() == "":
			return None, None, None
		
		ref1 = cls._do("rev-parse","--short", ref1).strip()
		ref2 = cls._do("rev-parse","--short", ref2).strip()
		
		return r, ref1, ref2



class GITServePages(object):
	""" Routing, controllers and template """
	def __init__(self, options):
		self.use_md = not markdown is None
		self.use_pygments = not highlight is None
		if self.use_md:
			print("[#] markdown ", end=" ")
		else:
			print("[ ] markdown ", end=" ")
		if self.use_pygments:
			print("[#] pygments ", end=" ")
		else:
			print("[ ] pygments ", end=" ")
		print()
		
		self.use_gravatar = not options['nogravatar']
		
		if self.use_pygments:
			self.formatter = HtmlFormatter(linenos=False, cssclass="source")
		
		self.tmpdir = tempfile.mkdtemp()
		print ("temp dir: {0}".format(self.tmpdir))
		
		self.routes = {
			re.compile(r'^/$') : self.index,
			re.compile(r'^/refs/$') : self.refs,
			re.compile(r'^/browse(?P<path>.*)$') : self.browse,
			re.compile(r'^/view(?P<path>.*)$') : self.view,
			re.compile(r'^/history(?P<path>.*)$') : self.history,
			re.compile(r'^/commit/(?P<ref>[a-zA-Z0-9]*)/$') : self.commit,
			re.compile(r'^/diff(?P<path>.*)$') : self.diff,
			re.compile(r'^/wiki/(?P<path>.*)$') : self.wiki,
		}
		
	def route(self, request):
		self.request = request
		self.method = request.command

		postvars = {}
		if self.method == "POST":
			ctype, pdict = cgi.parse_header(request.headers.get('content-type'))
			if ctype == 'multipart/form-data':
				postvars = cgi.parse_multipart(request.rfile, pdict)
			elif ctype == 'application/x-www-form-urlencoded':
				length = int(request.headers.get('content-length'))
				postvars = parse_qs(request.rfile.read(length).decode('utf8'), keep_blank_values=1)
		self.post = postvars
		
		path = request.path
		query = ""
		if "?" in path:
			path, query = path.split("?")
			
		self.path_info  = path
		self.query = parse_qs(query)

		controller = None
		kwargs = {}
		
		for route_rg, route_controller in self.routes.items():
			m = route_rg.match(path)
			if m:
				controller = route_controller
				kwargs = m.groupdict()
		
		if not controller is None:
			return controller(**kwargs)

		return None
	
	def _tpl(self, text, title=""):
		style="""
			body {
			  padding: 0px;
			  margin: 0px;
			  font-family: sans-serif;
			  background-color: #eee;
			}
			article {
			  width: 90%;
			  margin: 0px auto;
			}
			header > nav {
			  padding: 20px 5%;
			  background-color: #404e61;
			  color: #fff;
			}
			header > nav > a {
			  color: #ddd;
			}
			header > nav > a:hover {
			  color: #fff;
			}
			footer {
			  margin: 2em 0 0;
			  padding: 10px 5%;
			  background-color: #152a47;
			  color: #fff;
			}
			article > header { 
				margin: 1em 0; 
				border-bottom: 1px solid #404e61;
			}
			article > header > h3 { margin: 0; }
			li.dir {
			  list-style-image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAABTVBMVEUAABRISEhJSUlGTVNMTExRUVFWVlZbW1tfX180ZaQ0ZaU0ZqQ1ZqQ1ZqU2ZqQ2ZqU2Z6U3Z6U4Z6Q3aKY4aKU5aKU6aaVlZWVBbaZqampsbGxubm5FeLJzc3N0dHR4eHh5eXl6enpQg7qAgIB4hpeMjIyNjY1tnM5unM5wns+ZmZmbm5t4o9J5pNN6pNN6pdF+ptOhoaF+p9SioqKBqNWkpKSlpaSlpaWEq9WFq9Wnp6eHrdepqamJrtiqqqqrq6uLsNiLsNmsrKytra2OstmOstqurq6Qs9qRtNqRtNuwsLCRtduStduVttyUt9yVt9yzs7OWuNy0tLSZud2Zut2but22tracut23t7e5ubm7u7u9vb2pxOLBwcDExMTFxcWxyeXHx8fJycm2zea3z+e4z+e4z+i+0um+0+m+0+q+1Oq/1OrB1erE1+vG2Ow1AMXeAAAAAXRSTlMAQObYZgAAALtJREFUGNNjYEAHigpggBCQT0qMj4sLkoMLyMZ7OdvbOampqaqqKksBBaRjneyszE1NncIio4wlgQKS0RL8IMADBJycnMIM4hG8mdnZWVlZGSCQxsXAEcCT4+np7e0DAoEp3AzsbgK5fjDgkczLwGbDlxcCAf6ujqm8DKxmgumhwb4+7i621tYOCbwMLIYiMSZ6UGAUzsvAqC1kqaEOBZoWvAxMWqIGOjCgqw9UoSKmhAAy/AzMnMiAhwEAATQqrYcDKI4AAAAASUVORK5CYII=);
			}
			li.file {
			  list-style-image: url(data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAMAAAAoLQ9TAAAAP1BMVEUAAACBgYGVlZWZmZnExMTFxcXGxsbHx8fIyMjq6urr6+vs7Ozt7eXt7ebt7e3u7u7v7+/w8PDx8fHy8vL///9IyRz5AAAAAXRSTlMAQObYZgAAAGdJREFUGNNlj0sWgCAMA0FFPtUCxfufVahQeZrlTLKIWvUUVaOvKZoBeB9CAMDcgd+M2WusgKYBMQ4Q2E8N3uMBb6PpGE8BvI8pJQFtb51zAthnIuoAH09UBsBWyFQG+HxZ5reL+ucG2iMI0Xh/di8AAAAASUVORK5CYII=);
			}
			header > nav #ref {
			  float: right;
			}
			pre {
			  border: 1px solid #aaa;
			  background-color: #fff;
			  padding: 1em;
			  border-radius: 5px;
			  white-space: pre-wrap;
			}
			table.logs {
			  border: 0px;
			  width: 100%;
			  border-spacing: 0;
			  border-collapse: collapse;
			}
			table.logs td {
			  border-bottom: 1px solid #bbb;
			  padding: 0.5em;
			  margin: 0px;
			}
			table.logs th {
			  text-align: left;
			  padding: 0.2em;
			  margin: 0px;
			}
			.ref {
			  text-decoration: none;
			  font-family: monospace;
			  background-color: #f5f5f5;
			  padding: 0.2em;
			  border-radius: 4px;
			}
			.nw {
			  white-space: nowrap;
			}
			.no {
			  overflow: hidden;
			}
			.tag {
			  display: inline-block;
			  width: 10px;
			  height: 15px;
			  margin: 0px 1px 0px 0px;
			  background-color: #888;
			  mask: url(#maskTag);
			  -webkit-mask: url(#maskTag);
			  -o-mask: url(#maskTag);
			}
			.tag.master {
			  background-color: #e89128;
			}
			.tag.HEAD {
			  background-color: #7ad263;
			}
			.tag.tag_ {
			  background-color: #63b4d2;
			}
			textarea {
			  width: 100%;
			  height: 20em;
			}
			.actions {
			  padding: 0.2em;
			  background-color: #ccc;
			  margin-top: 1em;
			  text-align: right;
			}

		"""
		if self.use_pygments:
			style +=  self.formatter.get_style_defs()
		
		return """<!DOCTYPE html>
			<head>
				<meta charset="UTF-8">
				<title>~{repo_name} {title}</title>
				<style>
					{style}
				</style>
			</head>
			<body>
				<header>
					<nav>
						<strong>~{repo_name}</strong> 
						- <a href="/">home</a>
						- <a href="/browse/">browse</a>
					  	- <a href="/history/">history</a>
					   	- <a href="/refs/">refs</a>
					   	- <a href="/wiki/">wiki</a>
					   	<a href="/refs/" id='ref'>{ref}</a>
				   	</nav>
			   	</header>
				<article>{content}</article>
				<footer>clone this repo: <code>git clone http://{host}:{port}/{repo_name}</code></footer>
				<svg><defs><mask id="maskTag" maskUnits="objectBoundingBox">
					<path style="fill:#ffffff;fill-opacity:1;fill-rule:nonzero;stroke:none" d="M 6.3125 0 C 6.2098764 0.017375 6.1199182 0.0695 6.03125 0.125 C 4.9586289 0.7423 3.8462846 1.38955 2.90625 1.90625 L 0 12.8125 L 5.9375 14.40625 L 8.875 3.5 C 8.288629 2.4692 7.680842 1.43665 7.09375 0.40625 C 6.99554 0.22185 6.8427512 0.08965 6.625 0.03125 C 6.5161246 0.00225 6.4151236 -0.017375 6.3125 0 z M 5.9375 0.96875 C 6.4685738 0.96875 6.90625 1.3751761 6.90625 1.90625 C 6.90625 2.4373239 6.4685738 2.875 5.9375 2.875 C 5.4064261 2.875 4.96875 2.4373239 4.96875 1.90625 C 4.96875 1.3751761 5.4064261 0.96875 5.9375 0.96875 z "  />
					</mask></defs></svg>
			</body>
		""".format(
			title=title,
			repo_name=self.request.repo_name,
			host=self.request.server.server_name,
			port=self.request.server.server_port,
			style=style,
			content=text,
			ref=GIT.current_ref
		)
	
	def _hi(self, text, path="none.txt"):
		fname = os.path.basename(path)
		if not self.use_pygments:
			return "<pre>"+cgi.escape(text)+"</pre>"
		try:
			lexer = get_lexer_for_filename(fname, text)
			return highlight(text, lexer, self.formatter)
		except Exception:
			return "<pre>"+cgi.escape(text)+"</pre>"
	
	def index(self):
		txt_index = "Add a README to see something here. Call it README, README.txt or README.md"
		
		for fname in ('README.md', 'README', 'README.txt'):
			readme = os.path.join(self.request.repo_path, fname)
			if os.path.isfile( readme ):
				with codecs.open(readme, mode="r", encoding="utf-8") as input_file:
					text = input_file.read()
				if self.use_md and fname.endswith(".md"):
					txt_index = markdown.markdown(text)
				else:
					txt_index  = "<pre class='wrap'>{0}</pre>".format(text)
				break
				
		return (200, "text/html", self._tpl(txt_index))
		

	def refs(self):
		if "r" in self.query:
			GIT.current_ref = self.query['r'][0]
			return (302, '', '/history/')
		
		branches = GIT.branch()
		tags = GIT.tag()
		txt = "<ul><a href='?r=HEAD'>HEAD</a></li></ul>"
		if len(branches):
			txt += "<h3>Branches</h3>"
			txt += "<ul>"
			for k in branches:
				txt += "<li><a class='ref' href='?r={0}'>{0}</a></li>".format(k)
			txt += "</ul>"
		else:
			txt += "<h3>No branches</h3>"

		if len(tags):
			txt += "<h3>Tags</h3>"
			txt += "<ul>"
			for k in tags:
				txt += "<li><a class='ref' href='?r={0}'>{0}</a></li>".format(k)
			txt += "</ul>"
		else:
			txt += "<h3>No tags</h3>"
		
		return (200, "text/html", self._tpl(txt))
		

	def browse(self,path):
		path = path.strip("/")
		if path != "":
			path += "/"
		
		dirs, files = GIT.files(path)
		if len(dirs) == 0 and len(files) == 0:
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
			logs = GIT.log(path, ref, n=2)[-1]
		except CalledProcessError:
			logger.exception("git command error")
			return None
		
		txt = "<h3>{0} <span class='ref'>@{1}</span></h3>".format(path, ref)
		txt += "<p><a href='/history/{1}'>History</a> - Show diff: ".format(ref,path, logs[0])
		
		if ref!= logs[0]:
			txt += "<a href='/diff/{1}?ref={2}..{0}'>previus</a> - ".format(ref,path, logs[0])
		
		txt += "<a href='/diff/{1}?ref={0}..HEAD'>HEAD</a></p>".format(ref,path, logs[0])
		txt += self._hi(text, path)
		
		return (200, "text/html", self._tpl(txt))
	
	def history(self, path):
		ref = self.query.get("ref", [None])[0]
		try:
			logs = GIT.log(path.strip("/"), ref=ref)
		except CalledProcessError:
			logger.exception("git command error")
			return None
		
		txt_h = f"<h3>History of {path} <span class='ref'>@{ref}</span></h3>"
		txt_h += f"<form action='/diff/{path}' method='get'>"
		txt_h += "<table class='logs'>"
		txt_h += "<tr><th widht='20%'>author</th><th width='10%'>commit</th><th>message</th><th width='10%'>date</th>"
		
		if path!="/":
			txt_h += "<th width='10%'>diff</th></tr>"
		
		for l in logs:
			if l[5] != "":
				# format tags
				tag_spans = ""
				for t in l[5].strip(" ()").split(","):
					tag_class = t.replace(".","-").replace(":","_")
					tag_spans += "<span class='tag {}' title='{}'></span>".format(tag_class, t)
				l[5] = tag_spans
					
			txt_h += "<tr>"
			
			txt_h += "<td class='nw'>"
			if self.use_gravatar:
				l[4] = hashlib.md5(l[4].lower().encode()).hexdigest()
				txt_h += "<img src='http://www.gravatar.com/avatar/{4}?s=16' width='16' height='16'>"
			txt_h += " {1}</td>".format(*l)
			
			txt_h += "<td class='nw'><a class='ref' href='/commit/{0}/'>{0}</a> {5}</td>".format(*l)
			txt_h += "<td class='no'>{3}</td>".format(*l)
			txt_h += "<td class='nw'>{2}</td>".format(*l)
			
			if path != "/":
				txt_h += "<td class='nw'><input type='radio' name='ref2' value='{0}'>".format(*l)
				txt_h += "<input type='radio' name='ref1' value='{0}'></td>".format(*l)
				
			txt_h += "</tr>"
		txt_h += "</table>"
		
		if path!="/":
			txt_h += "<div class='actions'><input type='submit' value='diff'></div>"

		txt_h += "</form>"		
		return (200, "text/html", self._tpl(txt_h))
		
	def commit(self, ref):
		try:
			files = GIT.diff_tree(ref)
			log = GIT.log(ref=ref, n=1)[0]
		except CalledProcessError:
			logger.exception("git command error")
			return None

		txt = "<h3>Commit <span class='ref'>{0}</a></h3>".format(ref)
		if self.use_gravatar:		
			log[4] = hashlib.md5(log[4].lower().encode()).hexdigest()
			txt += "<p><img src='http://www.gravatar.com/avatar/{4}?s=16'> {1} - {2}</p>"
		else:
			txt += "<p>{1} - {2}</p>"
		txt += "<pre>{3}</pre>"
		txt = txt.format(*log)
		
		txt += "<ul>"
		for f in files:
			txt += "<li><b>{1}</b> <a href='/view/{2}?ref={0}'>{2}</a></li>".format(ref, *f)
		txt += "</ul>"
		
		return (200, "text/html", self._tpl(txt))

	def diff(self,path):
		ref = self.query.get("ref", [None])[0]
		if not ref is None and ".." in ref:
			ref1, ref2 = ref.split("..")
		else:
			ref1, ref2 = ref, None
		
		ref1 = self.query.get("ref1", [ref1])[0]
		ref2 = self.query.get("ref2", [ref2])[0]
		
		ref1 = ref1 or GIT.current_ref
		ref2 = ref2 or f"{ref1}~1"		
		
		path = path.strip("/")
		logs=[]
		try:
			text, dref1, dref2 = GIT.diff(path, ref1, ref2)
			# refs from diff are None when there is no diff.
			ref1 = dref1 or ref1
			ref2 = dref2 or ref2
			logs.append(GIT.log(path, ref1, n=1)[0])
			logs.append(GIT.log(path, ref2, n=1)[0])
		except CalledProcessError:
			logger.exception("git command error")
			return None

		txt = f"<h3>Diff <span class='ref'>{ref1}</span>..<span class='ref'>{ref2}</span> -- {path}</h3>"
		if text is None:
			txt += "<p>Files are identical!</p>"
		else:
			for l in logs:

				txt += "<dl>"
				txt += "<dt><a class='ref' href='/commit/{0}/'>{0}</a> - "
				if self.use_gravatar:
					l[4]=hashlib.md5( l[4].lower().encode() ).hexdigest()
					txt = "<img src='http://www.gravatar.com/avatar/{4}?s=16'>  "
				txt += "{1} - {2}</dt>"
				txt += "<dd><pre>{3}</pre></dd>"
				txt += "</dl>"
				txt = txt.format(*l)
				
			txt += self._hi(text, "diff.patch")
		
		return (200, "text/html", self._tpl(txt))

	def wiki(self, path):
		path = path.strip("/")
		branches = GIT.branch()
		
		if not self.use_md:
			return (200, "text/html", self._tpl("Markdown support is required to use wiki."))
		
		create = False
		if "__wiki" not in branches:
			if self.method == "POST":
				create = int(self.post.get('create',['0'])[0]) == 1
				# to create a wiki, we need to create an empty branch called "__wiki" and add commit to it
				# we add an empty home.md file
				self.post['text'] = ["# Your new wiki home\nEdit this page, use markdown syntax",]
				path = "home"
			else:
				form = """
				<form method='POST'>
					<p><button name='create' value='1' style='font-size:1.2em;padding:0.2em 1em;'>Create the wiki</button></p>
				</form>
				<p><b>WARNING!</b> Wiki function is experimental!</p>
				"""
				return (200, "text/html", self._tpl(form))
		
		if path == "":
			path = "home"
		fpath = f"{path}.md"

		wikiGitDo = partial(GIT._do, f"--work-tree={self.tmpdir}")
				
		# handle POST
		if self.method == "POST":
			text = self.post.get("text",[None])[0]
			action = self.post.get("action",["save"])[0]

			if not text is None:
				orig_branch = GIT.branch_current()
				try:
					if create:
						r = wikiGitDo("checkout", "--orphan", "__wiki")
					else:
						r = wikiGitDo("checkout", "__wiki")
				except CalledProcessError as e:
					return (500, "text/html", self._tpl(f"<pre>{e.output}</pre>", title="wiki"))
	
				if action == "save":
					try:
						with open(os.path.join(self.tmpdir, fpath), "w") as f:
							r = f.write(text)
					except Exception as e:
						r = wikiGitDo("checkout", fpath)
						r = wikiGitDo("checkout", orig_branch)
						return (500, "text/html", self._tpl(f"I'm sorry. Something went wrong saving the page. <pre>{e.message}</pre>", title="wiki"))

					try:
						r = wikiGitDo("add" , fpath)
					except CalledProcessError as e:
						return (500, "text/html", self._tpl(f"<pre>{e.output}</pre>", title="wiki"))
					
					try:
						if create:
							msg = "Created new wiki"
						else:
							msg = f"Modified {path}"
						r = wikiGitDo("commit" , "-m", msg)
					except CalledProcessError as e:
						return (500, "text/html", self._tpl(f"<pre>{e.output}</pre>", title="wiki"))
				
				elif action == "delete":
					try:
						msg = f"Deleted {path}"
						r = wikiGitDo("rm", fpath)
						r = wikiGitDo("commit", "-m", msg)
					except CalledProcessError as e:
						return (500, "text/html", self._tpl(f"<pre>{e.output}</pre>", title="wiki"))
										
					path = "home"

				try:
					r = wikiGitDo("checkout", orig_branch)
				except CalledProcessError as e:
					return (500, "text/html", self._tpl(f"<pre>{e.output}</pre>", title="wiki"))
				
			return (302, '', u'/wiki/{0}'.format(path))
			# end of POST
		
		# handle GET
		log = GIT.log(fpath, ref="__wiki", n=1)
		if len(log) == 0:
			text = "_new page_"
			log = ['','','','','']
		else:
			try:
				text = GIT.show(fpath, ref="__wiki")
			except CalledProcessError as e:
				if e.returncode == 128:
					text = "_new page_"
					log = ['','','','','']
				else:
					raise e
			else:
				log = log[0]

		if "edit" in self.query:
			text = f"""
				<header>
					<h3>{path}</h3> 
				</header>
				<form method='post'>
					<p><textarea name='text'>{text}</textarea></p>
					<div class='actions'>
						<input type='submit' name='action' value='save'>
						<input type='submit' name='action' value='delete'>
				</div>
			"""
		else:
			text = markdown.markdown(text)
			logtext = ""
			if log[0] != '':
				logtext = "<a class='ref' href='/commit/{0}/'>{2}</a> by {1} - <a href='/history/{fpath}?ref=__wiki'>history</a> - ".format(*log, fpath=fpath)
			text = f"""
				<header>
					<h3>{path}</h3> 
					<small>{logtext}<a href='/wiki/{path}?edit=1'>edit</a></small>
				</header>
				<div>{text}</div>
			"""
			
		return (200, "text/html", self._tpl(text, title="wiki"))

class GITRequestHandler(CGIHTTPRequestHandler):
	def translate_path(self, path):
		if path.startswith(self.repo_vfolder):
			r = GIT_HTTP_BACKEND
		else:
			r = CGIHTTPRequestHandler.translate_path(self, path)
		return r
	
	def is_cgi(self):
		is_cgi = CGIHTTPRequestHandler.is_cgi(self)
		if is_cgi and self.path.startswith(self.repo_vfolder):
			head, tail = self.cgi_info 
			self.cgi_info = head, f"{GIT_HTTP_BACKEND_NAME}/{tail}"
		return is_cgi
	
	def _do_pages(self):
		try:
			r = self.pages.route(self)
		except Exception as e:
			tb = "".join(traceback.format_exception(*sys.exc_info()))
			errmsg = f"""<!DOCTYPE html>
				<style>
					body{{
						font-family: sans-serif;
						background-color: #EEE;
						color: #888;
					}}
				</style>
				<body>
				<h1>Server Error</h1>
				<pre>{tb}</pre>
			"""
			r = (500, "text/html", errmsg)
		
		if not r is None:
			self.send_response(r[0])
			if r[0] == 302:
				self.send_header('Location', r[2])
				return False
			self.send_header('Content-type',r[1])
			self.send_header('Accept-Ranges', 'bytes')
			self.send_header('Content-Length', len(r[2]))
			self.end_headers()
			self.wfile.write(r[2].encode("utf-8"))
			return True
		return False
			
	def do_GET(self):
		self._do_pages() or CGIHTTPRequestHandler.do_GET(self)

	def do_POST(self):
		self._do_pages() or CGIHTTPRequestHandler.do_GET(self)


handler = None
def start_serve(git_repo_path, port=8001, options={}):
	global handler
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	os.environ['GIT_PAGER'] = "cat"
	
	server = HTTPServer
	handler = GITRequestHandler
	server_address = ("", port)
	
	repo_name = os.path.basename(git_repo_path)
	
	handler.repo_path = git_repo_path
	handler.repo_name = repo_name
	handler.repo_vfolder = f"/{repo_name}"
	handler.cgi_directories = [f"/{repo_name}"]
	handler.pages = GITServePages(options)
		
	httpd = server(server_address, handler)
	print(f"""
	Serving git repo '{repo_name}'
	
	Web interface at http://{httpd.server_name}:{httpd.server_port}
	git clone http://{httpd.server_name}:{httpd.server_port}/{repo_name}/
		
	CTRL+C to stop.
	""")
	try:
		httpd.serve_forever()	
	except KeyboardInterrupt:
		pass

def cleanup():
	global handler
	import shutil
	if not handler is None:
		print("cleaning up...")
		shutil.rmtree(handler.pages.tmpdir)

atexit.register(cleanup)


if __name__=="__main__":	
	import sys
	import argparse

	parser = argparse.ArgumentParser(description='Serve current git repo via web')
	parser.add_argument('port', metavar='port', type=int, default=8001, nargs='?',
		               help='webserver port (default: 8001)')
	parser.add_argument('--no-gravatar', dest='nogravatar', action='store_true',
		               default=False,
		               help='disable commit avatars')

	args = parser.parse_args()
	
	port = int(args.port)
	
	try:
		repo_path = GIT.rev_parse("--show-toplevel")
	except CalledProcessError as e:
		print(e.output)
		sys.exit(e.returncode)
	repo_path = repo_path.replace("/",os.path.sep).strip()

	start_serve(repo_path, port, {'nogravatar':args.nogravatar})
		
	
	
