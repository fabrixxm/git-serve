# -*- coding: utf-8 -*-
#!/usr/bin/env python
 
import BaseHTTPServer
import CGIHTTPServer
#import cgitb; cgitb.enable()  ## This line enables CGI error reporting
import os
 
class GITRequestHandler(CGIHTTPServer.CGIHTTPRequestHandler):
	def translate_path(self, path):
		print "translate_path", path, self.repo_name
		if path.startswith(self.repo_name):
			r = "C:\\Program Files (x86)\\Git\\libexec\\git-core\\git-http-backend.exe"
		else:
			r = CGIHTTPServer.CGIHTTPRequestHandler.translate_path(self, path)
		print "-" * 40
		return r
	def is_cgi(self):
		r = CGIHTTPServer.CGIHTTPRequestHandler.is_cgi(self)
		print "is_cgi", self.path, r, self.repo_name
		if r and self.path.startswith(self.repo_name):
			head, tail = self.cgi_info 
			self.cgi_info = head, "git-http-backend.exe/" + tail
			print "\t\t",self.cgi_info
		print "-" * 40
		return r

def start_serve(git_repo_path):
	os.environ['GIT_PROJECT_ROOT'] = git_repo_path
	os.environ['GIT_HTTP_EXPORT_ALL'] = "1"
	
	server = BaseHTTPServer.HTTPServer
	handler = GITRequestHandler
	server_address = ("", 8001)
	
	repo_name = os.path.basename(git_repo_path)
	
	handler.repo_name = "/"+repo_name
	handler.cgi_directories = ["/"+repo_name]
	
	print "Serving git repo '%s' on 0.0.0.0:8001" % repo_name
	print "git clone http://<host ip>:8001/%s/" % repo_name
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
	
	
