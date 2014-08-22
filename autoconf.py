#!/usr/bin/env python

import ast
import meta
import re
import sys
from cStringIO import StringIO

import pysh.pyshyacc as pyshyacc
from m4 import Parser

MACROS = [
    'AC_PREREQ',
    'AC_INIT',
    'AC_CONFIG_AUX_DIR',
    'AC_CANONICAL_SYSTEM',
    'MOZ_PYTHON',
    'MOZ_DEFAULT_COMPILER',
    'AC_SUBST',
    'MOZ_ARG_DISABLE_BOOL',
    'MOZ_ARG_ENABLE_BOOL',
    'MOZ_ARG_ENABLE_STRING',
    'MOZ_ARG_WITH_STRING',
    'MOZ_ARG_WITH_BOOL',
    'MOZ_ARG_WITHOUT_BOOL',
    'MOZ_ARG_HEADER',
    'AC_MSG_ERROR',
    'MOZ_PATH_PROG',
    'MOZ_PATH_PROGS',
    'AC_DEFINE',
    'AC_DEFINE_UNQUOTED',
    'MOZ_CROSS_COMPILER',
    'AC_PATH_PROG',
    'AC_CHECK_PROGS',
    'AC_PROG_CC',
    'AC_PROG_CXX',
    'AC_PROG_RANLIB',
    'MOZ_TOOL_VARIABLES',
    'MOZ_CHECK_COMPILER_WRAPPER',
    'AC_LANG_SAVE',
    'AC_LANG_C',
    'AC_TRY_COMPILE',
    'AC_LANG_CPLUSPLUS',
    'AC_LANG_RESTORE',
    'AC_MSG_CHECKING',
    'AC_MSG_WARN',
    'AC_CACHE_CHECK',
    'AC_TRY_LINK',
    'MOZ_FIND_WINSDK_VERSION',
    'AC_MSG_RESULT',
    'AC_PROG_CPP',
    'AC_PROG_CXXCPP',
    'AC_PROG_INSTALL',
    'AC_PROG_LN_S',
    'AC_PATH_XTRA',
    'MOZ_ARCH_OPTS',
    'AC_CACHE_VAL',
    'MOZ_ANDROID_STLPORT',
    'MOZ_C_SUPPORTS_WARNING',
    'MOZ_CXX_SUPPORTS_WARNING',
    'MOZ_DOING_LTO',
    'MOZ_CHECK_HEADERS',
    'MOZ_CHECK_HEADER',
    'MOZ_CHECK_COMMON_HEADERS',
    'MOZ_CHECK_CCACHE',
    'AC_PROG_AWK',
    'AC_SUBST_LIST',
    'AC_HEADER_STDC',
    'AC_C_CONST',
    'AC_TYPE_MODE_T',
    'AC_TYPE_OFF_T',
    'AC_TYPE_PID_T',
    'AC_TYPE_SIZE_T',
    'AC_STRUCT_ST_BLKSIZE',
    'AC_HEADER_DIRENT',
    'AC_ARG_ENABLE',
    'AC_CHECK_LIB',
    'AC_SEARCH_LIBS',
    'AC_CHECK_FUNCS',
    'AC_PROG_GCC_TRADITIONAL',
    'AC_FUNC_MEMCMP',
    'AC_HAVE_FUNCS',
    'AM_PATH_NSS',
    'AC_SUBST_SET',
    'AC_OUTPUT_SUBDIRS',
    'MOZ_COMPILER_OPTS',
    'MOZ_CXX11',
    'MOZ_GCC_PR49911',
    'MOZ_GCC_PR39608',
    'MOZ_LLVM_PR8927',
    'MOZ_LINUX_PERF_EVENT',
    'MOZ_CONFIG_NSPR',
    'MOZ_ZLIB_CHECK',
    'MOZ_CONFIG_FFI',
    'PKG_CHECK_MODULES',
    'MOZ_ANDROID_SDK',
    'AC_CHECK_HEADER',
    'AC_ERROR',
    'MOZ_CONFIG_ICU',
    'MOZ_CREATE_CONFIG_STATUS',
    'MOZ_SUBCONFIGURE_ICU',
    'MOZ_SUBCONFIGURE_FFI',
    'MOZ_SUBCONFIGURE_NSPR',
    'MOZ_RUN_CONFIG_STATUS',
    'AM_LANGINFO_CODESET',
]

