# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0
# For details: https://github.com/nedbat/coveragepy/blob/master/NOTICE.txt

"""File wrangling."""

import hashlib
import ntpath
import os
import os.path
import posixpath
import re
import sys

from coverage import env
from coverage.exceptions import ConfigError
from coverage.misc import contract, human_sorted, isolate_module, join_regex


os = isolate_module(os)


def set_relative_directory():
    """Set the directory that `relative_filename` will be relative to."""
    global RELATIVE_DIR, CANONICAL_FILENAME_CACHE

    # The current directory
    abs_curdir = abs_file(os.curdir)
    if not abs_curdir.endswith(os.sep):
        # Suffix with separator only if not at the system root
        abs_curdir = abs_curdir + os.sep

    # The absolute path to our current directory.
    RELATIVE_DIR = os.path.normcase(abs_curdir)

    # Cache of results of calling the canonical_filename() method, to
    # avoid duplicating work.
    CANONICAL_FILENAME_CACHE = {}


def relative_directory():
    """Return the directory that `relative_filename` is relative to."""
    return RELATIVE_DIR


@contract(returns='unicode')
def relative_filename(filename):
    """Return the relative form of `filename`.

    The file name will be relative to the current directory when the
    `set_relative_directory` was called.

    """
    fnorm = os.path.normcase(filename)
    if fnorm.startswith(RELATIVE_DIR):
        filename = filename[len(RELATIVE_DIR):]
    return filename


@contract(returns='unicode')
def canonical_filename(filename):
    """Return a canonical file name for `filename`.

    An absolute path with no redundant components and normalized case.

    """
    if filename not in CANONICAL_FILENAME_CACHE:
        cf = filename
        if not os.path.isabs(filename):
            for path in [os.curdir] + sys.path:
                if path is None:
                    continue
                f = os.path.join(path, filename)
                try:
                    exists = os.path.exists(f)
                except UnicodeError:
                    exists = False
                if exists:
                    cf = f
                    break
        cf = abs_file(cf)
        CANONICAL_FILENAME_CACHE[filename] = cf
    return CANONICAL_FILENAME_CACHE[filename]


MAX_FLAT = 100

@contract(filename='unicode', returns='unicode')
def flat_rootname(filename):
    """A base for a flat file name to correspond to this file.

    Useful for writing files about the code where you want all the files in
    the same directory, but need to differentiate same-named files from
    different directories.

    For example, the file a/b/c.py will return 'd_86bbcbe134d28fd2_c_py'

    """
    dirname, basename = ntpath.split(filename)
    if dirname:
        fp = hashlib.new("sha3_256", dirname.encode("UTF-8")).hexdigest()[:16]
        prefix = f"d_{fp}_"
    else:
        prefix = ""
    return prefix + basename.replace(".", "_")


if env.WINDOWS:

    _ACTUAL_PATH_CACHE = {}
    _ACTUAL_PATH_LIST_CACHE = {}

    def actual_path(path):
        """Get the actual path of `path`, including the correct case."""
        if path in _ACTUAL_PATH_CACHE:
            return _ACTUAL_PATH_CACHE[path]

        head, tail = os.path.split(path)
        if not tail:
            # This means head is the drive spec: normalize it.
            actpath = head.upper()
        elif not head:
            actpath = tail
        else:
            head = actual_path(head)
            if head in _ACTUAL_PATH_LIST_CACHE:
                files = _ACTUAL_PATH_LIST_CACHE[head]
            else:
                try:
                    files = os.listdir(head)
                except Exception:
                    # This will raise OSError, or this bizarre TypeError:
                    # https://bugs.python.org/issue1776160
                    files = []
                _ACTUAL_PATH_LIST_CACHE[head] = files
            normtail = os.path.normcase(tail)
            for f in files:
                if os.path.normcase(f) == normtail:
                    tail = f
                    break
            actpath = os.path.join(head, tail)
        _ACTUAL_PATH_CACHE[path] = actpath
        return actpath

