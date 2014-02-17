# -*- coding: utf-8 -*-
#!/usr/bin/env python
 
import BaseHTTPServer
import CGIHTTPServer
#import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
 
class GITRequestHandler(CGIHTTPServer.CGIHTTPRequestHandler):
	def translate_path(self, path):
		if path.startswith(self.repo_name):
			r = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
		else:
			r = CGIHTTPServer.CGIHTTPRequestHandler.translate_path(self, path)
		return r
	def is_cgi(self):
		r = CGIHTTPServer.CGIHTTPRequestHandler.is_cgi(self)
		if r and self.path.startswith(self.repo_name):
			head, tail = self.cgi_info 
			self.cgi_info = head, "git-http-backend.exe/" + tail
		return r

def start_serve(git_repo_path, port=8001):
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	
	server = BaseHTTPServer.HTTPServer
	handler = GITRequestHandler
	server_address = ("", port)
	
	repo_name = os.path.basename(git_repo_path)
	
	handler.repo_name = "/"+repo_name
	handler.cgi_directories = ["/"+repo_name]
	
	print "Serving git repo '%s' on 0.0.0.0:%s" % (repo_name, port)
	print "git clone http://<host ip>:%s/%s/" % (port,repo_name)
	httpd = server(server_address, handler)
	httpd.serve_forever()	


if __name__=="__main__":	
	import sys
	from subprocess import check_output,CalledProcessError

	
	port = 8001
	if len(sys.argv)>1 and sys.argv[1].isdigit():
		port = int(sys.argv[1])
	
	try:
		repo_path = check_output(["git", "rev-parse", "--show-toplevel"])
	except CalledProcessError, e:
		print e.output
		sys.exit(e.returncode)
	repo_path = repo_path.replace("/",os.path.sep).strip()

	start_serve(repo_path, port)
	
	
