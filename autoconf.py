#!/usr/bin/env python

import ast
import meta
import os
import re
import sys
from cStringIO import StringIO

import pysh.pyshyacc as pyshyacc
import pysh.interp as interp
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
        expr = ast.parse('sys.stdout.write()').body[0]
        expr.value.args = [ast.Str(msg + '\n')]
        return self.py(expr)

    def AC_MSG_CHECKING(self, args):
        return self.ac_msg('configure: checking ' + args[0])

    def AC_MSG_WARN(self, args):
        return self.ac_msg('configure: warning: ' + args[0])

    def AC_MSG_RESULT(self, args):
        return self.ac_msg(args[0])

    def AC_MSG_ERROR(self, args):
        return self.AC_ERROR(args)

    def AC_ERROR(self, args):
        code = ast.parse('sys.stderr.write()\nsys.exit(1)').body
        code[0].value.args = [ast.Str('configure: error: ' + args[0] + '\n')]
        return self.py(code)

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

class fakedict(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self._gets = set()
    def reset(self):
        self._gets = set()
    def __getitem__(self, key):
        self._gets.add(key)
        return '{%s}' % key

class ShellTranslator:
    def __init__(self, macro_handler, template):
        self.macro_handler = macro_handler
        self.template = template
        # mostly for word expansion
        self.interp = interp.Interpreter(os.getcwd())
           # disable filename expansion
        self.interp._env.set_opt('-f')
        # hack around variable expansion
        self.interp._env._env = fakedict()

    class WrapExpand:
        def __init__(self, translator, interp):
            self.translator = translator
            self.interp = interp
            self.subshell_output = interp.subshell_output
            self.commands = []
            self.var_gets = set()

        def __enter__(self):
            # This is monkeypatching an interp.Interpreter method
            def wrap_subshell(command):
                #XXX: this isn't sufficient. needs to parse command
                cmd = self.translator.make_call(command, call_type='check_output').value
                ret = '{cmd%d}' % len(self.commands)
                self.commands.append(cmd)
                return 0, ret
            self.interp.subshell_output = wrap_subshell
            self.interp._env._env.reset()
            self.var_gets = self.interp._env._env._gets
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.interp.subshell_output = self.subshell_output
            self.interp._env._env.reset()
            return False

    def expand_words(self, words):
        '''
        Returns (wordlist, variables_used, subcommands)
        '''
        with self.WrapExpand(self, self.interp) as wrap:
            args = []
            for word in words:
                args += self.interp.expand_token(word)
            return (args, wrap.var_gets, wrap.commands)

    def expand_variable(self, word):
        '''
        Returns ((status, word), variables_used, subcommands)
        '''
        with self.WrapExpand(self, self.interp) as wrap:
            return (self.interp.expand_variable(word), wrap.var_gets, wrap.commands)

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

    def translate_value(self, value, vars, commands):
        if not vars and not commands:
            # no variable expansion or anything funny
            return ast.Str(value)
        if not commands and len(vars) == 1 and value[1:-1] == list(vars)[0]:
            # simple case, just assigning the value of one var
            # to another
            call = ast.parse('vars.get("","")').body[0].value
            call.args[0].s = list(vars)[0]
            return call
        if len(commands) == 1 and value == '{cmd0}':
            # other simple case, assigning shell command output to var
            return commands[0]
        call = ast.parse('format("", vars, {})').body[0].value
        call.args[0].s = value
        if commands:
            call.args[2].keys = [ast.Str('cmd%d' % i) for i in range(len(commands))]
            call.args[2].values = commands
        return call

    def translate_simpleassignment(self, assign):
        type, (k, v) = assign
        (status, expanded), vars, commands = self.expand_variable((k, v))
        sub = ast.Subscript(ast.Name('vars', ast.Load()),
                            ast.Index(ast.Str(k)),
                            ast.Store())
        return ast.Assign(targets=[sub],
                          value=self.translate_value(expanded, vars, commands))

    thunk_re = re.compile('__python(\d+)__')
    def python_thunk(self, index):
        return self.macro_handler.get_expansion(index)

    def sys_exit(self, ret):
        expr = ast.parse('sys.exit()').body[0]
        expr.value.args = [ret]
        return expr

    def echo(self, s):
        return ast.Print(None, [s], True)

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

    def make_call(self, cmd, call_type=None):
        expr = ast.parse('subprocess.call(shell=True, env=varenv(vars, exports))').body[0]
        call = expr.value
        call.args = []
        if isinstance(cmd, str):
            call.args.append(ast.Str(cmd))
        elif isinstance(cmd, list):
            call.args.append(ast.List([ast.Str(c) for c in cmd], ast.Load()))
        elif isinstance(cmd, ast.AST):
            call.args.append(cmd)
        else:
            raise UnhandledTranslation('Unknown cmd %s' % type(cmd))
        if call_type == 'check_output':
            call.func.attr = call_type
            expr2 = ast.parse('x.rstrip("\\n")').body[0]
            expr2.value.func.value = expr.value
            return expr2
        elif call_type is not None:
            raise UnhandledTranslation('Unknown call_type %s' % call_type)
        return expr

    def translate_simplecommand_words(self, cmd_words):
        words, vars, commands = self.expand_words(cmd_words)
        if not words:
            return []
        m = self.thunk_re.match(words[0])
        if m:
            return self.python_thunk(int(m.group(1)))
        # Special-case some commands
        if words[0] == 'true':
            # not high fidelity, but I can live with this.
            return []
        if words[0] == 'exit':
            return self.sys_exit(self.translate_value(words[1], vars, commands))
        if words[0] == 'echo':
            return self.echo(self.translate_value(words[1], vars, commands))
        if words[0] == 'export':
            #XXX: fix this
            return self.export(words[1:])
        return self.make_call(self.translate_value(' '.join(words), vars, commands))

    def translate_simplecommand(self, cmd):
        if cmd.redirs:
            raise UnhandledTranslation('Unsupported SimpleCommand.redirs')
        if cmd.words:
            return self.translate_simplecommand_words(cmd.words)
        else:
            return [self.translate_simpleassignment(a) for a in cmd.assigns]

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


template_file = os.path.join(os.path.dirname(__file__), 'template.py')
template = ast.parse(open(template_file, 'r').read())

translator = ShellTranslator(macro_handler, template)
translator.translate(stuff)
#meta.asttools.print_ast(template)
sys.stdout.write(meta.dump_python_source(template))