else:
    def actual_path(path):
        """The actual path for non-Windows platforms."""
        return path


@contract(returns='unicode')
def abs_file(path):
    """Return the absolute normalized form of `path`."""
    return actual_path(os.path.abspath(os.path.realpath(path)))


def python_reported_file(filename):
    """Return the string as Python would describe this file name."""
    if env.PYBEHAVIOR.report_absolute_files:
        filename = os.path.abspath(filename)
    return filename


RELATIVE_DIR = None
CANONICAL_FILENAME_CACHE = None
set_relative_directory()


def isabs_anywhere(filename):
    """Is `filename` an absolute path on any OS?"""
    return ntpath.isabs(filename) or posixpath.isabs(filename)


def prep_patterns(patterns):
    """Prepare the file patterns for use in a `GlobMatcher`.

    If a pattern starts with a wildcard, it is used as a pattern
    as-is.  If it does not start with a wildcard, then it is made
    absolute with the current directory.

    If `patterns` is None, an empty list is returned.

    """
    prepped = []
    for p in patterns or []:
        if p.startswith(("*", "?")):
            prepped.append(p)
        else:
            prepped.append(abs_file(p))
    return prepped


class TreeMatcher:
    """A matcher for files in a tree.

    Construct with a list of paths, either files or directories. Paths match
    with the `match` method if they are one of the files, or if they are
    somewhere in a subtree rooted at one of the directories.

    """
    def __init__(self, paths, name="unknown"):
        self.original_paths = human_sorted(paths)
        self.paths = list(map(os.path.normcase, paths))
        self.name = name

    def __repr__(self):
        return f"<TreeMatcher {self.name} {self.original_paths!r}>"

    def info(self):
        """A list of strings for displaying when dumping state."""
        return self.original_paths

    def match(self, fpath):
        """Does `fpath` indicate a file in one of our trees?"""
        fpath = os.path.normcase(fpath)
        for p in self.paths:
            if fpath.startswith(p):
                if fpath == p:
                    # This is the same file!
                    return True
                if fpath[len(p)] == os.sep:
                    # This is a file in the directory
                    return True
        return False


class ModuleMatcher:
    """A matcher for modules in a tree."""
    def __init__(self, module_names, name="unknown"):
        self.modules = list(module_names)
        self.name = name

    def __repr__(self):
        return f"<ModuleMatcher {self.name} {self.modules!r}>"

    def info(self):
        """A list of strings for displaying when dumping state."""
        return self.modules

    def match(self, module_name):
        """Does `module_name` indicate a module in one of our packages?"""
        if not module_name:
            return False

        for m in self.modules:
            if module_name.startswith(m):
                if module_name == m:
                    return True
                if module_name[len(m)] == '.':
                    # This is a module in the package
                    return True

        return False


class GlobMatcher:
    """A matcher for files by file name pattern."""
    def __init__(self, pats, name="unknown"):
        self.pats = list(pats)
        self.re = globs_to_regex(self.pats, case_insensitive=env.WINDOWS)
        self.name = name

    def __repr__(self):
        return f"<GlobMatcher {self.name} {self.pats!r}>"

    def info(self):
        """A list of strings for displaying when dumping state."""
        return self.pats

    def match(self, fpath):
        """Does `fpath` match one of our file name patterns?"""
        return self.re.match(fpath) is not None


def sep(s):
    """Find the path separator used in this string, or os.sep if none."""
    sep_match = re.search(r"[\\/]", s)
    if sep_match:
        the_sep = sep_match[0]
    else:
        the_sep = os.sep
    return the_sep


