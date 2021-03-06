# This file is part of Marcel.
# 
# Marcel is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or at your
# option) any later version.
# 
# Marcel is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Marcel.  If not, see <https://www.gnu.org/licenses/>.

import marcel.argsparser
import marcel.core
import marcel.exception
import marcel.functionwrapper
import marcel.opmodule
import marcel.util


# ----------------------------------------------------------------------------------------------------------------------

# Parsing errors

class UnexpectedTokenError(marcel.exception.KillCommandException):

    SNIPPET_SIZE = 10

    def __init__(self, token, message):
        super().__init__(message)
        self.token = token
        self.message = message

    def __str__(self):
        if self.token is None:
            return 'Premature end of input'
        else:
            token_start = self.token.start
            token_text = self.token.text
            snippet_start = max(token_start - UnexpectedTokenError.SNIPPET_SIZE, 0)
            snippet_end = max(token_start + UnexpectedTokenError.SNIPPET_SIZE + 1, len(token_text))
            snippet = token_text[snippet_start:snippet_end]
            return f'Parsing error at position {token_start - snippet_start} of "...{snippet}...": {self.message}'


class PrematureEndError(UnexpectedTokenError):

    def __init__(self):
        super().__init__(None, None)


class UnknownOpError(marcel.exception.KillCommandException):

    def __init__(self, op_name):
        super().__init__(op_name)
        self.op_name = op_name

    def __str__(self):
        return f'Unknown command: {self.op_name}'


class MalformedStringError(marcel.exception.KillCommandException):

    def __init__(self, text, message):
        super().__init__(message)
        self.text = text


class ParseError(marcel.exception.KillCommandException):

    def __init__(self, message):
        super().__init__(message)


class EmptyCommand(marcel.exception.KillCommandException):

    def __init__(self):
        super().__init__(None)


# ----------------------------------------------------------------------------------------------------------------------

# Tokens

class Source:
    def __init__(self, text, position=0):
        self.text = text
        self.start = position
        self.end = position

    def __repr__(self):
        name = self.__class__.__name__
        if self.start is None or self.end is None:
            text = '' if self.text is None else self.text
        else:
            assert self.text is not None
            text = self.text[self.start:self.end]
        return f'{name}({text})'

    def peek_char(self):
        c = None
        if self.end < len(self.text):
            c = self.text[self.end]
        return c

    def next_char(self):
        c = None
        if self.end < len(self.text):
            c = self.text[self.end]
            self.end += 1
        return c

    def remaining(self):
        return len(self.text) - self.end

    def raw(self):
        return self.text[self.start:self.end]


class Token(Source):
    # Special characters that need to be escaped for python strings
    ESCAPABLE = '''\\\'\"\a\b\f\n\r\t\v'''
    SINGLE_QUOTE = "'"
    DOUBLE_QUOTE = '"'
    QUOTES = SINGLE_QUOTE + DOUBLE_QUOTE
    ESCAPE_CHAR = '\\'
    OPEN = '('
    CLOSE = ')'
    PIPE = '|'
    BANG = '!'
    FORK = '@'
    BEGIN = '['
    END = ']'
    ASSIGN = '='
    COMMENT = '#'
    COMMA = ','
    COLON = ':'
    STRING_TERMINATING = [OPEN, CLOSE, PIPE, BEGIN, END, ASSIGN, COMMENT, COMMA, COLON]

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position)
        self.adjacent_to_previous = adjacent_to_previous

    def value(self, parser):
        return None

    def is_string(self):
        return False

    def is_fork(self):
        return False

    def is_bang(self):
        return False

    def is_pipe(self):
        return False

    def is_expr(self):
        return False

    def is_begin(self):
        return False

    def is_end(self):
        return False

    def is_assign(self):
        return False

    def is_comma(self):
        return False

    def is_colon(self):
        return False

    def op_name(self):
        return None