class MacroHandler:
    def __init__(self):
        self.expansions = []
        self.substs = set()

    def get_expansion(self, index):
        return self.expansions[index]

    def py(self, code):
        if isinstance(code, basestring):
            code = ast.parse(code).body
        index = len(self.expansions)
        self.expansions.append(code)
        return '[__python%d__]' % index

    def AC_SUBST(self, args):
        self.substs.add(args[0])

    def ac_msg(self, msg):
        return self.py('sys.stdout.write(%s)' % repr(msg + '\n'))

    def AC_MSG_CHECKING(self, args):
        return self.ac_msg('checking for ' + args[0])

    def AC_MSG_WARN(self, args):
        return self.ac_msg('warning: ' + args[0])

    def AC_MSG_RESULT(self, args):
        return self.ac_msg(args[0])

    def AC_MSG_ERROR(self, args):
        return self.AC_ERROR(args)

    def AC_ERROR(self, args):
        # string escaping is kind of terrible here
        return self.py('sys.stderr.write(%s)\nsys.exit(1)' % repr(args[0] + '\n'))

p = Parser(sys.stdin.read())
p.changequote('[',']')
macro_handler = MacroHandler()
for m in MACROS:
    if hasattr(macro_handler, m):
        p.macros[m] = getattr(macro_handler, m)
    else:
        # for now replace all other macros with true so the shell parses
        p.macros[m] = lambda x: '[true]'

stream = StringIO()
# Parse m4
p.parse(stream=stream)
shell = stream.getvalue()
if len(sys.argv) > 1:
    sys.stdout.write(shell)
    sys.exit(0)
#open('/tmp/configure.sh','w').write(shell)

# Parse shell
stuff, leftover = pyshyacc.parse(shell, True)

def reduce_depth(thing):
    # Reduce a pipeline of a single command down to that command.
    if isinstance(thing, pyshyacc.Pipeline) and not thing.reverse_status and len(thing.commands) == 1:
        commands = thing.commands[0]
        if isinstance(commands, tuple) and len(commands) == 2:
            commands = commands[1]
        return reduce_depth(commands)
    return thing

class UnhandledTranslation(Exception):
    pass

flatten=lambda l: sum(map(flatten,l),[]) if isinstance(l,list) else [l]

