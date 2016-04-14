git-serve
=========

Git custom command to serve a repo over http.
Presents a web interface to browse the repo, history, tags and branches, and to view file diffs.

### Install

On linux should be enough to copy it on PATH, without .py, and to make it executable

    cp git-serve.py /usr/local/bin/git-serve
    chmod +x /usr/local/bin/git-serve

On windows use PyInstaller to make a one-file executable, then copy it on PATH 

    PyInstaller -F git-serve.py
    copy dist\git-serve.exe c:\windows


#### Optional dependencies

`markdown` to display README.md as home page, if present in repo

    pip install markdown

`pygments` to display syntax hilight when display files content

    pip install pygments

### Use

	git-serve.py [-h] [--no-gravatar] [port]

	Serve current git repo via web

	positional arguments:
	  port           webserver port (default: 8001)

	optional arguments:
	  -h, --help     show this help message and exit
	  --no-gravatar  disable commit avatars

    
The current repo will be avaiable at `http://[your ip]:[port]/`