# PythonString isn't a top-level token that appears on a command line. An Expression is defined as
# everything in between a top-level ( and the matching ). Everything delimited by those parens is
# simply passed to Python's eval. However, in order to do the matching, any parens inside a Python
# string (which could be part of the Expression) must be ignored.
#
# Python string literals are specified here:
# https://docs.python.org/3/reference/lexical_analysis.html#string-and-bytes-literals.
class PythonString(Token):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous)
        self.string = None
        self.scan()

    def __repr__(self):
        return self.string

    def value(self, parser):
        return self.string

    # TODO: string prefixes
    # TODO: Multiline (triple quoted only)
    # TODO: \octal
    # TODO: \hex
    # TODO: \N
    # TODO: \u
    # TODO: \U
    def scan(self):
        chars = []
        quote = self.next_char()
        assert quote in Token.QUOTES
        triple_quote = self.advance_if_triple(quote)
        while True:
            c = self.next_char()
            if c is None:
                raise MalformedStringError(self.text, "Not a python string")
            elif c in Token.QUOTES:
                # Possible ending quoted sequence
                if c == quote:
                    if triple_quote:
                        if self.advance_if_triple(quote):
                            # Ended triple quote
                            break
                        else:
                            chars.append(c)
                    else:
                        # Ended single quote
                        break
                else:
                    chars.append(c)
            elif c == Token.ESCAPE_CHAR:
                c = self.next_char()
                if c in Token.ESCAPABLE:
                    chars.append(c)
                else:
                    chars.append(Token.ESCAPE_CHAR)
                    chars.append(c)
            elif c.isspace():
                if quote:
                    # Space is inside quoted sequence
                    chars.append(c)
                else:
                    break
            else:
                chars.append(c)
        self.string = ''.join(chars)

    def advance_if_triple(self, quote):
        assert quote is not None
        if self.remaining() >= 2 and self.text[self.end:self.end + 2] == quote * 2:
            self.end += 2
            return True
        else:
            return False


class Expression(Token):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous)
        self._source = None
        self._function = None
        self.scan()

    def value(self, parser):
        if self._function is None:
            source = self.source()
            globals = parser.env.namespace
            split = source.split()
            if len(split) == 0:
                raise marcel.exception.KillCommandException(f'Empty function definition.')
            if split[0] in ('lambda', 'lambda:'):
                function = eval(source, globals)
            else:
                try:
                    function = eval('lambda ' + source, globals)
                    source = 'lambda ' + source
                except Exception:
                    try:
                        function = eval('lambda: ' + source, globals)
                        source = 'lambda: ' + source
                    except Exception:
                        raise marcel.exception.KillCommandException(f'Invalid function syntax: {source}')
            # Each pipeline with parameters, containing this function, introduces a layer of wrapping.
            pipelines = parser.current_pipelines
            parameterized_pipelines = []
            for i in range(pipelines.size()):
                pipeline = pipelines.top(i)
                if pipeline.params is not None:
                    param_list = ', '.join(pipeline.parameters())
                    source = f'lambda {param_list}: {source}'
                    parameterized_pipelines.append(pipeline)
            if len(parameterized_pipelines) > 0:
                function = eval(source, globals)
            self._function = marcel.functionwrapper.FunctionWrapper(function=function,
                                                                    source=source,
                                                                    parameterized_pipelines=parameterized_pipelines)
        return self._function
    
    def is_expr(self):
        return True

    def source(self):
        if self._source is None:
            self._source = self.text[self.start + 1:self.end - 1]
        return self._source

    def scan(self):
        c = self.next_char()
        assert c == Token.OPEN
        nesting = 1
        while nesting > 0:
            c = self.next_char()
            if c is None:
                break
            elif c == Token.OPEN:
                nesting += 1
            elif c == Token.CLOSE:
                nesting -= 1
            elif c in Token.QUOTES:
                self.end = PythonString(self.text, self.end - 1, False).end
        if self.text[self.end - 1] != Token.CLOSE:
            raise marcel.exception.KillCommandException(
                f'Malformed Python expression {self.text[self.start:self.end]}')


class String(Token):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, 0 if position is None else position, adjacent_to_previous)
        if position is None:
            # Text is fine as is.
            self.string = text
        else:
            # Text is from the input being parsed. Scan it to deal with escapes and quotes.
            self.string = None
            self.scan()

    def value(self, parser):
        return self.string

    def is_string(self):
        return True

    def op_name(self):
        # This should only being called for the first op following START
        return self.string

    def scan(self):
        quote = None
        chars = []
        while True:
            c = self.next_char()
            if c is None:
                break
            elif c.isspace() or c in Token.STRING_TERMINATING:
                if quote is None:
                    # c is part of the next token
                    self.end -= 1
                    break
                else:
                    chars.append(c)
            elif c in Token.QUOTES:
                if quote is None:
                    quote = c
                elif c == quote:
                    quote = None
                else:
                    chars.append(c)
            elif c == Token.ESCAPE_CHAR:
                if quote is None:
                    # TODO: ESCAPE at end of line
                    c = self.next_char()
                    chars.append(c)
                elif quote == Token.SINGLE_QUOTE:
                    chars.append(c)
                elif quote == Token.DOUBLE_QUOTE:
                    # TODO: no next char
                    c = self.next_char()
                    # TODO: Other escaped chars inside double quotes
                    if c == Token.ESCAPE_CHAR:
                        chars.append(c)
                    else:
                        chars.append(Token.ESCAPE_CHAR)
                        chars.append(c)
                else:
                    raise marcel.exception.KillCommandException(
                        f'Malformed string: {self.text[self.start:self.end]}')
            else:
                chars.append(c)
        self.string = ''.join(chars)


