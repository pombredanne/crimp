# -*- coding: utf-8 -*-
"""
The main runtime
"""

import sys
import logging
import locale
import codecs

from argparse import ArgumentParser
from argparse import HelpFormatter
from functools import partial
from io import TextIOWrapper
from io import StringIO
from os.path import abspath

from calmjs.parse import io
from calmjs.parse import rules
from calmjs.parse.exceptions import ECMASyntaxError
from calmjs.parse.lexers.es5 import Lexer
from calmjs.parse.parsers.es5 import parse
from calmjs.parse.unparsers.es5 import Unparser

logger = logging.getLogger(__name__)


class _HelpFormatter(HelpFormatter):
    """
    Help formatter that avoid the splitting of positional arguments from
    the optionals, but implemented in a very coupled manner with the
    intended usage, where the first action is the positional.
    """

    def _format_usage(self, usage, actions, groups, prefix):
        if actions and not actions[0].option_strings:
            actions[0].option_strings = ['']
            actions[0]._optioned = True
        return super(_HelpFormatter, self)._format_usage(
            usage, actions, groups, prefix)

    def _format_actions_usage(self, actions, groups):
        if actions and getattr(actions[0], '_optioned', False):
            actions[0].option_strings = []
        return super(_HelpFormatter, self)._format_actions_usage(
            actions, groups)


def create_argparser(program):
    argparser = ArgumentParser(
        prog=program, formatter_class=_HelpFormatter, add_help=False)
    argparser.add_argument(
        'inputs', metavar='input_file', nargs='*',
        help='path(s) to input file(s)'
    )

    argparser.add_argument(
        '-h', '--help', action='help',
        help='show this help message and exit')
    argparser.add_argument(
        '-O', '--output-path', dest='output', action='store',
        metavar='<output_path>',
        help='output file path')
    argparser.add_argument(
        '-m', '--mangle', dest='mangle', action='store_true',
        default=False,
        help='enable all basic mangling options')
    argparser.add_argument(
        '-p', '--pretty-print', dest='pretty', action='store_true',
        default=False,
        help='use pretty printer (omit for minify printer)')
    argparser.add_argument(
        '-s', '--source-map', dest='source_map', nargs='?',
        default=None, const='', metavar='<sourcemap_path>',
        help='enable source map; filename defaults to <output_path>.map, '
             'if identical to <output_path> it will be written inline as '
             'a data url')

    mangle_group = argparser.add_argument_group('basic mangling options')
    mangle_group.add_argument(
        '-o', '--obfuscate', dest='obfuscate', action='store_true',
        default=False,
        help='obfuscate (mangle) names')
    mangle_group.add_argument(
        '--drop-semi', dest='drop_semi', action='store_true',
        default=False,
        help='drop unneeded semicolons (minify printer only)')

    argparser.add_argument(
        '--indent-width', dest='indent_width', action='store', type=int,
        default=4, metavar='n',
        help='indentation width for pretty printer')
    argparser.add_argument(
        '--encoding', dest='encoding', action='store',
        default=locale.getpreferredencoding(), metavar='<codec>',
        help='the encoding for file-based I/O; stdio relies on system locale')

    return argparser


def parse_args(*argv):
    parser = create_argparser(argv[0])
    # sticking the entire argv into place to group all positionals
    # **before** the options
    values = parser.parse_args(argv)
    # of course, that value must be removed.
    values.inputs = values.inputs[1:]
    return values


def run(inputs, output, mangle, obfuscate, pretty, source_map, indent_width,
        drop_semi, encoding):
    """
    Not a general use method, as sys.exit is called.
    """

    def stdin():
        return (
            sys.stdin
            if isinstance(sys.stdin, (StringIO, TextIOWrapper)) else
            codecs.getreader(sys.stdin.encoding or encoding)(sys.stdin)
        )

    def stdout():
        return (
            sys.stdout
            if isinstance(sys.stdout, (StringIO, TextIOWrapper)) else
            codecs.getwriter(sys.stdout.encoding or encoding)(sys.stdout)
        )

    abs_output = abspath(output) if output else output
    abs_source_map = abspath(source_map) if source_map else source_map

    input_streams = (
        [partial(codecs.open, abspath(p), encoding=encoding) for p in inputs]
        if inputs else
        [stdin]
    )
    output_stream = (
        partial(codecs.open, abs_output, 'w', encoding=encoding)
        if abs_output else
        stdout
    )
    # if source_map is flagged (from empty string, in the const), if
    # no further name is supplied, use the output to build the path,
    # if it is also not stdout.
    source_map_path = (
        abs_output + '.map'
        if source_map == '' and output_stream is not stdout else
        abs_source_map
    )

    if source_map and abs_source_map == abs_output:
        # if a source_map was specified and the absolute paths of that
        # and the output is equal, use the output_stream that was
        # already created.
        sourcemap_stream = output_stream
    else:
        # no source map if source_map path is actually None, and only
        # generate a callable if the source_map_path is not an empty
        # string.
        sourcemap_stream = None if source_map_path is None else (
            partial(codecs.open, source_map_path, 'w', encoding=encoding)
            if source_map_path else
            stdout
        )

    enabled_rules = [rules.minify(drop_semi=drop_semi or mangle)]
    if obfuscate or mangle:
        enabled_rules.append(rules.obfuscate(
            reserved_keywords=Lexer.keywords_dict.keys()
        ))

    if pretty:
        enabled_rules.append(rules.indent(indent_str=' ' * indent_width))

    printer = Unparser(rules=enabled_rules)
    try:
        io.write(
            printer, (io.read(parse, f) for f in input_streams),
            output_stream, sourcemap_stream,
        )
    except ECMASyntaxError as e:
        logger.error('%s', e)
        sys.exit(1)
    except (IOError, OSError) as e:
        logger.error('%s', e)
        if e.args and isinstance(e.args[0], int):
            sys.exit(e.args[0])
        sys.exit(5)  # EIO
    except KeyboardInterrupt:
        sys.exit(130)
    # no need to close any streams as they are callables and that the io
    # read/write functions take care of that.

    sys.exit(0)


def main(*argv):
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.setLevel(logging.WARNING)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        run(**vars(parse_args(*argv)))
    finally:
        root_logger.removeHandler(handler)


if __name__ == '__main__':  # pragma: no cover
    main(*sys.argv)