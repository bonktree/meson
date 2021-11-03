#!/usr/bin/python3

'''This file generates completion function definitions for Zsh.'''
# NB: the function definitions are directly passed to the `eval` builtin.
# We must take care not to trust meson introspect's output
# and prevent e. g. code injection.

import json
import os
import sys
from shlex import quote


def fsemic(s):
    return s.replace(':', r'\:').replace(r'\\:', r'\:')


def dsemic(s):
    return s.replace(':', r'\\:')


def c_style_octal(i):
    return '0{:03}'.format(int(oct(i)[2:]))


def generate_choices(optentry):
    '''If a build option can be set to a limited number of values,
       return an iterable of possible values. Otherwise, return None.
    '''
    if optentry['type'] in ('combo', ):
        return optentry.get('choices', [])
    if optentry['type'] in ('boolean', ):
        return ('false', 'true')
    return None


def simple_hint(i):
    return '<{}>'.format(i)


def generate_hint(optentry):
    '''Produce a string representation of a build option's current value.
    '''
    v = optentry['value']

    if optentry['type'] in ('boolean', ):
        return simple_hint('true' if v else 'false')
    if optentry['name'] == 'install_umask':
        return simple_hint(c_style_octal(v))
    if optentry['type'] in ('integer', ):
        return simple_hint(int(v))

    return simple_hint(repr(v))


def zsh_tag(k):

    def asciify(c):
        return c if ord(c) < 0x80 and c.isalnum() else '-'

    return ''.join(map(asciify, k))


def generate_compadd_choices(o):
    '''Generate a compadd invocation with value choices.'''
    # We want to display a readably quoted description string which does
    # not garble single quotes inside the string. shlex.quote() works fine,
    # but uses single quotes on the outside and escapes single quotes as
    # '"'"', which is suboptimal to be read by humans. So we use zsh's
    # builtin (qqq) expansion modifier and not shlex.quote().
    decl = 'descr=' + quote(o['description'])
    value_descr = r'${(qqq)descr//\%/%%}' + quote(' ({})'.format(o['type']))
    choices = generate_choices(o)
    if choices is not None:
        compadd = (
            '_wanted',
            '-V',
            'build-option-values',
            'expl',
            value_descr,
            'compadd -',
            ' '.join(quote(i) for i in generate_choices(o)),
        )
    else:
        compadd = (
            '_message',
            '-e',
            'build-option-values',
            value_descr,
        )
    compadd = ' '.join(compadd)
    return '\n'.join((
        '    ' + decl,
        '    ' + compadd,
    ))


def complete_build_options(i_data):
    by_section = dict()
    switch_entries = dict()
    for opt in i_data:
        # Generate a _describe item spec.
        gr = opt['section']
        name = opt['name']
        descr = '{} {}'.format(opt['description'], generate_hint(opt))
        describe_spec = '{}:{}'.format(fsemic(name), fsemic(descr))
        by_section.setdefault(gr, [])
        by_section[gr].append(quote(describe_spec))

        switch_entries[name] = '\n'.join((
            '  ("{}")'.format(name),
            generate_compadd_choices(opt),
            '  ;;',
        ))

    def user_first(d):
        dd = d.copy()
        try:
            u = dd.pop('user')
            yield ('user', u)
        except KeyError:
            pass
        yield from dd.items()

    alt_decls = []
    alt_words = []
    functions_per_type = []
    for k, v in user_first(by_section):
        tag_prefix = zsh_tag(k)
        specs_arr = '__ndescgroup_{}'.format(tag_prefix)
        # No need to quote; `v` already consists of quoted _describe specs.
        sv = '  local -a {}=(\n    {}\n  )'.format(specs_arr, '\n    '.join(v))
        alt_decls.append(sv)
        word = '{}-options:{} option:(( "${{(@){}}}" ))'.format(
            tag_prefix, k, specs_arr)
        alt_words.append(quote(word))
    sv = '\n'.join((
         '__meson_project_buildoptions() {',
         '  # This function loops over tag labels itself.',
         '\n'.join(alt_decls),
         '  local -a alternative_argv=( "$@" )',
         '  _alternative -O alternative_argv {}'.format(' '.join(alt_words)),
         '}\n'))
    functions_per_type.append(sv)
    sv = '\n'.join((
        '__meson_project_buildoption_choices() {',
        '  # This function loops over tag labels itself.',
        '  local m_optname="$1"',
        '  local descr',
        '  case "$m_optname" in',
        '\n'.join(switch_entries.values()),
        '  *)',
        '    _message "unknown option; cannot offer choices"'
        '  ;;',
        '  esac',
        '}\n',
    ))
    functions_per_type.append(sv)
    funcs = '\n'.join(functions_per_type)
    return funcs


def emit_message_on_exception(exc):
    from traceback import format_exception_only
    lines = format_exception_only(type(exc), exc)
    mfmt = 'cannot complete: {}'
    msgs = [quote(mfmt.format(line.rstrip())) for line in lines]
    print('__meson_project_buildoptions () {',
          '\n'.join('  ' + '_message ' + msg for msg in msgs),
          '}',
          '__meson_project_buildoption_choices () {',
          '\n'.join('  ' + '_message ' + msg for msg in msgs),
          '}',
          sep='\n')


def path_from_builddir(builddir, mode):
    return os.path.join(builddir, 'meson-info', f'intro-{mode}.json')


def _getopts(argv):
    builddir = None
    istream = None
    mode = None
    posopts = 0
    for i in argv:
        if i.startswith('--'):
            mode = i[2:]
        else:
            if posopts > 0:
                continue
            posopts += 1
            builddir = i
    if mode is None:
        raise ValueError("completion mode is not specified")
    if mode not in ('buildoptions', ):
        raise ValueError("unknown completion mode: {}".format(mode))
    if builddir is None or builddir == '-':
        istream = sys.stdin
    else:
        p = path_from_builddir(builddir, mode)
        istream = open(p)
    return {
        'istream': istream,
        'mode': mode,
        'builddir': builddir,
    }


def main(argv):
    try:
        a = _getopts(argv)

        istream = a['istream']
        with istream:
            jd = json.load(istream)
        print(complete_build_options(jd))
        return 0
    except Exception as e:
        emit_message_on_exception(e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
