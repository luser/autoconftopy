This script aims to translate a configure.in autoconf script into a Python script.

It does this by using an M4 parser to parse the M4 input, and then a shell parser to parse the resulting shell script into an AST and translating that into a Python AST. Neither the M4 parser nor the shell parser aim to be 100% compatible, the goal is to parse just enough to get Mozilla's configure.in working.

The script does not attempt to parse any of the core autoconf m4 scripts, nor any of the aclocal-included scripts. Instead the full set of macros used are defined in the script, and they can be written to emit shell or Python code directly as needed.

Install Dependencies
====================

git clone https://github.com/luser/pym4.git
git clone https://github.com/luser/Meta.git
(cd Meta; git checkout fix-string-format-directive)
hg clone https://bitbucket.org/tedmielczarek/pysh

virtualenv ./venv
. ./venv/bin/activate
(cd Meta; python setup.py install)
export PYTHONPATH=`pwd`/pym4:`pwd`/pysh

Run the script
==============

python autoconf.py < /path/to/configure.in > configure.py

Note: if you are attempting to translate Mozilla's configure.in you will need to apply the configure.patch in this repository.
