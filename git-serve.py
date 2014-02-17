# -*- coding: utf-8 -*-
#!/usr/bin/env python
 
import BaseHTTPServer
import CGIHTTPServer
import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
 
class GITRequestHandler(CGIHTTPServer.CGIHTTPRequestHandler):
	def translate_path(self, path):
		if path.startswith("/git"):
			r = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
		else:
			r = CGIHTTPServer.CGIHTTPRequestHandler.translate_path(self, path)
		return r
	def is_cgi(self):
		r = CGIHTTPServer.CGIHTTPRequestHandler.is_cgi(self)
		if self.path.startswith("/git") and self.cgi_info[1]=="":
			self.cgi_info = self.cgi_info[0], "./"
		return r

def start_serve(git_repo_path):
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	
	server = BaseHTTPServer.HTTPServer
	handler = GITRequestHandler
	server_address = ("", 8001)
	handler.cgi_directories = ["/git"]
	
	print "Serving git repo '%s' on port 8001" % git_repo_path
	print "Clone on /git/"
	httpd = server(server_address, handler)
	httpd.serve_forever()	


if __name__=="__main__":	
	import sys
	from subprocess import check_output,CalledProcessError
	
	try:
		repo_path = check_output(["git", "rev-parse", "--show-toplevel"])
	except CalledProcessError, e:
		print e.output
		sys.exit(e.returncode)
	repo_path = repo_path.replace("/",os.path.sep).strip()
	start_serve(repo_path)
	
	
