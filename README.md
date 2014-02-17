git-serve
=========

Git custom command to serve a repo over http

### Install

On linux should be enough to copy it on PATH, without .py, and to make it executable

    cp git-serve.py /usr/local/bin/git-serve
    chmod +x /usr/local/bin/git-serve

On windows use PyInstaller to make a one-file executable, then copy it on PATH 

    PyInstaller -F git-serve.py
    copy dist\git-serve.exe c:\windows


### Use

    git serve [port]

`port` defaults to 8001
    
The current repo will be avaiable to clone at `http://[your ip]:[port]/[your repo folder name]/`

