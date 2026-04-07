import sys


def _tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _wrap(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


def red(t: str) -> str:    return _wrap("31", t)
def green(t: str) -> str:  return _wrap("32", t)
def yellow(t: str) -> str: return _wrap("33", t)
def cyan(t: str) -> str:   return _wrap("36", t)
def bold(t: str) -> str:   return _wrap("1",  t)
def dim(t: str) -> str:    return _wrap("2",  t)
