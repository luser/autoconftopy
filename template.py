import fnmatch
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

class quoted:
    def __init__(self, q):
        self.q = q

def for_loop(things, vars, extra):
    for t in things:
        if isinstance(t, quoted):
            yield format(t.q, vars, extra)
        else:
            for x in format(t, vars, extra).split():
                yield x

def match(thing, pattern):
    if '*' not in pattern and '?' not in pattern:
        return thing == pattern
    return fnmatch.fnmatch(thing, pattern)

def main(args):
    vars = dict(os.environ)
    # set positional parameters
    for i, a in enumerate(args):
        vars['argv%d' % i] = a
    exports = set(vars.keys())

if __name__ == '__main__':
    main(sys.argv)
