import os
import string
import subprocess
import sys

from collections import defaultdict

SUBSTS = set()

def varenv(vars, exports):
    env = {}
    for e in exports:
        env[e] = vars[e]
    return env

def format(s, vars, extra):
    d = defaultdict(str, vars)
    for k,v in extra.iteritems():
        d[k] = v
    return string.Formatter().vformat(s, (), d)

def main(args):
    vars = dict(os.environ)
    # set positional parameters
    for i, a in enumerate(args):
        vars[str(i)] = a
    exports = set(vars.keys())

if __name__ == '__main__':
    main(sys.argv)