class ShellTranslator:
    def __init__(self, macro_handler, template):
        self.macro_handler = macro_handler
        self.template = template

    def translate_if(self, if_):
        test = flatten(self.translate_commands(if_.cond))
        if len(test) > 1:
            raise UnhandledTranslation('Pipeline in if condition')
        if not test:
            raise UnhandledTranslation('Empty if condition?')
        body = flatten(self.translate_commands(if_.if_cmds))
        if not body:
            body.append(ast.Pass())
        orelse = flatten(self.translate_commands(if_.else_cmds))
        call = test[0].value if isinstance(test[0], ast.Expr) else test[0]
        test_expr = ast.UnaryOp(ast.Not(), call)
        return ast.If(test_expr, body, orelse)

    def translate_case(self, case):
        raise UnhandledTranslation('case')

    def translate_andor(self, andor):
        raise UnhandledTranslation('andor')

    def translate_pipeline(self, pipe):
        raise UnhandledTranslation('pipeline')

    def translate_simpleassignment(self, assign):
        sub = ast.Subscript(ast.Name('vars', ast.Load()),
                            ast.Index(ast.Str(assign[0])),
                            ast.Store())
        return ast.Assign(targets=[sub],
                          value=ast.Str(assign[1]))

    thunk_re = re.compile('__python(\d+)__')
    def python_thunk(self, index):
        return self.macro_handler.get_expansion(index)

    def sys_exit(self, ret):
        expr = ast.parse('sys.exit()').body[0]
        expr.value.args = [ast.Num(int(ret))]
        return expr

    def echo(self, s):
        return ast.Print(None, [ast.Str(s)], True)

    def export(self, exports):
        def mkexport(e):
            bits = e.split('=', 1)
            var = bits[0]
            expr = ast.parse('exports.add()').body[0]
            expr.value.args = [ast.Str(var)]
            if len(e) == 1:
                return expr
            val = e[1]
            return [self.translate_simpleassignment(bits), expr]

        return [mkexport(e) for e in exports]

    def translate_simplecommand_words(self, words):
        words = [w[1] for w in words]
        wordstr = ' '.join(words)
        m = self.thunk_re.match(wordstr)
        if m:
            return self.python_thunk(int(m.group(1)))
        # Special-case some commands
        if wordstr == 'true':
            # not high fidelity, but I can live with this.
            return []
        if words[0] == 'exit':
            return self.sys_exit(words[1])
        if words[0] == 'echo':
            return self.echo(words[1])
        if words[0] == 'export':
            return self.export(words[1:])
        # lazy
        expr = ast.parse('subprocess.call(shell=True, env=varenv(vars, exports))').body[0]
        call = expr.value
        # FIXME: this doesn't handle word expansion (variables etc)
        call.args = [ast.Str(wordstr)]
        return expr

    def translate_simplecommand(self, cmd):
        if cmd.redirs:
            raise UnhandledTranslation('Unsupported SimpleCommand.redirs')
        if cmd.words:
            return self.translate_simplecommand_words(cmd.words)
        else:
            return [self.translate_simpleassignment(a[1]) for a in cmd.assigns]

    def translate_redirectlist(self, redirs):
        raise UnhandledTranslation('redirectlist')

    def translate_subshell(self, subshell):
        raise UnhandledTranslation('subshell')

    def translate_commands(self, v):
        if isinstance(v, list):
            return [self.translate_commands(c) for c in v]
        if isinstance(v, tuple):
            if len(v)==2 and isinstance(v[0], str) and not isinstance(v[1], str):
                if v[0] == 'async':
                    raise UnhandledTranslation('Unsupported async command')
                else:
                    return self.translate_commands(v[1])
            return self.translate_commands(list(v))

        v = reduce_depth(v)

        if isinstance(v, pyshyacc.IfCond):
            return self.translate_if(v)
        elif isinstance(v, pyshyacc.CaseCond):
            return self.translate_case(v)
        elif isinstance(v, pyshyacc.ForLoop):
            return self.translate_for(v)
        elif isinstance(v, pyshyacc.AndOr):
            return self.translate_andor(v)
        elif isinstance(v, pyshyacc.Pipeline):
            return self.translate_pipeline(v)
        elif isinstance(v, pyshyacc.SimpleCommand):
            return self.translate_simplecommand(v)
        elif isinstance(v, pyshyacc.RedirectList):
            return self.translate_redirectlist(v)
        elif isinstance(v, pyshyacc.SubShell):
            return self.translate_subshell(v)
        else:
            raise UnhandledTranslation('Unhandled thing: %s' % repr(v))

    def translate(self, commands):
        main = filter(lambda x: isinstance(x, ast.FunctionDef) and x.name == 'main', self.template.body)[0]
        main.body.extend(flatten(self.translate_commands(commands)))
        substassign = filter(lambda x: isinstance(x, ast.Assign) and x.targets[0].id == 'SUBSTS', self.template.body)[0]
        substassign.value.args = [ast.Str(s) for s in self.macro_handler.substs]


template = ast.parse("""
import os
import sys
import subprocess

SUBSTS = set()

def varenv(vars, exports):
    env = {}
    for e in exports:
        env[e] = vars[e]
    return env

def main(args):
    vars = dict(os.environ)
    exports = set(vars.keys())

if __name__ == '__main__':
    main(sys.argv)
""")

translator = ShellTranslator(macro_handler, template)
translator.translate(stuff)
#meta.asttools.print_ast(template)
sys.stdout.write(meta.dump_python_source(template))