# Tokenizer for _glob_to_regex.
# None as a sub means disallowed.
G2RX_TOKENS = [(re.compile(rx), sub) for rx, sub in [
    (r"\*\*\*+", None),             # Can't have ***
    (r"[^/]+\*\*+", None),          # Can't have x**
    (r"\*\*+[^/]+", None),          # Can't have **x
    (r"\*\*/\*\*", None),           # Can't have **/**
    (r"^\*+/", r"(.*[/\\\\])?"),    # ^*/ matches any prefix-slash, or nothing.
    (r"/\*+$", r"[/\\\\].*"),       # /*$ matches any slash-suffix.
    (r"\*\*/", r"(.*[/\\\\])?"),    # **/ matches any subdirs, including none
    (r"/", r"[/\\\\]"),             # / matches either slash or backslash
    (r"\*", r"[^/\\\\]*"),          # * matches any number of non slash-likes
    (r"\?", r"[^/\\\\]"),           # ? matches one non slash-like
    (r"\[.*?\]", r"\g<0>"),         # [a-f] matches [a-f]
    (r"[a-zA-Z0-9_-]+", r"\g<0>"),  # word chars match themselves
    (r"[\[\]+{}]", None),           # Can't have regex special chars
    (r".", r"\\\g<0>"),             # Anything else is escaped to be safe
]]

def _glob_to_regex(pattern):
    """Convert a file-path glob pattern into a regex."""
    # Turn all backslashes into slashes to simplify the tokenizer.
    pattern = pattern.replace("\\", "/")
    if "/" not in pattern:
        pattern = "**/" + pattern
    path_rx = []
    pos = 0
    while pos < len(pattern):
        for rx, sub in G2RX_TOKENS:                     # pragma: always breaks
            m = rx.match(pattern, pos=pos)
            if m:
                if sub is None:
                    raise ConfigError(f"File pattern can't include {m[0]!r}")
                path_rx.append(m.expand(sub))
                pos = m.end()
                break
    return "".join(path_rx)


def globs_to_regex(patterns, case_insensitive=False, partial=False):
    """Convert glob patterns to a compiled regex that matches any of them.

    Slashes are always converted to match either slash or backslash, for
    Windows support, even when running elsewhere.

    If the pattern has no slash or backslash, then it is interpreted as
    matching a file name anywhere it appears in the tree.  Otherwise, the glob
    pattern must match the whole file path.

    If `partial` is true, then the pattern will match if the target string
    starts with the pattern. Otherwise, it must match the entire string.

    Returns: a compiled regex object.  Use the .match method to compare target
    strings.

    """
    flags = 0
    if case_insensitive:
        flags |= re.IGNORECASE
    rx = join_regex(map(_glob_to_regex, patterns))
    if not partial:
        rx = rf"(?:{rx})\Z"
    compiled = re.compile(rx, flags=flags)
    return compiled