class Run(Token):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous)
        self.symbol = None
        self.scan()  # Sets self.symbol

    def value(self, parser):
        return self.symbol

    def is_bang(self):
        return True

    def op_name(self):
        return 'run'

    def scan(self):
        c = self.next_char()
        assert c == Token.BANG
        c = self.peek_char()
        if c == Token.BANG:
            self.next_char()
            self.symbol = '!!'
        else:
            self.symbol = '!'


class OneCharSymbol(Token):

    def __init__(self, text, position, adjacent_to_previous, symbol):
        super().__init__(text, position, adjacent_to_previous)
        self.symbol = symbol
        self.end += 1

    def value(self, parser):
        return self.symbol


class Pipe(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.PIPE)

    def is_pipe(self):
        return True


class Fork(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.FORK)

    def is_fork(self):
        return True

    def op_name(self):
        return 'fork'


class Begin(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.BEGIN)

    def is_begin(self):
        return True


class End(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.END)

    def is_end(self):
        return True


class Assign(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.ASSIGN)

    def is_assign(self):
        return True

    def op_name(self):
        return 'assign'


class Comma(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.COMMA)

    def is_comma(self):
        return True


class Colon(OneCharSymbol):

    def __init__(self, text, position, adjacent_to_previous):
        super().__init__(text, position, adjacent_to_previous, Token.COLON)

    def is_colon(self):
        return True


class ImpliedMap(Token):

    def __init__(self):
        super().__init__(None, None, False)

    def op_name(self):
        return 'map'


# ----------------------------------------------------------------------------------------------------------------------

# Lexing


class Lexer(Source):

    def __init__(self, env, text):
        super().__init__(text)
        self.env = env

    def tokens(self):
        tokens = []
        token = self.next_token()
        while token is not None:
            tokens.append(token)
            token = self.next_token()
        return self.consolidate_adjacent(tokens)

    def next_token(self):
        token = None
        skipped = self.skip_whitespace()
        c = self.peek_char()
        if c is not None:
            adjacent_to_previous = self.end > 0 and skipped == 0
            if c == Token.OPEN:
                token = Expression(self.text, self.end, adjacent_to_previous)
            elif c == Token.CLOSE:
                raise ParseError('Unmatched )')
            elif c == Token.PIPE:
                token = Pipe(self.text, self.end, adjacent_to_previous)
            elif c == Token.BEGIN:
                token = Begin(self.text, self.end, adjacent_to_previous)
            elif c == Token.END:
                token = End(self.text, self.end, adjacent_to_previous)
            elif c == Token.FORK:
                token = Fork(self.text, self.end, adjacent_to_previous)
            elif c == Token.BANG:
                token = Run(self.text, self.end, adjacent_to_previous)
            elif c == Token.ASSIGN:
                token = Assign(self.text, self.end, adjacent_to_previous)
            elif c == Token.COMMA:
                token = Comma(self.text, self.end, adjacent_to_previous)
            elif c == Token.COLON:
                token = Colon(self.text, self.end, adjacent_to_previous)
            elif c == Token.COMMENT:
                # Ignore the rest of the line
                return None
            else:
                token = String(self.text, self.end, adjacent_to_previous)
            self.end = token.end
        return token

    def skip_whitespace(self):
        before = self.end
        c = self.peek_char()
        while c is not None and c.isspace():
            self.next_char()
            c = self.peek_char()
        after = self.end
        return after - before

    # Adjacent String and Expression tokens must be consolidated. Turn them into an Expression that concatenates
    # the values.
    def consolidate_adjacent(self, tokens):
        def eligible(token):
            return token.is_string() or token.is_expr()

        def consolidate(start, end):
            if end == start + 1:
                token = tokens[start]
            else:
                # Generate a new Expression token that combines the strings and expressions into
                # a Python f'...' string.
                buffer = ["(f'''"]
                t = start
                while t < end:
                    token = tokens[t]
                    t += 1
                    if token.is_string():
                        buffer.append(token.value(None))
                    else:
                        buffer.extend(['{', token.source(), '}'])
                buffer.append("''')")
                token = Expression(''.join(buffer), 0, False)
            return token

        consolidated = []
        n = len(tokens)
        start = 0
        while start < n:
            while start < n and not eligible(tokens[start]):
                consolidated.append(tokens[start])
                start += 1
            end = start + 1
            while end < n and eligible(tokens[end]) and tokens[end].adjacent_to_previous:
                end += 1
            if start < n:
                consolidated.append(consolidate(start, end))
            start = end
        return consolidated

# ----------------------------------------------------------------------------------------------------------------------

# Parsing

# Grammar:
#
#     command:
#             assignment
#             pipeline
#    
#     assignment:
#             var = arg
#    
#     pipeline:
#             op_sequence
#
#     op_sequence:
#             op_args | op_sequence
#             op_args
#    
#     op_args:
#             op arg*
#             expr
#    
#     op:
#             str
#             @
#             !
#             !!
#    
#     arg:
#             expr
#             str
#             begin [vars :] pipeline end
#
#     vars:
#             vars, var
#             var
#
#     var: str
#
#     expr: Expression
#
#     str: String
#
#     begin: [
#
#     end: ]


# Used mainly by TabCompleter.
class CurrentOp:

    def __init__(self, parser, op_token):
        op_name = op_token.op_name()
        op_module = parser.op_modules.get(op_name, None)
        if op_module:
            self.op = op_module.create_op()
            self.args_parser = op_module.args_parser()
        else:
            self.op = None
            self.args_parser = None
        self.processing_args = False

    def __repr__(self):
        return f'CurrentOp({self.op.op_name()})' if self.op else 'CurrentOp(<not builtin>)'

    @property
    def flags(self):
        return self.args_parser.flags() if self.args_parser else None


class Parser:

    def __init__(self, text, main):
        self.text = text
        self.env = main.env
        self.op_modules = main.op_modules
        self.tokens = Lexer(self.env, text).tokens()
        self.t = 0
        self.token = None  # The current token
        self.current_ops = marcel.util.Stack()
        self.current_pipelines = marcel.util.Stack()
        # For use by TabCompleter
        self.current_op = None

    def parse(self):
        if len(self.tokens) == 0:
            raise EmptyCommand()
        return self.command()

    def command(self):
        if self.next_token(String, Assign):
            return self.assignment(self.token.value(self))
        else:
            return self.pipeline(None)

    def assignment(self, var):
        self.next_token(Assign)
        arg = self.arg()
        if isinstance(arg, Token):
            value = arg.value(self)
        elif type(arg) is marcel.core.Pipeline:
            value = arg
        elif arg is None:
            raise UnexpectedTokenError(self.token, 'Unexpected token type.')
        else:
            assert False, arg
        op = self.create_assignment(var, value)
        return op

    def pipeline(self, parameters):
        pipeline = marcel.core.Pipeline()
        pipeline.set_parameters(parameters)
        self.current_pipelines.push(pipeline)
        op_sequence = Parser.ensure_sequence(self.op_sequence())
        op_sequence.reverse()
        for op_args in op_sequence:
            pipeline.append(op_args)
        self.current_pipelines.pop()
        return pipeline

    # Accumulates ops in REVERSE order, to avoid list prepend.
    # Top-level caller needs to reverse the result..
    def op_sequence(self):
        op_args = self.op_args()
        if self.next_token(Pipe):
            op_sequence = Parser.ensure_sequence(self.op_sequence())
            op_sequence.append(op_args)
            return op_sequence
        else:
            return op_args

    def op_args(self):
        if self.next_token(Expression):
            return self.create_map(self.token)
        else:
            op_token = self.op()
            self.current_op = CurrentOp(self, op_token)
            self.current_ops.push(self.current_op)
            arg_tokens = []
            arg_token = self.arg()
            while arg_token is not None:
                self.current_op.processing_args = True
                arg_tokens.append(arg_token)
                arg_token = self.arg()
            op = self.create_op(op_token, arg_tokens)
            self.current_op = self.current_ops.pop()
            return op

    def op(self):
        if self.next_token(String) or self.next_token(Fork) or self.next_token(Run):
            return self.token
        elif self.next_token():
            raise UnexpectedTokenError(self.token, f'Unexpected token type: {self.token}')
        else:
            raise PrematureEndError()

    def arg(self):
        if self.next_token(Begin):
            # If the next tokens are var comma, or var colon, then we have
            # pipeline variables being declared.
            if self.next_token(String, Comma) or self.next_token(String, Colon):
                pipeline_parameters = self.vars()
            else:
                pipeline_parameters = None
            pipeline = self.pipeline(pipeline_parameters)
            self.next_token(End)
            return pipeline
        elif self.next_token(String) or self.next_token(Expression):
            return self.token
        else:
            return None

    def vars(self):
        vars = []
        while self.token.is_string():
            vars.append(self.token.value(self))
            if self.next_token(Comma):
                if not self.next_token(String):
                    self.next_token()
                    raise UnexpectedTokenError(self.token, f'Expected a var, found {self.token}')
            else:
                self.next_token()  # Should be string or colon
        # Shouldn't have called vars() unless the token (on entry) was a string.
        assert len(vars) > 0
        if not self.token.is_colon():
            raise UnexpectedTokenError(self.token, f'Expected comma or colon, found {self.token}')
        return vars

    # Returns True if a qualifying token was found, and sets self.token to it.
    # Returns False if a qualifying token was not found, and leaves self.token unchanged.
    def next_token(self, *expected_token_types):
        n = len(expected_token_types)
        if self.t + n <= len(self.tokens):
            for i in range(n):
                if type(self.tokens[self.t + i]) is not expected_token_types[i]:
                    return False
            if self.t < len(self.tokens):
                self.token = self.tokens[self.t]
                self.t += 1
                return True
        return False

    @staticmethod
    def raise_unexpected_token_error(token, message):
        raise UnexpectedTokenError(token, message)

    def create_op(self, op_token, arg_tokens):
        op = self.create_op_builtin(op_token, arg_tokens)
        if op is None:
            op = self.create_op_executable(op_token, arg_tokens)
        if op is None:
            op = self.create_op_variable(op_token, arg_tokens)
        return op

    def create_op_builtin(self, op_token, arg_tokens):
        current_op = self.current_ops.top()
        if current_op.op is None:
            return None
        op = current_op.op
        op_name = op_token.op_name()
        # Both ! and !! map to the run op.
        if op_name == 'run':
            # !: Expect a command number
            # !!: Don't expect a command number, run the previous command
            # else: 'run' was entered
            op.expected_args = (1 if op_token.value(self) == '!' else
                                0 if op_token.value(self) == '!!' else None)
        args = []
        if op_name == 'bash':
            for x in arg_tokens:
                args.append(x.raw() if type(x) is String else
                            x.value(self) if isinstance(x, Token) else
                            x)
        else:
            for x in arg_tokens:
                args.append(x.value(self) if isinstance(x, Token) else x)
        current_op.args_parser.parse(args, op)
        return op

    def create_op_variable(self, op_token, arg_tokens):
        var = op_token.value(self)
        op_module = self.op_modules['runpipeline']
        op = op_module.create_op()
        op.var = var
        if len(arg_tokens) > 0:
            pipeline_args = []
            for token in arg_tokens:
                pipeline_args.append(token
                                     if type(token) is marcel.core.Pipeline else
                                     token.value(self))
            args, kwargs = marcel.argsparser.PipelineArgsParser(var).parse_pipeline_args(pipeline_args)
            op.set_pipeline_args(args, kwargs)
        return op

    def create_op_executable(self, op_token, arg_tokens):
        op = None
        name = op_token.value(self)
        if marcel.util.is_executable(name):
            args = [name]
            for x in arg_tokens:
                args.append(x.raw() if type(x) is String else
                            x.value(self) if isinstance(x, Token) else
                            x)
            op = marcel.opmodule.create_op(self.env, 'bash', *args)
        return op

    def create_assignment(self, var, value):
        assign_module = self.op_modules['assign']
        assert assign_module is not None
        op = assign_module.create_op()
        op.var = var
        if callable(value):
            op.function = value
        elif type(value) is marcel.core.Pipeline:
            op.pipeline = value
        elif type(value) is str:
            op.string = value
        else:
            assert False, value
        pipeline = marcel.core.Pipeline()
        pipeline.append(op)
        return pipeline

    def create_map(self, expr):
        assert type(expr) is Expression
        return marcel.opmodule.create_op(self.env, 'map', expr.value(self))

    @staticmethod
    def ensure_sequence(x):
        if not marcel.util.is_sequence_except_string(x):
            x = [x]
        return x