class PathAliases:
    """A collection of aliases for paths.

    When combining data files from remote machines, often the paths to source
    code are different, for example, due to OS differences, or because of
    serialized checkouts on continuous integration machines.

    A `PathAliases` object tracks a list of pattern/result pairs, and can
    map a path through those aliases to produce a unified path.

    """
    def __init__(self, debugfn=None, relative=False):
        self.aliases = []   # A list of (original_pattern, regex, result)
        self.debugfn = debugfn or (lambda msg: 0)
        self.relative = relative
        self.pprinted = False

    def pprint(self):
        """Dump the important parts of the PathAliases, for debugging."""
        self.debugfn(f"Aliases (relative={self.relative}):")
        for original_pattern, regex, result in self.aliases:
            self.debugfn(f" Rule: {original_pattern!r} -> {result!r} using regex {regex.pattern!r}")

    def add(self, pattern, result):
        """Add the `pattern`/`result` pair to the list of aliases.

        `pattern` is an `glob`-style pattern.  `result` is a simple
        string.  When mapping paths, if a path starts with a match against
        `pattern`, then that match is replaced with `result`.  This models
        isomorphic source trees being rooted at different places on two
        different machines.

        `pattern` can't end with a wildcard component, since that would
        match an entire tree, and not just its root.

        """
        original_pattern = pattern
        pattern_sep = sep(pattern)

        if len(pattern) > 1:
            pattern = pattern.rstrip(r"\/")

        # The pattern can't end with a wildcard component.
        if pattern.endswith("*"):
            raise ConfigError("Pattern must not end with wildcards.")

        # The pattern is meant to match a filepath.  Let's make it absolute
        # unless it already is, or is meant to match any prefix.
        if not pattern.startswith('*') and not isabs_anywhere(pattern + pattern_sep):
            pattern = abs_file(pattern)
        if not pattern.endswith(pattern_sep):
            pattern += pattern_sep

        # Make a regex from the pattern.
        regex = globs_to_regex([pattern], case_insensitive=True, partial=True)

        # Normalize the result: it must end with a path separator.
        result_sep = sep(result)
        result = result.rstrip(r"\/") + result_sep
        self.aliases.append((original_pattern, regex, result))

    def map(self, path, exists=os.path.exists):
        """Map `path` through the aliases.

        `path` is checked against all of the patterns.  The first pattern to
        match is used to replace the root of the path with the result root.
        Only one pattern is ever used.  If no patterns match, `path` is
        returned unchanged.

        The separator style in the result is made to match that of the result
        in the alias.

        `exists` is a function to determine if the resulting path actually
        exists.

        Returns the mapped path.  If a mapping has happened, this is a
        canonical path.  If no mapping has happened, it is the original value
        of `path` unchanged.

        """
        if not self.pprinted:
            self.pprint()
            self.pprinted = True

        for original_pattern, regex, result in self.aliases:
            m = regex.match(path)
            if m:
                new = path.replace(m[0], result)
                new = new.replace(sep(path), sep(result))
                if not self.relative:
                    new = canonical_filename(new)
                dot_start = result.startswith(("./", ".\\")) and len(result) > 2
                if new.startswith(("./", ".\\")) and not dot_start:
                    new = new[2:]
                if not exists(new):
                    continue
                self.debugfn(
                    f"Matched path {path!r} to rule {original_pattern!r} -> {result!r}, " +
                    f"producing {new!r}"
                )
                return new

        # If we get here, no pattern matched.

        if self.relative and not isabs_anywhere(path):
            parts = re.split(r"[/\\]", path)
            if len(parts) > 1:
                dir1 = parts[0]
                pattern = f"*/{dir1}"
                regex = rf"^(.*[\\/])?{re.escape(dir1)}[\\/]"
                result = f"{dir1}{os.sep}"
                self.debugfn(f"Generating rule: {pattern!r} -> {result!r} using regex {regex!r}")
                self.aliases.append((pattern, re.compile(regex), result))
                return self.map(path, exists=exists)

        self.debugfn(f"No rules match, path {path!r} is unchanged")
        return path


def find_python_files(dirname, include_namespace_packages):
    """Yield all of the importable Python files in `dirname`, recursively.

    To be importable, the files have to be in a directory with a __init__.py,
    except for `dirname` itself, which isn't required to have one.  The
    assumption is that `dirname` was specified directly, so the user knows
    best, but sub-directories are checked for a __init__.py to be sure we only
    find the importable files.

    If `include_namespace_packages` is True, then the check for __init__.py
    files is skipped.

    Files with strange characters are skipped, since they couldn't have been
    imported, and are probably editor side-files.

    """
    for i, (dirpath, dirnames, filenames) in enumerate(os.walk(dirname)):
        if not include_namespace_packages:
            if i > 0 and "__init__.py" not in filenames:
                # If a directory doesn't have __init__.py, then it isn't
                # importable and neither are its files
                del dirnames[:]
                continue
        for filename in filenames:
            # We're only interested in files that look like reasonable Python
            # files: Must end with .py or .pyw, and must not have certain funny
            # characters that probably mean they are editor junk.
            if re.match(r"^[^.#~!$@%^&*()+=,]+\.pyw?$", filename):
                yield os.path.join(dirpath, filename)
